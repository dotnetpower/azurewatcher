"""Forseti-gated document worker service for at-least-once processing."""

from __future__ import annotations

import asyncio
import logging
from typing import Final
from uuid import UUID

from fdai.core.document_ingestion import DocumentIngestionWorker
from fdai.shared.contracts import DocumentState
from fdai.shared.providers.document_ingestion import DocumentMetadataStore
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)


class DocumentIngestionEventConsumer:
    def __init__(
        self,
        *,
        event_bus: EventBus,
        worker: DocumentIngestionWorker,
        metadata: DocumentMetadataStore,
        topic: str,
        group_id: str = "fdai-document-admission-worker",
        retry_seconds: float = 2.0,
        reconcile_interval_seconds: float = 30.0,
        reconcile_batch_size: int = 100,
    ) -> None:
        if (
            topic != "object.verdict"
            or not group_id
            or retry_seconds <= 0
            or reconcile_interval_seconds <= 0
            or reconcile_batch_size < 1
        ):
            raise ValueError("document worker MUST consume object.verdict with valid limits")
        self._event_bus: Final = event_bus
        self._worker: Final = worker
        self._metadata: Final = metadata
        self._topic: Final = topic
        self._group_id: Final = group_id
        self._retry_seconds: Final = retry_seconds
        self._reconcile_interval_seconds: Final = reconcile_interval_seconds
        self._reconcile_batch_size: Final = reconcile_batch_size
        self._active: set[UUID] = set()
        self._active_lock = asyncio.Lock()

    async def run(self) -> None:
        while True:
            try:
                async for event in self._event_bus.subscribe(self._topic, self._group_id):
                    if (
                        event.payload.get("kind") != "document_ingestion"
                        or event.payload.get("stage") != "received"
                        or event.payload.get("decision") != "admit"
                    ):
                        continue
                    upload_id = event.payload.get("upload_id")
                    if not isinstance(upload_id, str):
                        raise ValueError("document admission verdict is missing upload_id")
                    await self._process_once(UUID(upload_id))
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error(
                    "document_ingestion_event_consumer_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                await asyncio.sleep(self._retry_seconds)

    async def reconcile(self) -> None:
        while True:
            try:
                for state in (
                    DocumentState.QUARANTINED,
                    DocumentState.SCANNING,
                    DocumentState.PROTECTION_CHECK,
                    DocumentState.EXTRACTING,
                    DocumentState.INDEXING,
                ):
                    sessions = await self._metadata.list_uploads_by_state(
                        state.value,
                        limit=self._reconcile_batch_size,
                    )
                    for session in sessions:
                        try:
                            await self._process_once(session.upload_id)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _LOGGER.error(
                                "document_ingestion_reconcile_upload_failed",
                                extra={
                                    "upload_id": str(session.upload_id),
                                    "exception_type": type(exc).__name__,
                                },
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error(
                    "document_ingestion_reconcile_cycle_failed",
                    extra={"exception_type": type(exc).__name__},
                )
            await asyncio.sleep(self._reconcile_interval_seconds)

    async def _process_once(self, upload_id: UUID) -> None:
        async with self._active_lock:
            if upload_id in self._active:
                return
            self._active.add(upload_id)
        try:
            await self._worker.process(upload_id)
        finally:
            async with self._active_lock:
                self._active.discard(upload_id)


__all__ = ["DocumentIngestionEventConsumer"]
