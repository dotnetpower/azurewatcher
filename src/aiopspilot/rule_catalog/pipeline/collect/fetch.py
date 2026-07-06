"""Fetcher Protocol + built-in implementations.

The pipeline uses a fetch adapter picked by :class:`FetchKind`. Three
implementations ship today:

- :class:`LocalDirectoryFetcher` — copies a filesystem tree into the
  snapshot directory. Used by tests and by hand-authored sources that
  live inside this repo.
- :class:`GitCloneFetcher` — ``git clone --depth 1`` at the pinned
  revision, then copies the requested ``subpath`` (or whole tree). Real
  networked adapter used for OSS sources (Gatekeeper library, Checkov,
  tfsec, ...).
- HTTP downloader — deferred; the manifest ``kind=http`` shape lands
  next when the first HTTP source arrives.

Every fetcher returns a :class:`FetchResult` describing the local
directory the pipeline will hash + snapshot.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from aiopspilot.rule_catalog.schema.source_manifest import FetchConfig, FetchKind


class FetchError(RuntimeError):
    """Raised when a fetch cannot complete deterministically."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Local directory + resolved revision returned by a fetcher.

    ``resolved_revision`` is the immutable identifier the pipeline records
    on the snapshot's provenance (git commit sha for git, source path for
    local, expected_sha256 for http).
    """

    tree_root: Path
    resolved_revision: str


@runtime_checkable
class Fetcher(Protocol):
    """One fetch adapter.

    ``fetch`` MUST populate ``dest_root`` with the source tree the caller
    will hash + snapshot. It MAY create subdirectories under ``dest_root``
    but MUST NOT touch anything outside it.
    """

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult: ...


# ---------------------------------------------------------------------------
# Local (fixture / hand-authored) fetcher
# ---------------------------------------------------------------------------


class LocalDirectoryFetcher(Fetcher):
    """Copy a filesystem tree into the snapshot dir.

    Absolute paths are respected; relative paths are resolved against
    the repo root supplied at construction. The whole tree is copied so
    subsequent stages can hash a stable byte sequence.
    """

    def __init__(self, *, repo_root: Path) -> None:
        if not repo_root.is_dir():
            raise ValueError(f"repo_root MUST be a directory; got {repo_root!r}")
        self._repo_root = repo_root

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult:
        if config.kind is not FetchKind.LOCAL:
            raise FetchError(f"LocalDirectoryFetcher does not handle kind={config.kind}")
        if config.path is None:  # pragma: no cover — schema enforces
            raise FetchError("LocalDirectoryFetcher requires fetch.path")

        source = Path(config.path)
        if not source.is_absolute():
            source = (self._repo_root / source).resolve()
        if not source.exists():
            raise FetchError(f"local source not found: {source}")

        dest_root.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            target = dest_root / source.name
            shutil.copy2(source, target)
        else:
            for entry in source.iterdir():
                dest = dest_root / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest)
                else:
                    shutil.copy2(entry, dest)
        return FetchResult(tree_root=dest_root, resolved_revision=str(source))


# ---------------------------------------------------------------------------
# Git clone fetcher
# ---------------------------------------------------------------------------


class GitCloneFetcher(Fetcher):
    """Shallow-clone at a pinned SHA, then copy the requested subtree.

    Uses ``git clone --depth 1 --branch <sha>`` when possible; falls back
    to ``fetch --depth 1 <sha>`` for hosts that reject a branch=sha shape.
    A malformed revision (mutable ref) is rejected earlier by
    ``SourceManifest`` — this class only executes what the manifest
    validated.
    """

    def __init__(self, *, git_binary: str = "git", timeout_seconds: float = 120.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        self._git = git_binary
        self._timeout = timeout_seconds

    def fetch(self, *, config: FetchConfig, dest_root: Path) -> FetchResult:
        if config.kind is not FetchKind.GIT:
            raise FetchError(f"GitCloneFetcher does not handle kind={config.kind}")
        if config.repo is None or config.revision is None:  # pragma: no cover — schema enforces
            raise FetchError("GitCloneFetcher requires fetch.repo + fetch.revision")

        dest_root.mkdir(parents=True, exist_ok=True)
        checkout_dir = dest_root / "_clone"

        try:
            self._run([self._git, "init", "--quiet"], cwd=checkout_dir, mkdir=True)
            self._run([self._git, "remote", "add", "origin", config.repo], cwd=checkout_dir)
            self._run(
                [
                    self._git,
                    "fetch",
                    "--depth",
                    "1",
                    "--no-tags",
                    "--filter=blob:none",
                    "origin",
                    config.revision,
                ],
                cwd=checkout_dir,
            )
            self._run([self._git, "checkout", "--quiet", "FETCH_HEAD"], cwd=checkout_dir)
        except FetchError:
            raise
        except subprocess.SubprocessError as exc:
            raise FetchError(f"git operation failed: {exc}") from exc

        source_tree = checkout_dir if config.subpath is None else checkout_dir / config.subpath
        if not source_tree.exists():
            raise FetchError(f"subpath {config.subpath!r} does not exist in cloned tree")

        # Copy the subtree next to the clone dir so hash + snapshot don't
        # include the .git metadata.
        target_root = dest_root / "tree"
        target_root.mkdir(parents=True, exist_ok=True)
        if source_tree.is_file():
            shutil.copy2(source_tree, target_root / source_tree.name)
        else:
            for entry in source_tree.iterdir():
                if entry.name == ".git":
                    continue
                dest = target_root / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest)
                else:
                    shutil.copy2(entry, dest)

        # Drop the clone dir now that we have the clean tree.
        shutil.rmtree(checkout_dir, ignore_errors=True)
        return FetchResult(tree_root=target_root, resolved_revision=config.revision)

    def _run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        mkdir: bool = False,
    ) -> None:
        if mkdir:
            cwd.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(  # noqa: S603 — argv is a list, not shell.
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise FetchError(
                f"{' '.join(argv)} failed with exit={proc.returncode}:\n{proc.stderr.strip()}"
            )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def build_fetcher(kind: FetchKind, *, repo_root: Path) -> Fetcher:
    """Return the default fetcher for a manifest kind.

    Composition-root helper. Forks can replace individual fetchers by
    swapping the dispatch in their own composition root.
    """
    if kind is FetchKind.LOCAL:
        return LocalDirectoryFetcher(repo_root=repo_root)
    if kind is FetchKind.GIT:
        return GitCloneFetcher()
    raise FetchError(f"no default fetcher registered for kind={kind}")


__all__ = [
    "FetchError",
    "FetchResult",
    "Fetcher",
    "GitCloneFetcher",
    "LocalDirectoryFetcher",
    "build_fetcher",
]
