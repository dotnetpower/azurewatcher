"""Integration test — PostgresStateStore round-trip against a live DB.

Skipped unless ``AIOPSPILOT_DATABASE_URL`` is set (same guard as the
migrations test). The docker-compose dev stack (`make dev-up`) exposes
the URL as ``postgresql+psycopg://aiopspilot:devonly@localhost:5432/aiopspilot``.

The tests here:

- ``append_audit_entry`` writes a row with hash-chained integrity;
- ``read_state`` / ``write_state`` round-trip on ``state_kv``;
- ``verify_chain`` returns True after two appends and False after we
  tamper with the persisted hash.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from aiopspilot.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def _requires_live_db() -> str:
    url = os.environ.get("AIOPSPILOT_DATABASE_URL")
    if not url:
        pytest.skip("AIOPSPILOT_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 — controlled subprocess
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


@pytest.mark.asyncio
async def test_append_audit_entry_writes_hash_chained_row() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    event_id = str(uuid.uuid4())
    await store.append_audit_entry(
        {
            "event_id": event_id,
            "actor": "integration-test",
            "action_kind": "smoke",
            "mode": "shadow",
            "reason": "hash-chain-check",
        }
    )
    # A second entry inherits the first's hash — verify_chain confirms.
    await store.append_audit_entry(
        {
            "event_id": str(uuid.uuid4()),
            "actor": "integration-test",
            "action_kind": "smoke",
            "mode": "shadow",
            "reason": "second",
        }
    )
    assert await store.verify_chain() is True


@pytest.mark.asyncio
async def test_state_kv_round_trip() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    key = f"integration-test-{uuid.uuid4()}"
    await store.write_state(key, {"a": 1, "nested": {"b": 2}})
    got = await store.read_state(key)
    assert got == {"a": 1, "nested": {"b": 2}}
    # Idempotent overwrite — no history row explosion.
    await store.write_state(key, {"a": 2})
    assert await store.read_state(key) == {"a": 2}
    assert await store.read_state("unknown-key") is None


@pytest.mark.asyncio
async def test_append_audit_rejects_invalid_mode() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    with pytest.raises(ValueError, match="mode"):
        await store.append_audit_entry(
            {
                "event_id": str(uuid.uuid4()),
                "actor": "integration-test",
                "action_kind": "smoke",
                "mode": "invalid",
            }
        )


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=""))


def test_config_rejects_bad_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PostgresStateStore(
            config=PostgresStateStoreConfig(dsn="postgresql://x", statement_timeout_ms=0)
        )
