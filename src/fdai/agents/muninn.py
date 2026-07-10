"""Muninn - Memory (Wave 2 behavior).

Muninn owns the state / context store used by other agents. In Wave 2
the implementation is a simple in-memory KV; fork adapters swap in a
persistent backend (Postgres, pgvector).
"""

from __future__ import annotations

from typing import Any

from fdai.agents.adapters import InMemoryStateStore
from fdai.agents.base import Agent
from fdai.agents.introspection import (
    IntrospectionResult,
    capability_facts,
    mentioned,
)
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

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        data = self.state_store.data
        facts = {
            **capability_facts(self.spec),
            "buckets": sorted(data),
            "total_keys": sum(len(v) for v in data.values()),
        }
        buckets = mentioned(question, data)
        if buckets:
            bucket = buckets[0]
            facts.update({"bucket": bucket, "key_count": len(data[bucket])})
            answer = f"Bucket {bucket!r} holds {len(data[bucket])} key(s)."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Holding {len(data)} state bucket(s) with "
            f"{sum(len(v) for v in data.values())} key(s) total."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Muninn"]
