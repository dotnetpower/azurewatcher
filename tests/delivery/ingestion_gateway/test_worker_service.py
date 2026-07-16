"""Tests for Kafka-driven document processing."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fdai.delivery.ingestion_gateway.worker_service import DocumentIngestionEventConsumer
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


class _Worker:
    def __init__(self) -> None:
        self.upload_ids: list[UUID] = []

    async def process(self, upload_id: UUID) -> None:
        self.upload_ids.append(upload_id)


async def test_worker_processes_received_and_ignores_other_events() -> None:
    bus = InMemoryEventBus()
    worker = _Worker()
    upload_id = UUID("00000000-0000-0000-0000-000000000401")
    await bus.publish("aw.document.events", "doc", {"event_type": "upload.created"})
    await bus.publish(
        "aw.document.events",
        "doc",
        {"event_type": "document.received", "upload_id": str(upload_id)},
    )
    consumer = DocumentIngestionEventConsumer(
        event_bus=bus,
        worker=worker,  # type: ignore[arg-type]
        topic="aw.document.events",
        retry_seconds=0.01,
    )

    task = asyncio.create_task(consumer.run())
    for _ in range(20):
        if worker.upload_ids:
            break
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert worker.upload_ids == [upload_id]
