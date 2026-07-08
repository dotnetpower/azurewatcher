"""In-memory pub/sub bus for tests and single-process runs.

Real deployment wraps this contract around a Kafka client (Event Hubs
on `:9093`). The in-memory implementation shipping here exists so:

- Wave 2 through 8 code can be exercised end-to-end without an external
  broker.
- Fork maintainers can develop against a deterministic bus before
  integrating their Azure adapter.

The bus enforces the single-writer invariant at publish time by
delegating to :class:`fdai.agents.registry.PantheonRegistry`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fdai.agents.registry import PantheonRegistry

Payload = dict[str, Any]
Handler = Callable[[str, Payload], Awaitable[None]]


@runtime_checkable
class PantheonBus(Protocol):
    """Structural bus contract the pantheon agents depend on.

    Both the sync-dispatch :class:`InMemoryBus` (tests / single-process
    runs) and the Kafka-backed
    :class:`fdai.agents.bus_bridge.EventBusBridge` (production Event Hubs)
    satisfy this Protocol, so an agent binds to either without knowing
    which. Agents type their ``bus`` seam against this, never against the
    concrete test double - see the composition-root wiring in
    :mod:`fdai.agents.runtime`.
    """

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        """Register ``handler`` for every record published to ``topic``."""
        ...

    async def publish(self, principal: str, topic: str, payload: Payload) -> Any:
        """Publish ``payload`` to ``topic`` as ``principal`` (single-writer)."""
        ...


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    topic: str
    payload: Payload
    principal: str


@dataclass
class InMemoryBus:
    """Sync-dispatch pub/sub bus for tests.

    Publish delivers to every subscriber synchronously (await in order
    of subscription). This is intentional: tests rely on the entire
    reaction chain resolving before the publish returns.
    """

    registry: PantheonRegistry
    subscribers: dict[str, list[tuple[str, Handler]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    published: list[PublishedMessage] = field(default_factory=list)

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        self.subscribers[topic].append((agent_name, handler))

    async def publish(self, principal: str, topic: str, payload: Payload) -> None:
        self.registry.assert_can_publish(principal, topic)
        self.published.append(
            PublishedMessage(topic=topic, payload=dict(payload), principal=principal)
        )
        for _, handler in self.subscribers.get(topic, []):
            # Hand each subscriber its own copy so a handler that mutates the
            # payload cannot contaminate later subscribers or the caller's
            # object (the Kafka-backed bridge copies per delivery too).
            await handler(topic, dict(payload))

    def clear_history(self) -> None:
        self.published.clear()

    def messages_on(self, topic: str) -> list[PublishedMessage]:
        return [m for m in self.published if m.topic == topic]


__all__ = ["InMemoryBus", "PantheonBus", "PublishedMessage", "Payload", "Handler"]
