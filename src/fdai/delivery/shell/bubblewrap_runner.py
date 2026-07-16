"""Credential-free bubblewrap runner for typed local-read commands."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandPlan,
    CommandReceipt,
    CommandRunner,
    CommandStatus,
)

_WORKSPACE_REF = re.compile(r"^workspace:sha256:(?P<digest>[0-9a-f]{64})$")
_SANDBOX_TMP: Final[str] = "/tmp"  # noqa: S108 - private bubblewrap tmpfs
_SANDBOX_RUFF_CACHE: Final[str] = "/tmp/ruff"  # noqa: S108 - inside private tmpfs


class WorkspaceDirectoryResolver(Protocol):
    def resolve(self, workspace_ref: str) -> Path: ...


@dataclass(frozen=True, slots=True)
class DirectoryWorkspaceResolver:
    """Resolve opaque workspace refs beneath one private directory root."""

    root: Path

    def resolve(self, workspace_ref: str) -> Path:
        match = _WORKSPACE_REF.fullmatch(workspace_ref)
        if match is None:
            raise ValueError("workspace_ref MUST be a content-addressed workspace ref")
        root = self.root.resolve(strict=True)
        candidate = root / match.group("digest")
        resolved = candidate.resolve(strict=True)
        if resolved.parent != root or candidate.is_symlink() or not resolved.is_dir():
            raise ValueError("workspace_ref does not resolve to a private workspace directory")
        return resolved


@dataclass(frozen=True, slots=True)
class BubblewrapCommandRunnerConfig:
    bubblewrap_executable: str = "/usr/bin/bwrap"
    executable_paths: Mapping[str, str] = field(default_factory=dict)
    read_only_mounts: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        executables = dict(self.executable_paths or {})
        mounts = dict(self.read_only_mounts or {})
        if not Path(self.bubblewrap_executable).is_absolute():
            raise ValueError("bubblewrap_executable MUST be absolute")
        for executable_ref, path in executables.items():
            if not executable_ref or not Path(path).is_absolute():
                raise ValueError("executable_paths MUST map ids to absolute paths")
        for source, target in mounts.items():
            if not Path(source).is_absolute() or not Path(target).is_absolute():
                raise ValueError("read_only_mounts MUST contain absolute paths")
        object.__setattr__(self, "executable_paths", executables)
        object.__setattr__(self, "read_only_mounts", mounts)


class BubblewrapCommandRunner(CommandRunner):
    """Execute local-read plans in an offline read-only mount namespace."""

    def __init__(
        self,
        *,
        workspaces: WorkspaceDirectoryResolver,
        config: BubblewrapCommandRunnerConfig,
    ) -> None:
        self._workspaces: Final = workspaces
        self._config: Final = config
        self._receipts: dict[str, CommandReceipt] = {}

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        _validate_plan(plan)
        if plan.workspace_ref is None:
            raise ValueError("local command plan requires workspace_ref")
        workspace = self._workspaces.resolve(plan.workspace_ref)
        try:
            executable = self._config.executable_paths[plan.executable_ref]
        except KeyError as exc:
            raise ValueError(f"unregistered executable_ref {plan.executable_ref!r}") from exc
        if plan.dry_run:
            return CommandReceipt(
                status=CommandStatus.PLANNED,
                receipt_ref=_receipt_ref("command-plan", plan),
            )
        prior = self._receipts.get(plan.idempotency_key)
        if prior is not None:
            return CommandReceipt(
                status=CommandStatus.ALREADY_APPLIED,
                receipt_ref=prior.receipt_ref,
                exit_code=prior.exit_code,
                already_existed=True,
            )
        receipt = await self._run(plan=plan, workspace=workspace, executable=executable)
        if receipt.status is CommandStatus.SUCCEEDED:
            self._receipts[plan.idempotency_key] = receipt
        return receipt

    async def _run(
        self,
        *,
        plan: CommandPlan,
        workspace: Path,
        executable: str,
    ) -> CommandReceipt:
        argv = _bubblewrap_argv(
            config=self._config,
            workspace=workspace,
            executable=executable,
            command_argv=plan.argv,
        )
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        stdout_task = asyncio.create_task(_read_bounded(process.stdout, plan.max_output_bytes))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr, plan.max_output_bytes))
        stopped_reason: str | None = None
        try:
            _, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(process.wait(), stdout_task, stderr_task),
                timeout=plan.timeout_seconds,
            )
        except TimeoutError:
            stopped_reason = "command timed out"
            stdout, stderr = await _terminate(process, stdout_task, stderr_task)
        except _OutputLimitExceededError:
            stopped_reason = "command output exceeded its byte cap"
            stdout, stderr = await _terminate(process, stdout_task, stderr_task)
        except asyncio.CancelledError:
            await _terminate(process, stdout_task, stderr_task)
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        if stopped_reason is not None:
            return CommandReceipt(
                status=CommandStatus.STOPPED,
                receipt_ref=_receipt_ref("command-stopped", plan),
                exit_code=process.returncode,
                stdout_tail=_tail(stdout),
                stderr_tail=stopped_reason,
                duration_ms=duration_ms,
            )
        status = CommandStatus.SUCCEEDED if process.returncode == 0 else CommandStatus.FAILED
        return CommandReceipt(
            status=status,
            receipt_ref=_receipt_ref("command", plan),
            exit_code=process.returncode,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            duration_ms=duration_ms,
        )


class _OutputLimitExceededError(RuntimeError):
    pass


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> bytes:
    if stream is None:
        return b""
    output = bytearray()
    while True:
        chunk = await stream.read(8 * 1024)
        if not chunk:
            return bytes(output)
        if len(output) + len(chunk) > limit:
            raise _OutputLimitExceededError()
        output.extend(chunk)


async def _terminate(
    process: asyncio.subprocess.Process,
    stdout_task: asyncio.Task[bytes],
    stderr_task: asyncio.Task[bytes],
) -> tuple[bytes, bytes]:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()
    for task in (stdout_task, stderr_task):
        if not task.done():
            task.cancel()
    results = await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
    stdout = results[0] if isinstance(results[0], bytes) else b""
    stderr = results[1] if isinstance(results[1], bytes) else b""
    return stdout, stderr


def _validate_plan(plan: CommandPlan) -> None:
    if plan.execution_class is not CommandExecutionClass.LOCAL_READ:
        raise ValueError("bubblewrap runner accepts local_read commands only")
    if plan.network_profile is not CommandNetworkProfile.NONE:
        raise ValueError("bubblewrap runner requires the offline network profile")
    if plan.credential_profile is not None:
        raise ValueError("bubblewrap runner does not accept a credential profile")


def _bubblewrap_argv(
    *,
    config: BubblewrapCommandRunnerConfig,
    workspace: Path,
    executable: str,
    command_argv: tuple[str, ...],
) -> tuple[str, ...]:
    argv = [
        config.bubblewrap_executable,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        _SANDBOX_TMP,
        "--dir",
        "/home",
        "--dir",
        "/run",
        "--dir",
        "/workspace",
        "--ro-bind",
        str(workspace),
        "/workspace",
    ]
    for source, target in sorted(config.read_only_mounts.items()):
        argv.extend(("--ro-bind", source, target))
    argv.extend(
        (
            "--chdir",
            "/workspace",
            "--clearenv",
            "--setenv",
            "HOME",
            _SANDBOX_TMP,
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "RUFF_CACHE_DIR",
            _SANDBOX_RUFF_CACHE,
            "--",
            executable,
            *command_argv,
        )
    )
    return tuple(argv)


def _receipt_ref(prefix: str, plan: CommandPlan) -> str:
    payload = f"{plan.command_id}:{plan.command_version}:{plan.idempotency_key}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{plan.command_id}:{digest}"


def _tail(value: bytes) -> str:
    return value[-4_096:].decode("utf-8", errors="replace")


__all__ = [
    "BubblewrapCommandRunner",
    "BubblewrapCommandRunnerConfig",
    "DirectoryWorkspaceResolver",
    "WorkspaceDirectoryResolver",
]
