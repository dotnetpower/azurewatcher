"""CollectorPipeline + LocalDirectoryFetcher + CLI — offline tests.

Git-clone fetcher tests are deferred (require network) — the seam is
tested through fixture manifests + LocalDirectoryFetcher, which
exercises every non-git path (hash, snapshot, dry-run, mismatch).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from aiopspilot.rule_catalog.pipeline.collect import (
    CollectorPipeline,
    LocalDirectoryFetcher,
)
from aiopspilot.rule_catalog.pipeline.collect.collector import (
    _count_files,
    _hash_tree,
    _short_revision,
)
from aiopspilot.rule_catalog.pipeline.collect.fetch import (
    FetchError,
    GitCloneFetcher,
    build_fetcher,
)
from aiopspilot.rule_catalog.pipeline.collect_cli import main as cli_main
from aiopspilot.rule_catalog.schema.source_manifest import (
    FetchConfig,
    FetchKind,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _write_source_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy.rego").write_text("package foo\ndeny = false\n", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "policy.yaml").write_text("id: sample\nseverity: low\n", encoding="utf-8")


def _write_manifest(path: Path, source_path: str, *, source_id: str = "smoke-src") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": source_id,
                "name": "Smoke",
                "license": "Apache-2.0",
                "redistribution": "embeddable",
                "fetch": {"kind": "local", "path": source_path},
                "parser": "rule-yaml",
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# LocalDirectoryFetcher
# ---------------------------------------------------------------------------


def test_local_fetcher_copies_tree(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _write_source_tree(source)
    dest = tmp_path / "dest"
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    result = fetcher.fetch(
        config=FetchConfig(kind=FetchKind.LOCAL, path=str(source)),
        dest_root=dest,
    )
    assert result.tree_root == dest
    assert (dest / "policy.rego").exists()
    assert (dest / "sub" / "policy.yaml").exists()


def test_local_fetcher_resolves_relative_path(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    dest = tmp_path / "dest"
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    result = fetcher.fetch(
        config=FetchConfig(kind=FetchKind.LOCAL, path="seed"),
        dest_root=dest,
    )
    assert (dest / "policy.rego").exists()
    assert result.resolved_revision.endswith("/seed")


def test_local_fetcher_raises_on_missing(tmp_path: Path) -> None:
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    with pytest.raises(FetchError, match="not found"):
        fetcher.fetch(
            config=FetchConfig(kind=FetchKind.LOCAL, path=str(tmp_path / "nope")),
            dest_root=tmp_path / "dest",
        )


def test_local_fetcher_rejects_git_kind(tmp_path: Path) -> None:
    fetcher = LocalDirectoryFetcher(repo_root=tmp_path)
    with pytest.raises(FetchError, match="does not handle"):
        fetcher.fetch(
            config=FetchConfig(
                kind=FetchKind.GIT,
                repo="https://x/y",
                revision="0" * 40,
            ),
            dest_root=tmp_path,
        )


def test_build_fetcher_dispatch(tmp_path: Path) -> None:
    assert isinstance(build_fetcher(FetchKind.LOCAL, repo_root=tmp_path), LocalDirectoryFetcher)
    assert isinstance(build_fetcher(FetchKind.GIT, repo_root=tmp_path), GitCloneFetcher)
    with pytest.raises(FetchError):
        build_fetcher(FetchKind.HTTP, repo_root=tmp_path)


def test_git_fetcher_construction_guards() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        GitCloneFetcher(timeout_seconds=0)


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def test_hash_tree_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "s"
    _write_source_tree(src)
    h1 = _hash_tree(src)
    h2 = _hash_tree(src)
    assert h1 == h2
    assert len(h1) == 64


def test_hash_tree_changes_when_content_changes(tmp_path: Path) -> None:
    src = tmp_path / "s"
    _write_source_tree(src)
    h1 = _hash_tree(src)
    (src / "extra.txt").write_text("delta\n", encoding="utf-8")
    h2 = _hash_tree(src)
    assert h1 != h2


def test_short_revision_alnum_is_truncated() -> None:
    assert _short_revision("abcdef0123456789") == "abcdef012345"
    assert _short_revision("abc123") == "abc123"


def test_short_revision_non_alnum_is_hashed() -> None:
    a = _short_revision("/some/path/with/slashes")
    b = _short_revision("/some/path/with/slashes")
    assert a == b
    assert len(a) == 12


def test_count_files(tmp_path: Path) -> None:
    src = tmp_path / "s"
    _write_source_tree(src)
    assert _count_files(src) == 2


# ---------------------------------------------------------------------------
# CollectorPipeline
# ---------------------------------------------------------------------------


def test_collector_writes_snapshot_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))

    pipeline = CollectorPipeline(
        repo_root=tmp_path,
        output_root=tmp_path / "snapshots",
    )
    report = pipeline.collect_from_manifest_path(manifest_path)

    assert report.source_id == "smoke-src"
    assert report.file_count == 2
    assert report.snapshot_dir.exists()
    tree_dir = report.snapshot_dir / "tree"
    assert (tree_dir / "policy.rego").exists()
    assert (tree_dir / "sub" / "policy.yaml").exists()

    provenance = json.loads((report.snapshot_dir / "SNAPSHOT.json").read_text())
    assert provenance["source_id"] == "smoke-src"
    assert provenance["content_sha256"] == report.content_sha256
    assert provenance["parser"] == "rule-yaml"


def test_collector_dry_run_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))
    out = tmp_path / "snapshots"

    pipeline = CollectorPipeline(repo_root=tmp_path, output_root=out)
    report = pipeline.collect_from_manifest_path(manifest_path, dry_run=True)
    assert report.file_count == 2
    assert not out.exists()


def test_collector_replaces_existing_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))
    out = tmp_path / "snapshots"

    pipeline = CollectorPipeline(repo_root=tmp_path, output_root=out)
    first = pipeline.collect_from_manifest_path(manifest_path)
    # A stale file left in the snapshot dir MUST be cleared on the second run.
    (first.snapshot_dir / "stale.txt").write_text("stale\n", encoding="utf-8")
    second = pipeline.collect_from_manifest_path(manifest_path)
    assert not (second.snapshot_dir / "stale.txt").exists()
    assert first.content_sha256 == second.content_sha256


def test_collector_repo_root_must_be_directory(tmp_path: Path) -> None:
    bogus = tmp_path / "missing"
    with pytest.raises(ValueError, match="directory"):
        CollectorPipeline(repo_root=bogus)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_runs_dry_run_against_local_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "seed"
    _write_source_tree(source)
    manifest_path = tmp_path / "manifest.yaml"
    _write_manifest(manifest_path, str(source))
    out = tmp_path / "snapshots"

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(out),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["source_id"] == "smoke-src"
    assert payload["dry_run"] is True


def test_cli_fails_on_bad_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not a mapping\n", encoding="utf-8")
    exit_code = cli_main(
        [
            "--manifest",
            str(bad),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "out"),
        ]
    )
    assert exit_code == 2
    assert "error" in capsys.readouterr().err
