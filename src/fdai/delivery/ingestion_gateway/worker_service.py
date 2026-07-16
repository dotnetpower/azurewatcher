"""Kafka-driven document worker service for at-least-once processing."""

from __future__ import annotations

import asyncio
from typing import Final
from uuid import UUID

from fdai.core.document_ingestion import DocumentIngestionWorker
from fdai.shared.providers.event_bus import EventBus


class DocumentIngestionEventConsumer:
    def __init__(
        self,
        *,
        event_bus: EventBus,
        worker: DocumentIngestionWorker,
        topic: str,
        group_id: str = "fdai-document-worker",
        retry_seconds: float = 2.0,
    ) -> None:
        if not topic or not group_id or retry_seconds <= 0:
            raise ValueError("document worker topic, group_id, and retry_seconds are required")
        self._event_bus: Final = event_bus
        self._worker: Final = worker
        self._topic: Final = topic
        self._group_id: Final = group_id
        self._retry_seconds: Final = retry_seconds

    async def run(self) -> None:
        while True:
            try:
                async for event in self._event_bus.subscribe(self._topic, self._group_id):
                    if event.payload.get("event_type") != "document.received":
                        continue
                    upload_id = event.payload.get("upload_id")
                    if not isinstance(upload_id, str):
                        raise ValueError("document.received event is missing upload_id")
                    await self._worker.process(UUID(upload_id))
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(self._retry_seconds)


__all__ = ["DocumentIngestionEventConsumer"]
