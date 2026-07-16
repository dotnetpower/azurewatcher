"""Bubblewrap command runner isolates local-read typed commands."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fdai.delivery.shell import (
    BubblewrapCommandRunner,
    BubblewrapCommandRunnerConfig,
    DirectoryWorkspaceResolver,
)
from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
    CommandPlan,
    CommandStatus,
)

_BWRAP = Path("/usr/bin/bwrap")


def _workspace(tmp_path: Path) -> tuple[DirectoryWorkspaceResolver, str, Path]:
    root = tmp_path / "workspaces"
    digest = hashlib.sha256(b"workspace").hexdigest()
    workspace = root / digest
    workspace.mkdir(parents=True)
    return DirectoryWorkspaceResolver(root), f"workspace:sha256:{digest}", workspace


def _plan(
    workspace_ref: str,
    *,
    executable_ref: str = "test.command",
    argv: tuple[str, ...] = (),
    timeout_seconds: int = 5,
    max_output_bytes: int = 4096,
    dry_run: bool = False,
) -> CommandPlan:
    return CommandPlan(
        command_id="local.test",
        command_version=1,
        idempotency_key="event-1",
        executable_ref=executable_ref,
        argv=argv,
        execution_class=CommandExecutionClass.LOCAL_READ,
        network_profile=CommandNetworkProfile.NONE,
        output_format=CommandOutputFormat.TEXT,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        dry_run=dry_run,
        workspace_ref=workspace_ref,
    )


@pytest.mark.skipif(not _BWRAP.is_file(), reason="bubblewrap is unavailable")
async def test_runs_read_command_and_keeps_workspace_read_only(tmp_path: Path) -> None:
    resolver, workspace_ref, workspace = _workspace(tmp_path)
    (workspace / "input.txt").write_text("evidence\n", encoding="utf-8")
    runner = BubblewrapCommandRunner(
        workspaces=resolver,
        config=BubblewrapCommandRunnerConfig(
            executable_paths={"test.command": "/usr/bin/python3"},
        ),
    )
    source = (
        "from pathlib import Path; "
        "print(Path('input.txt').read_text().strip()); "
        "Path('blocked.txt').write_text('no')"
    )

    receipt = await runner.execute(_plan(workspace_ref, argv=("-c", source)))

    assert receipt.status is CommandStatus.FAILED
    assert "evidence" in receipt.stdout_tail
    assert not (workspace / "blocked.txt").exists()


@pytest.mark.skipif(not _BWRAP.is_file(), reason="bubblewrap is unavailable")
async def test_enforces_output_cap(tmp_path: Path) -> None:
    resolver, workspace_ref, _ = _workspace(tmp_path)
    runner = BubblewrapCommandRunner(
        workspaces=resolver,
        config=BubblewrapCommandRunnerConfig(
            executable_paths={"test.command": "/usr/bin/python3"},
        ),
    )

    receipt = await runner.execute(
        _plan(workspace_ref, argv=("-c", "print('x' * 10000)"), max_output_bytes=128)
    )

    assert receipt.status is CommandStatus.STOPPED
    assert receipt.stderr_tail == "command output exceeded its byte cap"


async def test_dry_run_starts_no_process(tmp_path: Path) -> None:
    resolver, workspace_ref, _ = _workspace(tmp_path)
    runner = BubblewrapCommandRunner(
        workspaces=resolver,
        config=BubblewrapCommandRunnerConfig(
            executable_paths={"missing": "/definitely/not/executed"},
        ),
    )

    receipt = await runner.execute(_plan(workspace_ref, executable_ref="missing", dry_run=True))

    assert receipt.status is CommandStatus.PLANNED


def test_workspace_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    resolver, workspace_ref, workspace = _workspace(tmp_path)
    workspace.rmdir()
    workspace.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ValueError, match="private workspace"):
        resolver.resolve(workspace_ref)


async def test_rejects_credentialed_plan_before_process_start(tmp_path: Path) -> None:
    resolver, workspace_ref, _ = _workspace(tmp_path)
    runner = BubblewrapCommandRunner(
        workspaces=resolver,
        config=BubblewrapCommandRunnerConfig(executable_paths={}),
    )
    plan = CommandPlan(
        command_id="azure.resource.list",
        command_version=1,
        idempotency_key="event-1",
        executable_ref="azure.cli",
        argv=("resource", "list"),
        execution_class=CommandExecutionClass.CLOUD_READ,
        network_profile=CommandNetworkProfile.AZURE_CONTROL_PLANE,
        output_format=CommandOutputFormat.JSON,
        timeout_seconds=30,
        max_output_bytes=4096,
        dry_run=False,
        credential_profile="azure.reader",
        workspace_ref=workspace_ref,
    )

    with pytest.raises(ValueError, match="local_read commands only"):
        await runner.execute(plan)
