"""Delivery adapters for governed document chunk indexing."""

from fdai.delivery.document_index.chunking import (
    DocumentChunkRecord,
    chunk_document_envelope,
    document_version_ref,
)
from fdai.delivery.document_index.memory import InMemoryEmbeddingDocumentIndex

__all__ = [
    "DocumentChunkRecord",
    "InMemoryEmbeddingDocumentIndex",
    "chunk_document_envelope",
    "document_version_ref",
]
