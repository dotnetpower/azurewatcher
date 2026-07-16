"""Persistent pgvector index for governed document envelopes."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.document_index.chunking import chunk_document_envelope, document_version_ref
from fdai.delivery.pgvector.knowledge import _coerce_metadata, _encode_vector
from fdai.shared.contracts import DocumentEnvelope
from fdai.shared.providers.knowledge import Embedder, KnowledgeChunk
from fdai.shared.providers.secret_provider import SecretProvider

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class PgvectorDocumentIndexConfig:
    dsn_secret: str
    table: str = "knowledge_chunk"
    embedding_dim: int = 384
    max_chars: int = 1_200
    overlap: int = 150
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10

    def __post_init__(self) -> None:
        if not self.dsn_secret:
            raise ValueError("dsn_secret MUST be non-empty")
        if not _IDENTIFIER_RE.fullmatch(self.table):
            raise ValueError("table MUST be a plain ASCII SQL identifier")
        if self.embedding_dim < 1:
            raise ValueError("embedding_dim MUST be >= 1")
        if self.max_chars <= 0:
            raise ValueError("max_chars MUST be positive")
        if self.overlap < 0 or self.overlap >= self.max_chars:
            raise ValueError("overlap MUST be in [0, max_chars)")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        if self.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")


class PgvectorDocumentIndex:
    """Atomic document-version index with access-filtered retrieval."""

    def __init__(
        self,
        *,
        config: PgvectorDocumentIndexConfig,
        embedder: Embedder,
        secrets: SecretProvider,
    ) -> None:
        self._config: Final[PgvectorDocumentIndexConfig] = config
        self._embedder: Final[Embedder] = embedder
        self._secrets: Final[SecretProvider] = secrets

    async def commit(self, envelope: DocumentEnvelope) -> int:
        records = chunk_document_envelope(
            envelope,
            max_chars=self._config.max_chars,
            overlap=self._config.overlap,
        )
        rows: list[tuple[str, str, str, str, str, str]] = []
        for record in records:
            vector = await self._embedder.embed(record.text)
            rows.append(
                (
                    record.chunk_id,
                    record.doc_id,
                    record.text,
                    record.source_ref,
                    _encode_vector(vector, dim=self._config.embedding_dim),
                    json.dumps(dict(record.metadata), sort_keys=True),
                )
            )

        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                await connection.execute(
                    f"DELETE FROM {table} WHERE doc_id = %s",  # noqa: S608
                    (document_version_ref(envelope.document_id, envelope.version_id),),
                )
                for row in rows:
                    await connection.execute(
                        f"""
                        INSERT INTO {table}
                            (chunk_id, doc_id, text, source_ref, embedding, metadata)
                        VALUES (%s, %s, %s, %s, %s::vector, %s::jsonb)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            doc_id = EXCLUDED.doc_id,
                            text = EXCLUDED.text,
                            source_ref = EXCLUDED.source_ref,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata
                        """,  # noqa: S608
                        row,
                    )
        return len(rows)

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                await connection.execute(
                    f"DELETE FROM {table} WHERE doc_id = %s",  # noqa: S608
                    (document_version_ref(document_id, version_id),),
                )

    async def search(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        k: int = 5,
    ) -> Sequence[KnowledgeChunk]:
        if k <= 0 or not allowed_access_refs:
            return ()
        vector = await self._embedder.embed(query)
        literal = _encode_vector(vector, dim=self._config.embedding_dim)
        dsn = await self._secrets.get(self._config.dsn_secret)
        table = self._config.table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"""
                    SELECT doc_id,
                           chunk_id,
                           text,
                           source_ref,
                           metadata,
                           1.0 - (embedding <=> %s::vector) AS score
                      FROM {table}
                                         WHERE metadata->>'governed_document' = 'true'
                                             AND metadata->>'collection_id' = %s
                       AND metadata->>'access_descriptor_ref' = ANY(%s)
                     ORDER BY embedding <=> %s::vector ASC
                     LIMIT %s
                    """,  # noqa: S608
                    (
                        literal,
                        collection_id,
                        sorted(allowed_access_refs),
                        literal,
                        int(k),
                    ),
                )
                fetched = await cursor.fetchall()
        return tuple(
            KnowledgeChunk(
                doc_id=str(row["doc_id"]),
                chunk_id=str(row["chunk_id"]),
                text=str(row["text"]),
                source_ref=str(row["source_ref"]),
                score=float(row["score"]),
                metadata=_coerce_metadata(row["metadata"]),
            )
            for row in fetched
        )

    async def _set_session_knobs(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout_ms = int(self._config.statement_timeout_ms)
        probes = int(self._config.ivfflat_probes)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        await connection.execute(f"SET LOCAL ivfflat.probes = {probes}")


__all__ = ["PgvectorDocumentIndex", "PgvectorDocumentIndexConfig"]
