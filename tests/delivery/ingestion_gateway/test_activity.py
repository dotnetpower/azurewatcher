"""Tests for durable document lifecycle activity delivery."""

from __future__ import annotations

from fdai.delivery.ingestion_gateway.activity import DurableDocumentActivitySink
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_activity_uses_fixed_topic_and_preserves_event_type() -> None:
    state = InMemoryStateStore()
    bus = InMemoryEventBus()
    sink = DurableDocumentActivitySink(
        state_store=state,
        event_bus=bus,
        event_topic="aw.document.events",
    )

    await sink.audit({"action": "document.ready", "document_id": "doc-1"})
    await sink.publish("document.ready", "doc-1", {"document_id": "doc-1"})

    records = [record async for record in bus.subscribe("aw.document.events", "test")]
    assert records[0].payload["event_type"] == "document.ready"
    assert len(state.audit_entries) == 1


def test_activity_rejects_empty_event_topic() -> None:
    try:
        DurableDocumentActivitySink(
            state_store=InMemoryStateStore(),
            event_bus=InMemoryEventBus(),
            event_topic="",
        )
    except ValueError as exc:
        assert "event_topic" in str(exc)
    else:
        raise AssertionError("empty event topic was accepted")
