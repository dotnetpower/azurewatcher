"""Copy-on-write private Git workspaces for coding-agent proposals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fdai.delivery.shell.bubblewrap_runner import DirectoryWorkspaceResolver
from fdai.shared.providers.code_workspace import (
    CodePatchKind,
    CodePatchSet,
    CodeWorkspaceProvider,
    CodeWorkspaceSnapshot,
)

_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,199}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_PROTECTED_PATHS = frozenset(
    {
        ".env",
        ".env.local",
        "resolved-models.json",
        "resolved-models-local.json",
    }
)
_PROTECTED_PREFIXES = (
    ".fdai-",
    ".git/",
    ".venv/",
    "console/dist/",
    "security/integrity/",
)
_MANIFEST = ".git/fdai-workspace.json"


@dataclass(frozen=True, slots=True)
class GitCodeWorkspaceConfig:
    source_repo: Path
    private_root: Path
    git_executable: str = "/usr/bin/git"
    timeout_seconds: float = 60.0
    max_output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.source_repo.is_absolute() or not self.private_root.is_absolute():
            raise ValueError("source_repo and private_root MUST be absolute")
        if not Path(self.git_executable).is_absolute():
            raise ValueError("git_executable MUST be absolute")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")
        if not 1024 <= self.max_output_bytes <= 1_000_000:
            raise ValueError("max_output_bytes MUST be in [1024, 1000000]")


class GitCodeWorkspaceProvider(CodeWorkspaceProvider):
    """Clone a committed revision and materialize patches into derived copies."""

    def __init__(self, config: GitCodeWorkspaceConfig) -> None:
        self._config = config

    async def prepare(self, *, base_revision: str) -> CodeWorkspaceSnapshot:
        if _REVISION.fullmatch(base_revision) is None:
            raise ValueError("base_revision MUST be a bounded revision identifier")
        source = self._config.source_repo.resolve(strict=True)
        commit = (
            await self._git(
                "-C",
                str(source),
                "rev-parse",
                "--verify",
                f"{base_revision}^{{commit}}",
            )
        ).strip()
        if _COMMIT.fullmatch(commit) is None:
            raise RuntimeError("git returned an invalid commit id")
        root = self._private_root()
        digest = hashlib.sha256(f"{source}:{commit}".encode()).hexdigest()
        workspace_ref = f"workspace:sha256:{digest}"
        destination = root / digest
        if destination.is_dir():
            _verify_manifest(destination, expected_commit=commit)
            return CodeWorkspaceSnapshot(workspace_ref=workspace_ref, base_revision=commit)

        staging = root / f".{digest}.{uuid.uuid4().hex}"
        try:
            await self._git(
                "clone",
                "--quiet",
                "--no-hardlinks",
                "--no-checkout",
                "--",
                str(source),
                str(staging),
            )
            await self._git("-C", str(staging), "checkout", "--quiet", "--detach", commit)
            await self._git("-C", str(staging), "remote", "remove", "origin")
            _write_manifest(staging, commit=commit, patch_hash=None)
            os.chmod(staging, 0o700)
            try:
                staging.rename(destination)
            except FileExistsError:
                shutil.rmtree(staging, ignore_errors=True)
                _verify_manifest(destination, expected_commit=commit)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return CodeWorkspaceSnapshot(workspace_ref=workspace_ref, base_revision=commit)

    async def apply(self, patch: CodePatchSet) -> str:
        root = self._private_root()
        resolver = DirectoryWorkspaceResolver(root)
        source = resolver.resolve(patch.workspace_ref)
        manifest = _read_manifest(source)
        if patch.base_revision != manifest.get("commit"):
            raise ValueError("patch base_revision does not match the workspace commit")
        digest = hashlib.sha256(f"{patch.workspace_ref}:{patch.patch_hash}".encode()).hexdigest()
        workspace_ref = f"workspace:sha256:{digest}"
        destination = root / digest
        if destination.is_dir():
            _verify_manifest(
                destination,
                expected_commit=patch.base_revision,
                expected_patch_hash=patch.patch_hash,
            )
            return workspace_ref

        staging = root / f".{digest}.{uuid.uuid4().hex}"
        try:
            shutil.copytree(source, staging, symlinks=True)
            for operation in patch.operations:
                target = _patch_target(staging, operation.path)
                if operation.kind is CodePatchKind.ADD:
                    if target.exists() or target.is_symlink():
                        raise ValueError(f"add target already exists: {operation.path!r}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(operation.content_after or "", encoding="utf-8")
                    continue
                if not target.is_file() or target.is_symlink():
                    raise ValueError(f"patch target is not a regular file: {operation.path!r}")
                actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual_hash != operation.expected_before_sha256:
                    raise ValueError(f"stale before hash for {operation.path!r}")
                if operation.kind is CodePatchKind.DELETE:
                    target.unlink()
                else:
                    target.write_text(operation.content_after or "", encoding="utf-8")
            _write_manifest(
                staging,
                commit=patch.base_revision,
                patch_hash=patch.patch_hash,
            )
            os.chmod(staging, 0o700)
            try:
                staging.rename(destination)
            except FileExistsError:
                shutil.rmtree(staging, ignore_errors=True)
                _verify_manifest(
                    destination,
                    expected_commit=patch.base_revision,
                    expected_patch_hash=patch.patch_hash,
                )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return workspace_ref

    def _private_root(self) -> Path:
        self._config.private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._config.private_root, 0o700)
        return self._config.private_root.resolve(strict=True)

    async def _git(self, *argv: str) -> str:
        process = await asyncio.create_subprocess_exec(
            self._config.git_executable,
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"HOME": "/nonexistent", "LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        stdout_task = asyncio.create_task(
            _read_bounded(process.stdout, self._config.max_output_bytes)
        )
        stderr_task = asyncio.create_task(
            _read_bounded(process.stderr, self._config.max_output_bytes)
        )
        try:
            _, stdout, stderr = await asyncio.wait_for(
                asyncio.gather(process.wait(), stdout_task, stderr_task),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            await _terminate(process, stdout_task, stderr_task)
            raise RuntimeError("git workspace command timed out") from None
        except _GitOutputLimitError:
            await _terminate(process, stdout_task, stderr_task)
            raise RuntimeError("git workspace command exceeded its output cap") from None
        except asyncio.CancelledError:
            await _terminate(process, stdout_task, stderr_task)
            raise
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:500]
            raise RuntimeError(f"git workspace command failed: {detail}")
        return stdout.decode("utf-8", errors="strict")


class _GitOutputLimitError(RuntimeError):
    pass


async def _read_bounded(stream: asyncio.StreamReader | None, limit: int) -> bytes:
    if stream is None:
        return b""
    output = bytearray()
    while True:
        chunk = await stream.read(8 * 1024)
        if not chunk:
            return bytes(output)
        if len(output) + len(chunk) > limit:
            raise _GitOutputLimitError()
        output.extend(chunk)


async def _terminate(
    process: asyncio.subprocess.Process,
    stdout_task: asyncio.Task[bytes],
    stderr_task: asyncio.Task[bytes],
) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()
    for task in (stdout_task, stderr_task):
        if not task.done():
            task.cancel()
    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


def _patch_target(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ValueError("patch path MUST be repository-relative")
    if value in _PROTECTED_PATHS or any(
        value == prefix.rstrip("/") or value.startswith(prefix) for prefix in _PROTECTED_PREFIXES
    ):
        raise ValueError("patch path targets a protected runtime/generated file")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("patch path traverses a symbolic link")
    return root.joinpath(*relative.parts)


def _write_manifest(workspace: Path, *, commit: str, patch_hash: str | None) -> None:
    payload = {"commit": commit, "patch_hash": patch_hash}
    (workspace / _MANIFEST).write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _read_manifest(workspace: Path) -> dict[str, object]:
    try:
        value = json.loads((workspace / _MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("workspace manifest is missing or invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("workspace manifest MUST be an object")
    return value


def _verify_manifest(
    workspace: Path,
    *,
    expected_commit: str,
    expected_patch_hash: str | None = None,
) -> None:
    manifest = _read_manifest(workspace)
    if manifest.get("commit") != expected_commit:
        raise ValueError("workspace commit does not match its content address")
    if expected_patch_hash is not None and manifest.get("patch_hash") != expected_patch_hash:
        raise ValueError("workspace patch does not match its content address")


__all__ = ["GitCodeWorkspaceConfig", "GitCodeWorkspaceProvider"]
