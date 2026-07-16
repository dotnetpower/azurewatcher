"""PostgreSQL metadata store for durable document-ingestion state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.shared.contracts import DocumentVersion, UploadSession
from fdai.shared.providers.document_ingestion import DocumentNotFoundError


@dataclass(frozen=True, slots=True)
class PostgresDocumentMetadataStoreConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresDocumentMetadataStoreConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgresDocumentMetadataStoreConfig timeouts MUST be positive")


class PostgresDocumentMetadataStore:
    def __init__(self, *, config: PostgresDocumentMetadataStoreConfig) -> None:
        self._config: Final = config

    async def create(self, session: UploadSession, version: DocumentVersion) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            try:
                await connection.execute(
                    "INSERT INTO document_upload_session "
                    "(upload_id, document_id, version_id, state, payload, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        session.upload_id,
                        session.document_id,
                        session.version_id,
                        session.state.value,
                        session.model_dump_json(),
                        session.created_at,
                        session.created_at,
                    ),
                )
                await connection.execute(
                    "INSERT INTO document_version "
                    "(document_id, version_id, upload_id, state, active, payload, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        version.document_id,
                        version.version_id,
                        version.upload_id,
                        version.state.value,
                        version.active,
                        version.model_dump_json(),
                        version.created_at,
                        version.updated_at,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError("document upload or version already exists") from exc

    async def get_upload(self, upload_id: UUID) -> UploadSession:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_upload_session WHERE upload_id = %s",
                (upload_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise DocumentNotFoundError("upload was not found")
        return UploadSession.model_validate(_payload(row["payload"]))

    async def save_upload(self, session: UploadSession) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "UPDATE document_upload_session SET state = %s, payload = %s::jsonb, "
                "updated_at = NOW() WHERE upload_id = %s RETURNING upload_id",
                (session.state.value, session.model_dump_json(), session.upload_id),
            )
            if await cursor.fetchone() is None:
                raise DocumentNotFoundError("upload was not found")

    async def get_version(self, document_id: UUID, version_id: UUID) -> DocumentVersion:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_version WHERE document_id = %s AND version_id = %s",
                (document_id, version_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise DocumentNotFoundError("document version was not found")
        return DocumentVersion.model_validate(_payload(row["payload"]))

    async def save_version(self, version: DocumentVersion) -> None:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if version.active:
                await connection.execute(
                    "UPDATE document_version SET active = FALSE, "
                    "payload = jsonb_set(payload, '{active}', 'false'::jsonb), updated_at = NOW() "
                    "WHERE document_id = %s AND version_id <> %s AND active",
                    (version.document_id, version.version_id),
                )
            cursor = await connection.execute(
                "UPDATE document_version SET state = %s, active = %s, payload = %s::jsonb, "
                "updated_at = %s WHERE document_id = %s AND version_id = %s "
                "RETURNING version_id",
                (
                    version.state.value,
                    version.active,
                    version.model_dump_json(),
                    version.updated_at,
                    version.document_id,
                    version.version_id,
                ),
            )
            if await cursor.fetchone() is None:
                raise DocumentNotFoundError("document version was not found")

    async def list_versions(self, document_id: UUID) -> tuple[DocumentVersion, ...]:
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT payload FROM document_version WHERE document_id = %s "
                "ORDER BY created_at ASC, version_id ASC",
                (document_id,),
            )
            rows = await cursor.fetchall()
        if not rows:
            raise DocumentNotFoundError("document was not found")
        return tuple(DocumentVersion.model_validate(_payload(row["payload"])) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            f"SET LOCAL statement_timeout = {int(self._config.statement_timeout_ms)}"
        )


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("document metadata payload is not a JSON object")


__all__ = ["PostgresDocumentMetadataStore", "PostgresDocumentMetadataStoreConfig"]
