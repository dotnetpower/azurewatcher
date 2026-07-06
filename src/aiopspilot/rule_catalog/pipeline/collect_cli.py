"""CLI entrypoint for the rule-catalog collector pipeline.

Usage
-----

    python -m aiopspilot.rule_catalog.pipeline.collect_cli \\
        --manifest rule-catalog/sources/gatekeeper-library/manifest.yaml \\
        [--dry-run]

Exits:

- ``0`` — snapshot written (or dry-run summary printed).
- ``2`` — manifest / fetch / hash-mismatch error.
- ``64`` — usage error.

The snapshot lands under
``rule-catalog/sources/<id>/<short-revision>/`` next to a
``SNAPSHOT.json`` provenance file. The T0 catalog is NOT touched — a
future normalization stage promotes snapshots into
``rule-catalog/catalog/`` under the same governance pipeline as the
existing hand-authored rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from aiopspilot.rule_catalog.pipeline.collect import CollectorPipeline
from aiopspilot.rule_catalog.pipeline.collect.fetch import FetchError
from aiopspilot.rule_catalog.schema.source_manifest import ManifestError


def _repo_root() -> Path:
    # Walks up from this file until a ``rule-catalog/`` sibling appears —
    # matches the resolution used by the process entrypoint.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "rule-catalog").is_dir():
            return parent
    return Path.cwd()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiopspilot-rule-collect",
        description=(
            "Fetch a rule-catalog source at its pinned revision, hash the "
            "resulting tree, and write a snapshot under "
            "rule-catalog/sources/<id>/<revision>/. Parser + normalization "
            "stages ship in follow-up phases; this CLI only guarantees a "
            "deterministic, provenance-stamped snapshot."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the source manifest YAML.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + hash but skip writing snapshot bytes.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override repo root (defaults to the auto-detected one).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Override snapshot output root (defaults to <repo>/rule-catalog/sources).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root or _repo_root()

    try:
        pipeline = CollectorPipeline(
            repo_root=repo_root,
            output_root=args.output_root,
        )
        report = pipeline.collect_from_manifest_path(args.manifest, dry_run=args.dry_run)
    except (ManifestError, FetchError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "source_id": report.source_id,
        "resolved_revision": report.resolved_revision,
        "content_sha256": report.content_sha256,
        "file_count": report.file_count,
        "parser": report.parser,
        "license": report.license,
        "snapshot_dir": str(report.snapshot_dir),
        "mismatch": report.mismatch,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if report.mismatch:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover — process entrypoint
    raise SystemExit(main())


__all__ = ["main"]
