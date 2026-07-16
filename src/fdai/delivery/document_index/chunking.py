"""Structure-aware chunk mapping for document envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from fdai.shared.contracts import DocumentEnvelope
from fdai.shared.providers.knowledge import chunk_text


@dataclass(frozen=True, slots=True)
class DocumentChunkRecord:
    chunk_id: str
    doc_id: str
    text: str
    source_ref: str
    metadata: Mapping[str, str]


def document_version_ref(document_id: UUID, version_id: UUID) -> str:
    return f"governed:{document_id}:{version_id}"


def chunk_document_envelope(
    envelope: DocumentEnvelope,
    *,
    max_chars: int = 1_200,
    overlap: int = 150,
) -> tuple[DocumentChunkRecord, ...]:
    """Split each structural unit while preserving citation and access metadata."""
    version_ref = document_version_ref(envelope.document_id, envelope.version_id)
    records: list[DocumentChunkRecord] = []
    for unit in envelope.units:
        pieces = chunk_text(unit.text, max_chars=max_chars, overlap=overlap)
        for piece_index, piece in enumerate(pieces):
            records.append(
                DocumentChunkRecord(
                    chunk_id=f"{version_ref}:{unit.unit_id}:{piece_index}",
                    doc_id=version_ref,
                    text=piece,
                    source_ref=(
                        f"document://{envelope.document_id}/versions/"
                        f"{envelope.version_id}#{unit.unit_id}"
                    ),
                    metadata={
                        "governed_document": "true",
                        "document_id": str(envelope.document_id),
                        "version_id": str(envelope.version_id),
                        "collection_id": envelope.collection_id,
                        "access_descriptor_ref": envelope.access_descriptor_ref,
                        "source_sha256": envelope.source_sha256,
                        "unit_id": unit.unit_id,
                        "unit_kind": unit.kind,
                        "locator": unit.locator,
                        "protection_state": envelope.protection_state.value,
                        "purposes": ",".join(purpose.value for purpose in envelope.purposes),
                    },
                )
            )
    return tuple(records)


__all__ = ["DocumentChunkRecord", "chunk_document_envelope", "document_version_ref"]
