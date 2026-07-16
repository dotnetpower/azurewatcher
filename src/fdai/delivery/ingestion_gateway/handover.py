"""Handover-bootstrap consumer and draft-result storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai.core.stewardship.handover_bootstrap import (
    DocumentKind,
    HandoverBootstrapper,
    HandoverDocument,
    StewardMapDraft,
    render_draft_yaml,
)
from fdai.shared.contracts import DocumentEnvelope, DocumentPurpose, UploadSession
from fdai.shared.providers import DocumentNotFoundError


@dataclass(frozen=True, slots=True)
class HandoverDraftArtifact:
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    draft: StewardMapDraft
    yaml: str

    def to_dict(self) -> dict[str, object]:
        return {
            "upload_id": str(self.upload_id),
            "document_id": str(self.document_id),
            "version_id": str(self.version_id),
            "draft": self.draft.to_dict(),
            "yaml": self.yaml,
        }


class HandoverDraftReader(Protocol):
    async def get(self, upload_id: UUID) -> HandoverDraftArtifact: ...


class InMemoryHandoverDraftStore:
    def __init__(self) -> None:
        self._items: dict[UUID, HandoverDraftArtifact] = {}

    async def put(self, artifact: HandoverDraftArtifact) -> None:
        self._items[artifact.upload_id] = artifact

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact:
        try:
            return self._items[upload_id]
        except KeyError as exc:
            raise DocumentNotFoundError("handover draft was not found") from exc


class HandoverBootstrapConsumer:
    purpose = DocumentPurpose.HANDOVER_BOOTSTRAP

    def __init__(
        self,
        *,
        bootstrapper: HandoverBootstrapper,
        store: InMemoryHandoverDraftStore,
    ) -> None:
        self._bootstrapper = bootstrapper
        self._store = store

    async def consume(
        self, *, session: UploadSession, envelope: DocumentEnvelope
    ) -> tuple[str, ...]:
        document = HandoverDocument(
            doc_id=str(envelope.document_id),
            kind=_document_kind(session.source_name),
            title=session.source_name,
            text="\n".join(unit.text for unit in envelope.units),
        )
        draft = await self._bootstrapper.bootstrap((document,))
        await self._store.put(
            HandoverDraftArtifact(
                upload_id=session.upload_id,
                document_id=envelope.document_id,
                version_id=envelope.version_id,
                draft=draft,
                yaml=render_draft_yaml(draft),
            )
        )
        return draft.warnings


def _document_kind(source_name: str) -> DocumentKind:
    lowered = source_name.casefold()
    if "raci" in lowered:
        return DocumentKind.RACI
    if "on-call" in lowered or "on_call" in lowered:
        return DocumentKind.ON_CALL
    if "org" in lowered:
        return DocumentKind.ORG_CHART
    if "runbook" in lowered:
        return DocumentKind.RUNBOOK
    if "handover" in lowered:
        return DocumentKind.HANDOVER_MEMO
    return DocumentKind.OTHER


__all__ = [
    "HandoverBootstrapConsumer",
    "HandoverDraftArtifact",
    "HandoverDraftReader",
    "InMemoryHandoverDraftStore",
]
