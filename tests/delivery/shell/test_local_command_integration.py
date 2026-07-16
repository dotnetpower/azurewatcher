"""Private workspace, typed catalog, and bubblewrap runner integration."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from fdai.core.tools.default_commands import default_command_catalog
from fdai.delivery.shell import (
    BubblewrapCommandRunner,
    BubblewrapCommandRunnerConfig,
    DirectoryWorkspaceResolver,
    GitCodeWorkspaceConfig,
    GitCodeWorkspaceProvider,
)
from fdai.shared.providers.code_workspace import (
    CodePatchKind,
    CodePatchOperation,
    CodePatchSet,
)
from fdai.shared.providers.command_runner import CommandStatus

_BWRAP = Path("/usr/bin/bwrap")


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed test executable and argv
        ("/usr/bin/git", "-C", str(repo), *argv),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    path = repo / "src" / "fdai" / "example.py"
    path.parent.mkdir(parents=True)
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "user@example.com")
    path.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "src/fdai/example.py")
    _git(repo, "commit", "--quiet", "-m", "initial")
    return repo


@pytest.mark.skipif(not _BWRAP.is_file(), reason="bubblewrap is unavailable")
async def test_private_patch_is_visible_to_typed_git_diff(tmp_path: Path) -> None:
    source = _source_repo(tmp_path)
    private_root = tmp_path / "private"
    workspaces = GitCodeWorkspaceProvider(
        GitCodeWorkspaceConfig(
            source_repo=source.resolve(),
            private_root=private_root.resolve(),
        )
    )
    resolver = DirectoryWorkspaceResolver(private_root)
    runner = BubblewrapCommandRunner(
        workspaces=resolver,
        config=BubblewrapCommandRunnerConfig(
            executable_paths={"git.cli": "/usr/bin/git"},
        ),
    )
    catalog = default_command_catalog()
    snapshot = await workspaces.prepare(base_revision="HEAD")

    status_plan = catalog.resolve(
        command_id="local.git.status",
        arguments={},
        trusted_values={},
        idempotency_key="status-1",
        dry_run=False,
        workspace_ref=snapshot.workspace_ref,
    )
    status_receipt = await runner.execute(status_plan)
    assert status_receipt.status is CommandStatus.SUCCEEDED
    assert status_receipt.stdout_tail == ""

    base = resolver.resolve(snapshot.workspace_ref)
    target = base / "src" / "fdai" / "example.py"
    patch = CodePatchSet(
        workspace_ref=snapshot.workspace_ref,
        base_revision=snapshot.base_revision,
        operations=(
            CodePatchOperation(
                kind=CodePatchKind.UPDATE,
                path="src/fdai/example.py",
                expected_before_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                content_after="VALUE = 2\n",
            ),
        ),
    )
    derived_ref = await workspaces.apply(patch)
    diff_plan = catalog.resolve(
        command_id="local.git.diff",
        arguments={"path": "src/fdai/example.py"},
        trusted_values={},
        idempotency_key="diff-1",
        dry_run=False,
        workspace_ref=derived_ref,
    )

    diff_receipt = await runner.execute(diff_plan)

    assert diff_receipt.status is CommandStatus.SUCCEEDED
    assert "-VALUE = 1" in diff_receipt.stdout_tail
    assert "+VALUE = 2" in diff_receipt.stdout_tail
    assert (source / "src" / "fdai" / "example.py").read_text() == "VALUE = 1\n"
