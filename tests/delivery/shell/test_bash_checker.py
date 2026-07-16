"""Bash syntax checks parse shell artifacts without running commands."""

from pathlib import Path

import pytest

from fdai.delivery.shell import BashSyntaxChecker, BashSyntaxCheckerConfig
from fdai.shared.providers.shell_task import ShellTaskFile, ShellTaskSpec

_BASH = Path("/usr/bin/bash")


def _task(source: str) -> ShellTaskSpec:
    return ShellTaskSpec(
        task_id="repo.verify",
        version="1.0.0",
        entrypoint="run.sh",
        files=(ShellTaskFile(path="run.sh", content=source),),
    )


@pytest.mark.skipif(not _BASH.is_file(), reason="bash is unavailable")
async def test_accepts_valid_script_without_executing_commands(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    task = _task(
        f"#!/bin/bash\nset -euo pipefail\nprintf unsafe > {marker}\nif true; then printf ok; fi\n"
    )

    report = await BashSyntaxChecker().check(task)

    assert report.valid
    assert report.checker_id == "bash.noexec.v1"
    assert not marker.exists()


@pytest.mark.skipif(not _BASH.is_file(), reason="bash is unavailable")
async def test_reports_invalid_bash_syntax() -> None:
    task = _task("#!/bin/bash\nset -euo pipefail\nif true; then\n")

    report = await BashSyntaxChecker().check(task)

    assert not report.valid
    assert report.issues[0].path == "run.sh"
    assert "syntax error" in report.issues[0].message


def test_config_requires_absolute_bash_path() -> None:
    with pytest.raises(ValueError, match="absolute path to bash"):
        BashSyntaxCheckerConfig(executable="bash")
