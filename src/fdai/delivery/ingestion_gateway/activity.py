"""Durable audit and event delivery for document-ingestion lifecycle records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


class DurableDocumentActivitySink:
    def __init__(self, *, state_store: StateStore, event_bus: EventBus, event_topic: str) -> None:
        if not event_topic:
            raise ValueError("document event_topic MUST NOT be empty")
        self._state_store: Final = state_store
        self._event_bus: Final = event_bus
        self._event_topic: Final = event_topic

    async def audit(self, record: Mapping[str, object]) -> None:
        await self._state_store.append_audit_entry(record)

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> None:
        event = dict(payload)
        event["event_type"] = topic
        await self._event_bus.publish(self._event_topic, key, event)


__all__ = ["DurableDocumentActivitySink"]
