"""Git workspace provider never edits the source checkout."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from fdai.delivery.shell import GitCodeWorkspaceConfig, GitCodeWorkspaceProvider
from fdai.delivery.shell.bubblewrap_runner import DirectoryWorkspaceResolver
from fdai.shared.providers.code_workspace import (
    CodePatchKind,
    CodePatchOperation,
    CodePatchSet,
)


def _git(repo: Path, *argv: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed test executable and argv
        ("/usr/bin/git", "-C", str(repo), *argv),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "user@example.com")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "--quiet", "-m", "initial")
    return repo


def _provider(repo: Path, root: Path) -> GitCodeWorkspaceProvider:
    return GitCodeWorkspaceProvider(
        GitCodeWorkspaceConfig(source_repo=repo.resolve(), private_root=root.resolve())
    )


async def test_prepare_clones_committed_revision_not_source_wip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("VALUE = 99\n", encoding="utf-8")
    root = tmp_path / "private"
    provider = _provider(repo, root)

    snapshot = await provider.prepare(base_revision="HEAD")
    workspace = DirectoryWorkspaceResolver(root).resolve(snapshot.workspace_ref)

    assert (workspace / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 99\n"
    assert _git(workspace, "remote") == ""
    assert snapshot.base_revision == _git(repo, "rev-parse", "HEAD")


async def test_apply_materializes_derived_workspace_and_preserves_base(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    root = tmp_path / "private"
    provider = _provider(repo, root)
    snapshot = await provider.prepare(base_revision="HEAD")
    base = DirectoryWorkspaceResolver(root).resolve(snapshot.workspace_ref)
    before = hashlib.sha256((base / "app.py").read_bytes()).hexdigest()
    patch = CodePatchSet(
        workspace_ref=snapshot.workspace_ref,
        base_revision=snapshot.base_revision,
        operations=(
            CodePatchOperation(
                kind=CodePatchKind.UPDATE,
                path="app.py",
                expected_before_sha256=before,
                content_after="VALUE = 2\n",
            ),
        ),
    )

    derived_ref = await provider.apply(patch)
    repeated_ref = await provider.apply(patch)
    derived = DirectoryWorkspaceResolver(root).resolve(derived_ref)

    assert repeated_ref == derived_ref
    assert (base / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (derived / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


async def test_apply_rejects_stale_hash_without_touching_base(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    root = tmp_path / "private"
    provider = _provider(repo, root)
    snapshot = await provider.prepare(base_revision="HEAD")
    patch = CodePatchSet(
        workspace_ref=snapshot.workspace_ref,
        base_revision=snapshot.base_revision,
        operations=(
            CodePatchOperation(
                kind=CodePatchKind.UPDATE,
                path="app.py",
                expected_before_sha256="0" * 64,
                content_after="VALUE = 2\n",
            ),
        ),
    )

    with pytest.raises(ValueError, match="stale before hash"):
        await provider.apply(patch)

    base = DirectoryWorkspaceResolver(root).resolve(snapshot.workspace_ref)
    assert (base / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


async def test_provider_rechecks_traversal_at_apply_boundary(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    root = tmp_path / "private"
    provider = _provider(repo, root)
    snapshot = await provider.prepare(base_revision="HEAD")
    patch = CodePatchSet(
        workspace_ref=snapshot.workspace_ref,
        base_revision=snapshot.base_revision,
        operations=(
            CodePatchOperation(
                kind=CodePatchKind.ADD,
                path="../escape.py",
                content_after="print('no')\n",
            ),
        ),
    )

    with pytest.raises(ValueError, match="repository-relative"):
        await provider.apply(patch)
    assert not (root / "escape.py").exists()
