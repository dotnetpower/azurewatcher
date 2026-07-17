"""Installable deployment administration CLI."""

from __future__ import annotations

from typing import TextIO


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """Load the command parser lazily so delivery adapters can import CLI contracts."""
    from fdai.deployment_cli.cli import main as run

    return run(argv, stdout=stdout)


__all__ = ["main"]
