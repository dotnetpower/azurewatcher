#!/usr/bin/env python3
"""Ratchet oversized roadmap documents toward focused owner documents."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NEW_DOC_MAX_LINES = 400
LEGACY_GROWTH_FLOOR = 650


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _base_ref(diff_range: str | None) -> str:
    if diff_range:
        return diff_range.split("...", 1)[0].split("..", 1)[0]
    return "HEAD"


def _changed_docs(diff_range: str | None) -> tuple[str, ...]:
    args = ("diff", "--name-only", "--diff-filter=ACMRT", diff_range or "HEAD")
    paths = _run_git(*args).stdout.splitlines()
    if diff_range is None:
        paths.extend(_run_git("ls-files", "--others", "--exclude-standard").stdout.splitlines())
    return tuple(
        sorted(path for path in paths if path.startswith("docs/roadmap/") and path.endswith(".md"))
    )


def _old_line_count(base_ref: str, relative: str) -> int | None:
    result = _run_git("show", f"{base_ref}:{relative}", check=False)
    if result.returncode != 0:
        return None
    return len(result.stdout.splitlines())


def size_violations(documents: tuple[tuple[str, int, int | None], ...]) -> list[str]:
    errors: list[str] = []
    for path, current_lines, old_lines in documents:
        if old_lines is None and current_lines > NEW_DOC_MAX_LINES:
            errors.append(
                f"{path}: new document has {current_lines} lines; maximum is {NEW_DOC_MAX_LINES}"
            )
        elif (
            old_lines is not None
            and current_lines > LEGACY_GROWTH_FLOOR
            and current_lines > old_lines
        ):
            errors.append(
                f"{path}: legacy oversized document grew {old_lines} -> {current_lines}; "
                "split it into focused owner documents"
            )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print("usage: check-document-size.py [<git-diff-range>]", file=sys.stderr)
        return 2
    diff_range = argv[1] if len(argv) == 2 else None
    base_ref = _base_ref(diff_range)
    documents = []
    for relative in _changed_docs(diff_range):
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        documents.append(
            (
                relative,
                len(path.read_text(encoding="utf-8").splitlines()),
                _old_line_count(base_ref, relative),
            )
        )
    errors = size_violations(tuple(documents))
    if errors:
        for error in errors:
            print(f"document-size: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"document-size: OK ({len(documents)} changed roadmap document(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
