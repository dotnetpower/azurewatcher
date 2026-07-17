"""PostgreSQL managed MCP catalog store with atomic audit commits."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.mcp.catalog import McpServerCatalog, McpServerManifest
from fdai.delivery.mcp.management import (
    ManagedMcpSnapshot,
    McpAdminAuditRecord,
    McpHealthStatus,
    McpServerHealth,
)


@dataclass(frozen=True, slots=True)
class PostgresMcpCatalogStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresMcpCatalogStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresMcpCatalogStoreConfig timeouts MUST be positive")


class PostgresMcpCatalogStore:
    """Revision-CAS catalog persistence; each commit appends its admin audit."""

    def __init__(self, *, config: PostgresMcpCatalogStoreConfig) -> None:
        self._config = config

    async def load(self) -> ManagedMcpSnapshot:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            revision_cursor = await connection.execute(
                "SELECT revision FROM mcp_catalog_state WHERE singleton = TRUE FOR SHARE"
            )
            revision_row = await revision_cursor.fetchone()
            if revision_row is None:
                raise RuntimeError("managed MCP catalog state row is missing")
            cursor = await connection.execute(
                """
                SELECT server_id, server_url, tool_map, audience, enabled,
                       health_status, health_checked_at, health_reason
                  FROM mcp_server
                 ORDER BY server_id
                """
            )
            rows = await cursor.fetchall()
        manifests: dict[str, McpServerManifest] = {}
        health: dict[str, McpServerHealth] = {}
        for row in rows:
            server_id = str(row["server_id"])
            tool_map = row["tool_map"]
            if not isinstance(tool_map, dict):
                raise ValueError("managed MCP tool_map row MUST be a JSON object")
            manifests[server_id] = McpServerManifest(
                server_id=server_id,
                server_url=str(row["server_url"]),
                tool_map={str(key): str(value) for key, value in tool_map.items()},
                audience=str(row["audience"]) if row["audience"] is not None else None,
                enabled=bool(row["enabled"]),
            )
            health[server_id] = McpServerHealth(
                status=McpHealthStatus(str(row["health_status"])),
                checked_at=row["health_checked_at"],
                reason=str(row["health_reason"]),
            )
        return ManagedMcpSnapshot(
            revision=int(revision_row["revision"]),
            catalog=McpServerCatalog(manifests),
            health=health,
        )

    async def commit(
        self,
        *,
        expected_revision: int,
        catalog: McpServerCatalog,
        health: Mapping[str, McpServerHealth],
        audit: McpAdminAuditRecord,
    ) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            revision_cursor = await connection.execute(
                "SELECT revision FROM mcp_catalog_state WHERE singleton = TRUE FOR UPDATE"
            )
            revision_row = await revision_cursor.fetchone()
            if revision_row is None:
                raise RuntimeError("managed MCP catalog state row is missing")
            if int(revision_row["revision"]) != expected_revision:
                return False
            await connection.execute("DELETE FROM mcp_server")
            for manifest in catalog.list():
                server_health = health.get(
                    manifest.server_id,
                    McpServerHealth(McpHealthStatus.UNKNOWN),
                )
                await connection.execute(
                    """
                    INSERT INTO mcp_server (
                        server_id, server_url, tool_map, audience, enabled,
                        health_status, health_checked_at, health_reason
                    ) VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                    """,
                    (
                        manifest.server_id,
                        manifest.server_url,
                        json.dumps(dict(manifest.tool_map), sort_keys=True),
                        manifest.audience,
                        manifest.enabled,
                        server_health.status.value,
                        server_health.checked_at,
                        server_health.reason,
                    ),
                )
            next_revision = expected_revision + 1
            await connection.execute(
                "UPDATE mcp_catalog_state SET revision = %s, updated_at = now() "
                "WHERE singleton = TRUE",
                (next_revision,),
            )
            await connection.execute(
                """
                INSERT INTO mcp_admin_audit (
                    revision, action, actor_id, server_id, recorded_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    next_revision,
                    audit.action,
                    audit.actor_id,
                    audit.server_id,
                    audit.recorded_at,
                ),
            )
        return True

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


__all__ = ["PostgresMcpCatalogStore", "PostgresMcpCatalogStoreConfig"]
