"""CLI contract tests for the repository verification facade."""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY = _ROOT / "scripts" / "verify.sh"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository script with test-controlled arguments
        [str(_VERIFY), *arguments],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_full_requires_a_focused_pytest_path() -> None:
    result = _run("--full")

    assert result.returncode == 2
    assert "--full requires a pytest path" in result.stderr
    assert "--all" in result.stderr


def test_help_distinguishes_focused_and_whole_suite_modes() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert "--full <path>" in result.stdout
    assert "--all" in result.stdout
