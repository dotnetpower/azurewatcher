"""Scheduler tick entry point - upstream-safe (P2-6)."""

from __future__ import annotations

import fdai.delivery.scheduler_tick_cli as tick_cli


def test_no_dsn_returns_zero(monkeypatch) -> None:
    monkeypatch.delenv("FDAI_SCHEDULE_STORE_DSN", raising=False)
    assert tick_cli.main() == 0


def test_blank_dsn_returns_zero(monkeypatch) -> None:
    monkeypatch.setenv("FDAI_SCHEDULE_STORE_DSN", "   ")
    assert tick_cli.main() == 0
