"""Bounded Bash no-exec syntax checker for inert shell artifacts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from fdai.shared.providers.shell_checker import (
    ShellCheckIssue,
    ShellCheckReport,
    ShellTaskChecker,
)
from fdai.shared.providers.shell_task import ShellTaskSpec


@dataclass(frozen=True, slots=True)
class BashSyntaxCheckerConfig:
    executable: str = "/usr/bin/bash"
    timeout_seconds: float = 5.0
    max_stderr_bytes: int = 16 * 1024

    def __post_init__(self) -> None:
        path = Path(self.executable)
        if not path.is_absolute() or path.name != "bash":
            raise ValueError("executable MUST be an absolute path to bash")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")
        if not 128 <= self.max_stderr_bytes <= 64 * 1024:
            raise ValueError("max_stderr_bytes MUST be in [128, 65536]")


class BashSyntaxChecker(ShellTaskChecker):
    """Run pinned Bash with noexec against each shell file over stdin."""

    def __init__(self, config: BashSyntaxCheckerConfig | None = None) -> None:
        self._config = config or BashSyntaxCheckerConfig()

    async def check(self, task: ShellTaskSpec) -> ShellCheckReport:
        issues: list[ShellCheckIssue] = []
        for item in sorted(task.files, key=lambda value: value.path):
            if not item.path.endswith(".sh"):
                continue
            issue = await self._check_file(item.path, item.content)
            if issue is not None:
                issues.append(issue)
        return ShellCheckReport(
            artifact_hash=task.artifact_hash,
            checker_id="bash.noexec.v1",
            issues=tuple(issues),
        )

    async def _check_file(self, path: str, content: str) -> ShellCheckIssue | None:
        env = {
            "HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        }
        try:
            process = await asyncio.create_subprocess_exec(
                self._config.executable,
                "--noprofile",
                "--norc",
                "-n",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return ShellCheckIssue(
                path=path,
                message=f"bash checker unavailable: {type(exc).__name__}",
            )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(content.encode("utf-8")),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return ShellCheckIssue(path=path, message="bash syntax check timed out")
        if process.returncode == 0:
            return None
        bounded = stderr[: self._config.max_stderr_bytes].decode("utf-8", errors="replace")
        message = _sanitize_error(bounded)
        return ShellCheckIssue(path=path, message=message or "bash syntax check failed")


def _sanitize_error(value: str) -> str:
    normalized = value.replace("/dev/stdin", "<shell-task>").replace("bash: ", "")
    return " ".join(normalized.split())[:500]


__all__ = ["BashSyntaxChecker", "BashSyntaxCheckerConfig"]
