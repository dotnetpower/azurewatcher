"""Deletion-aware in-memory embedding index for local document ingestion."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

from fdai.delivery.document_index.chunking import (
    DocumentChunkRecord,
    chunk_document_envelope,
    document_version_ref,
)
from fdai.shared.contracts import DocumentEnvelope
from fdai.shared.providers.knowledge import Embedder, KnowledgeChunk, cosine_similarity


class InMemoryEmbeddingDocumentIndex:
    def __init__(self, *, embedder: Embedder, max_chars: int = 1_200, overlap: int = 150) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars MUST be positive")
        if overlap < 0 or overlap >= max_chars:
            raise ValueError("overlap MUST be in [0, max_chars)")
        self._embedder: Final[Embedder] = embedder
        self._max_chars = max_chars
        self._overlap = overlap
        self._entries: dict[str, tuple[DocumentChunkRecord, tuple[float, ...]]] = {}

    async def commit(self, envelope: DocumentEnvelope) -> int:
        records = chunk_document_envelope(
            envelope,
            max_chars=self._max_chars,
            overlap=self._overlap,
        )
        embedded = [(record, tuple(await self._embedder.embed(record.text))) for record in records]
        version_ref = document_version_ref(envelope.document_id, envelope.version_id)
        retained = {
            chunk_id: entry
            for chunk_id, entry in self._entries.items()
            if entry[0].doc_id != version_ref
        }
        retained.update({record.chunk_id: (record, vector) for record, vector in embedded})
        self._entries = retained
        return len(embedded)

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        version_ref = document_version_ref(document_id, version_id)
        self._entries = {
            chunk_id: entry
            for chunk_id, entry in self._entries.items()
            if entry[0].doc_id != version_ref
        }

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
        query_vector = tuple(await self._embedder.embed(query))
        candidates: list[tuple[float, DocumentChunkRecord]] = []
        for record, vector in self._entries.values():
            if record.metadata["collection_id"] != collection_id:
                continue
            if record.metadata["access_descriptor_ref"] not in allowed_access_refs:
                continue
            candidates.append((cosine_similarity(query_vector, vector), record))
        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        return tuple(
            KnowledgeChunk(
                doc_id=record.doc_id,
                chunk_id=record.chunk_id,
                text=record.text,
                source_ref=record.source_ref,
                score=score,
                metadata=record.metadata,
            )
            for score, record in candidates[:k]
        )


__all__ = ["InMemoryEmbeddingDocumentIndex"]
