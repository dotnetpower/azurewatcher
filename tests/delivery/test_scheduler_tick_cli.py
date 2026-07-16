"""Scheduler tick entry point - upstream-safe (P2-6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import fdai.delivery.scheduler_tick_cli as tick_cli
from fdai.delivery.persistence.postgres_user_context_projection_recovery import (
    ProjectionUpsertJob,
)
from fdai.delivery.persistence.postgres_user_context_retention import ProjectionDeleteJob


def test_no_dsn_returns_zero(monkeypatch) -> None:
    monkeypatch.delenv("FDAI_SCHEDULE_STORE_DSN", raising=False)
    assert tick_cli.main() == 0


def test_blank_dsn_returns_zero(monkeypatch) -> None:
    monkeypatch.setenv("FDAI_SCHEDULE_STORE_DSN", "   ")
    assert tick_cli.main() == 0


async def test_projection_delete_failures_are_retried_without_blocking() -> None:
    now = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)
    retention = AsyncMock()
    retention.claim_deletions.return_value = (
        ProjectionDeleteJob("object-ok-1", 0),
        ProjectionDeleteJob("object-failed", 2),
        ProjectionDeleteJob("object-ok-2", 0),
    )
    ontology = AsyncMock()
    ontology.delete_object.side_effect = (None, RuntimeError("temporary"), None)

    completed = await tick_cli._drain_projection_deletes(
        retention=retention,
        ontology=ontology,
        now=now,
    )

    assert completed == 2
    assert retention.complete_deletion.await_count == 2
    retention.retry_deletion.assert_awaited_once_with(
        "object-failed",
        available_at=now + timedelta(minutes=4),
        error="RuntimeError:temporary",
    )


def test_projection_retry_delay_is_bounded() -> None:
    assert tick_cli._projection_retry_delay(ProjectionDeleteJob("first", 0)) == timedelta(minutes=1)
    assert tick_cli._projection_retry_delay(ProjectionDeleteJob("later", 100)) == timedelta(hours=1)


async def test_projection_upserts_complete_and_dead_letter_poison_jobs() -> None:
    now = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)
    recovery = AsyncMock()
    successful = ProjectionUpsertJob("preference", "user-1", "user-1", 0)
    poison = ProjectionUpsertJob("policy", "user-1", "policy-1", 4)
    recovery.claim.return_value = (successful, poison)
    recovery.project.side_effect = (True, RuntimeError("invalid projection"))

    completed = await tick_cli._drain_projection_upserts(recovery=recovery, now=now)

    assert completed == 1
    recovery.complete.assert_awaited_once_with(successful)
    recovery.dead_letter.assert_awaited_once_with(
        poison,
        error="RuntimeError:invalid projection",
    )
    recovery.retry.assert_not_awaited()
