"""Protected channel attachment ingestion into citation-only evidence refs."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from fdai.core.conversation.channel_gateway import AttachmentIngestionResult
from fdai.core.conversation.session import Principal
from fdai.core.document_ingestion import (
    CreateUploadRequest,
    DocumentIngestionService,
    DocumentIngestionWorker,
)
from fdai.shared.contracts import (
    DocumentPurpose,
    DocumentState,
    SourceStorageMode,
)
from fdai.shared.providers.conversation_channel import ChannelAttachment, InboundTurn


class ChannelAttachmentFetcher(Protocol):
    """Fetch one opaque vendor ref using server-owned app credentials."""

    async def fetch(self, attachment: ChannelAttachment, *, max_bytes: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ChannelDocumentEvidenceConfig:
    collection_id: str
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    storage_mode: SourceStorageMode = SourceStorageMode.MANAGED_COPY

    def __post_init__(self) -> None:
        if not self.collection_id or not self.access_descriptor_ref:
            raise ValueError("channel evidence collection and access descriptor are required")
        if not self.retention_policy_version:
            raise ValueError("channel evidence retention policy is required")
        if self.storage_mode is SourceStorageMode.METADATA_ONLY:
            raise ValueError("channel evidence MUST pass byte-level ingestion protection")


class ProtectedChannelAttachmentIngestor:
    """Run every attachment through scan, protection, extraction, and indexing."""

    def __init__(
        self,
        *,
        service: DocumentIngestionService,
        worker: DocumentIngestionWorker,
        fetchers: dict[str, ChannelAttachmentFetcher],
        config: ChannelDocumentEvidenceConfig,
    ) -> None:
        self._service = service
        self._worker = worker
        self._fetchers = dict(fetchers)
        self._config = config

    async def ingest(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
    ) -> AttachmentIngestionResult:
        fetcher = self._fetchers.get(turn.channel_kind.value)
        if fetcher is None:
            return AttachmentIngestionResult(
                status="rejected",
                reason="channel attachment fetcher is unavailable",
            )
        evidence_refs: list[str] = []
        for attachment in turn.attachments:
            if attachment.size_bytes > self._service.capabilities.max_file_size:
                return _rejected("attachment exceeds the ingestion size limit")
            content = await fetcher.fetch(
                attachment,
                max_bytes=self._service.capabilities.max_file_size,
            )
            if len(content) != attachment.size_bytes:
                return _rejected("attachment size does not match channel metadata")
            session, _ = await self._service.create_upload(
                actor_id=principal.id,
                request=CreateUploadRequest(
                    source_name=attachment.name,
                    collection_id=self._config.collection_id,
                    media_type_hint=attachment.media_type_hint,
                    expected_size=len(content),
                    expected_sha256=hashlib.sha256(content).hexdigest(),
                    storage_mode=self._config.storage_mode,
                    purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
                    access_descriptor_ref=self._config.access_descriptor_ref,
                    reader_groups=self._config.reader_groups,
                    retention_policy_version=self._config.retention_policy_version,
                ),
            )
            if self._service.capabilities.direct_upload:
                await self._service.put_local_content(
                    actor_id=principal.id,
                    upload_id=session.upload_id,
                    content=content,
                )
            else:
                await self._service.put_streaming_content(
                    actor_id=principal.id,
                    upload_id=session.upload_id,
                    chunks=_single_chunk(content),
                )
            await self._service.complete_upload(
                actor_id=principal.id,
                upload_id=session.upload_id,
            )
            version = await self._worker.process(session.upload_id)
            if (
                version.state
                not in {
                    DocumentState.READY,
                    DocumentState.READY_WITH_WARNINGS,
                }
                or not version.available
            ):
                return _rejected("attachment was held by ingestion protection")
            evidence_refs.append(f"doc:{version.document_id}:{version.version_id}")
        return AttachmentIngestionResult(
            status="ready",
            evidence_refs=tuple(evidence_refs),
        )


async def _single_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _rejected(reason: str) -> AttachmentIngestionResult:
    return AttachmentIngestionResult(status="rejected", reason=reason)


__all__ = [
    "ChannelAttachmentFetcher",
    "ChannelDocumentEvidenceConfig",
    "ProtectedChannelAttachmentIngestor",
]
