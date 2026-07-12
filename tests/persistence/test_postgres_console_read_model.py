"""Integration test - PostgresConsoleReadModel against a live DB.

Skipped unless ``FDAI_DATABASE_URL`` is set (mirrors
``test_postgres_state_store.py``). The docker-compose dev stack
(``make dev-up``) exposes the URL as
``postgresql+psycopg://fdai:devonly@localhost:5432/fdai``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.read_api.postgres_read_model import (
    PostgresConsoleReadModel,
    PostgresConsoleReadModelConfig,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


async def _seed_audit(store: PostgresStateStore, *, count: int, kind: str) -> list[str]:
    event_ids: list[str] = []
    for i in range(count):
        eid = str(uuid.uuid4())
        event_ids.append(eid)
        await store.append_audit_entry(
            {
                "event_id": eid,
                "actor": "integration-test",
                "action_kind": kind,
                "mode": "shadow" if i % 2 == 0 else "enforce",
                "outcome": "auto",
                "tier": "T0",
            }
        )
    return event_ids


@pytest.mark.asyncio
async def test_list_audit_returns_page_and_next_cursor() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    writer = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    reader = PostgresConsoleReadModel(config=PostgresConsoleReadModelConfig(dsn=dsn))
    kind = f"read-model-integration-{uuid.uuid4()}"
    await _seed_audit(writer, count=3, kind=kind)
    page = await reader.list_audit(limit=2)
    # Newest first: only the ones we seeded with our unique kind may or
    # may not lead the page (other integration tests may share the DB),
    # so we verify against the shape only.
    assert len(page.items) == 2
    # Cursor is present when a next page exists.
    assert page.next_cursor is not None
    # Follow the cursor - the next page starts strictly before the last
    # seq on the previous page.
    page2 = await reader.list_audit(limit=2, cursor=page.next_cursor)
    assert all(item.seq < page.items[-1].seq for item in page2.items)


@pytest.mark.asyncio
async def test_dashboard_metrics_reflects_seeded_rows() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    writer = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    reader = PostgresConsoleReadModel(config=PostgresConsoleReadModelConfig(dsn=dsn))
    kind = f"kpi-integration-{uuid.uuid4()}"
    await _seed_audit(writer, count=4, kind=kind)
    kpi = await reader.dashboard_metrics()
    assert kpi.event_count >= 4
    # Our seeded kind must appear in the aggregated counts.
    assert kpi.by_action_kind.get(kind, 0) >= 4
    assert kpi.shadow_share + kpi.enforce_share <= 1.0


@pytest.mark.asyncio
async def test_list_hil_queue_projects_pending_park_records() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    writer = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    reader = PostgresConsoleReadModel(config=PostgresConsoleReadModelConfig(dsn=dsn))
    # Seed one pending park + one resolved park; only the pending one appears.
    aid_pending = f"integration-pending-{uuid.uuid4()}"
    aid_resolved = f"integration-resolved-{uuid.uuid4()}"
    idem = f"idem-{uuid.uuid4()}"
    event_id = str(uuid.uuid4())
    parked_at = datetime.now(tz=UTC).isoformat()
    await writer.write_state(
        f"hil_park:{aid_pending}",
        {
            "status": "pending",
            "approval_id": aid_pending,
            "action": {
                "idempotency_key": idem,
                "event_id": event_id,
                "action_type": "integration.test_action",
            },
            "rule_id": "integration.rule",
            "action_type": "integration.test_action",
            "submitter_oid": "user-integration",
            "assignee_oid": None,
            "correlation_id": "corr-integration",
            "idempotency_key": idem,
            "parked_at": parked_at,
            "on_call": None,
        },
    )
    await writer.write_state(
        f"hil_park:{aid_resolved}",
        {
            "status": "resolved",
            "approval_id": aid_resolved,
            "action": {"idempotency_key": "resolved-idem", "event_id": str(uuid.uuid4())},
            "parked_at": parked_at,
        },
    )
    page = await reader.list_hil_queue(limit=100)
    matching = [item for item in page.items if item.idempotency_key == idem]
    assert len(matching) == 1
    only = matching[0]
    assert only.event_id == event_id
    assert only.action_kind == "integration.test_action"
    assert only.correlation_id == "corr-integration"
    # And a pending count is reflected in the KPI HIL pending gauge.
    kpi = await reader.dashboard_metrics()
    assert kpi.hil_pending >= 1
    _ = json  # keep import for lints; JSON round-trip is exercised in units
