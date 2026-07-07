"""``SseBroadcaster`` - relay events from the internal ``EventBus`` to ``SseSink``.

The internal Kafka event bus carries machine-to-machine records. The
outbound SSE stream carries a redacted, JSON-encoded view of the same
records for browser / webhook consumers. This class is the boundary.

Design
------
- Every ``(topic, channel)`` pair is served by one background async task.
- Each task drives an ``async for envelope in event_bus.subscribe(topic,
  group_id)`` loop and calls ``await sse_sink.publish(channel, SseEvent
  (...))``.
- Cancellation is cooperative: :meth:`stop` cancels every task and
  awaits them; :meth:`run` is idempotent (calling it twice is a no-op
  on the second call).
- The broadcaster **never persists** anything; if a consumer disconnects
  mid-relay, later publishes are simply not delivered to that consumer.
  Persistent replay is the audit log's responsibility.

Wiring reference (planned)
--------------------------
- ``core/audit`` → ``aw.audit.stream`` SSE channel (audit log tail)
- ``core/risk_gate`` → ``aw.hil.queue`` SSE channel (HIL updates)
- ``core/tiers/*`` → ``aw.tier.decisions`` SSE channel (KPI dashboard)

The concrete map is a composition-root decision - this module only
supplies the mechanism.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from fdai.shared.providers.event_bus import EventBus, EventEnvelope
from fdai.shared.providers.sse import SseEvent, SseSink

_LOGGER = logging.getLogger(__name__)


class SseBroadcaster:
    """Relay :class:`EventBus` topics to :class:`SseSink` channels."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        sse_sink: SseSink,
        topic_channel_map: Mapping[str, str],
        event_type: str = "envelope",
        group_id_prefix: str = "fdai-sse",
    ) -> None:
        if not topic_channel_map:
            raise ValueError("topic_channel_map MUST NOT be empty")
        self._event_bus = event_bus
        self._sse_sink = sse_sink
        self._topic_channel_map = dict(topic_channel_map)
        self._event_type = event_type
        self._group_id_prefix = group_id_prefix
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._stopped = False

    async def run(self) -> None:
        """Start one relay task per topic → channel mapping.

        Idempotent - a second call before :meth:`stop` is a no-op. Once
        :meth:`stop` runs, the broadcaster is spent and MUST be
        re-instantiated.
        """
        if self._started:
            return
        if self._stopped:
            raise RuntimeError("broadcaster already stopped; instantiate a new one")
        self._started = True

        loop = asyncio.get_running_loop()
        for topic, channel in self._topic_channel_map.items():
            group_id = f"{self._group_id_prefix}-{channel}"
            self._tasks.append(
                loop.create_task(
                    self._relay_topic(topic, channel, group_id),
                    name=f"sse-relay:{topic}->{channel}",
                )
            )

    async def stop(self) -> None:
        """Cancel every relay task and wait for cleanup. Idempotent."""
        if self._stopped:
            return
        self._stopped = True

        for task in self._tasks:
            task.cancel()
        # Await every task so their `finally` blocks (queue detach in the
        # in-memory fake, connection close in a real Kafka client) run.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _relay_topic(self, topic: str, channel: str, group_id: str) -> None:
        try:
            async for envelope in self._event_bus.subscribe(topic, group_id):
                await self._sse_sink.publish(channel, self._envelope_to_sse(envelope))
        except asyncio.CancelledError:
            _LOGGER.debug(
                "sse-relay:%s->%s cancelled",
                topic,
                channel,
            )
            raise
        except Exception:  # pragma: no cover - real backends surface their own
            _LOGGER.exception("sse-relay:%s->%s crashed", topic, channel)
            raise

    def _envelope_to_sse(self, envelope: EventEnvelope) -> SseEvent:
        # Correlation id is optional; every audit-linked event carries it.
        correlation_id = _extract_correlation_id(envelope.payload)
        return SseEvent(
            id=correlation_id or _extract_event_id(envelope.payload),
            event=self._event_type,
            data=json.dumps(
                {
                    "topic": envelope.topic,
                    "key": envelope.key,
                    "offset": envelope.offset,
                    "payload": envelope.payload,
                },
                ensure_ascii=True,
                default=str,
            ),
        )


def _extract_correlation_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("correlation_id")
    return value if isinstance(value, str) and value else None


def _extract_event_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("event_id")
    return value if isinstance(value, str) and value else None


__all__ = ["SseBroadcaster"]
