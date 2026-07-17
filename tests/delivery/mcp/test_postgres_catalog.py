"""PostgreSQL managed MCP catalog restart and CAS tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.delivery.mcp import (
    ManagedMcpCatalogService,
    McpAdminAuditRecord,
    McpServerManifest,
    PostgresMcpCatalogStore,
    PostgresMcpCatalogStoreConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


class _Discovery:
    async def discover(self, manifest: McpServerManifest) -> frozenset[str]:
        return frozenset(manifest.tool_map.values())


def test_config_rejects_empty_dsn_or_bad_timeout() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresMcpCatalogStoreConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresMcpCatalogStoreConfig(dsn="postgresql://x", connect_timeout_s=0)


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_catalog_survives_restart_and_rejects_stale_revision() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    suffix = uuid.uuid4().hex[:8]
    config = PostgresMcpCatalogStoreConfig(dsn=dsn)
    store = PostgresMcpCatalogStore(config=config)
    service = ManagedMcpCatalogService(store=store, discovery=_Discovery())
    stale = await store.load()
    manifest = McpServerManifest(
        server_id=f"example.{suffix}",
        server_url=f"https://{suffix}.example.com/mcp",
        tool_map={f"tool.{suffix}": "example_tool"},
    )
    await service.install(manifest, actor_id="owner-example", at=_NOW)
    await service.enable(manifest.server_id, actor_id="owner-example", at=_NOW)

    restarted = PostgresMcpCatalogStore(config=config)
    loaded = await restarted.load()
    assert loaded.catalog.get(manifest.server_id).enabled is True
    assert (
        await restarted.commit(
            expected_revision=stale.revision,
            catalog=stale.catalog,
            health=stale.health,
            audit=McpAdminAuditRecord(
                action="mcp.server.stale_write",
                actor_id="owner-example",
                server_id=manifest.server_id,
                recorded_at=_NOW,
            ),
        )
        is False
    )
