"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

from typing import Any

from fdai.agents.adapters import InMemoryStateStore
from fdai.agents.base import Agent
from fdai.agents.pantheon import _MUNINN


class Muninn(Agent):
    """Wave-2 Muninn: state / context store proxy."""

    def __init__(self, *, state_store: InMemoryStateStore | None = None) -> None:
        super().__init__(spec=_MUNINN)
        self.state_store = state_store or InMemoryStateStore()

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.turn":
            turn_id = str(payload.get("turn_id") or payload.get("id", ""))
            if turn_id:
                self.state_store.put("conversation_turns", turn_id, payload)

    def get_context(self, bucket: str, key: str) -> Any | None:
        return self.state_store.get(bucket, key)

    def put_context(self, bucket: str, key: str, value: Any) -> None:
        self.state_store.put(bucket, key, value)


__all__ = ["Muninn"]
