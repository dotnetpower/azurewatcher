#!/usr/bin/env python3
"""Reject fork-mode detection from runtime, deployment, and committed config paths."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOTS = (
    REPO_ROOT / "src",
    REPO_ROOT / "config",
    REPO_ROOT / "infra",
)
TOKENS = ("FDAI_FORK", ".fdai-fork", "fdai.fork")
TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".tf",
    ".sh",
    ".md",
    ".txt",
}


def violations() -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if any(token in line for token in TOKENS):
                    found.append((path.relative_to(REPO_ROOT), line_number, line.strip()))
    return found


def main() -> int:
    found = violations()
    if found:
        print(
            "fork-runtime-independence: ERROR: fork markers are repository-integrity signals "
            "and MUST NOT control runtime behavior",
            file=sys.stderr,
        )
        for path, line_number, line in found:
            print(f"  {path}:{line_number}: {line}", file=sys.stderr)
        return 1
    print("fork-runtime-independence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
