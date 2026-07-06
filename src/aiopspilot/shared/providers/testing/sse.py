"""In-memory :class:`SseSink` - async fan-out queues, one per subscriber.

Late-join semantics: a subscriber that connects after ``publish()`` was
called MUST NOT see the earlier events (standard SSE / pub-sub). Callers
that need replay MUST persist elsewhere (audit log or Kafka topic) and
seed subscribers from that record.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from aiopspilot.shared.providers.sse import SseEvent, SseSink


class InMemorySseSink(SseSink):
    """Async fan-out to per-subscriber queues.

    Unbounded queues - this fake is for unit tests + debugger sessions,
    NOT production. Real HTTP adapters MUST handle backpressure (bounded
    queue + slow-consumer disconnect).
    """

    def __init__(self) -> None:
        # Per-channel list of live subscriber queues. Access under a lock
        # so publish() and subscribe() cannot race.
        self._subscribers: dict[str, list[asyncio.Queue[SseEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: SseEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(channel, ()))
        for queue in queues:
            # asyncio.Queue.put_nowait raises QueueFull only if the queue
            # is bounded; ours is unbounded so this is effectively O(1).
            queue.put_nowait(event)

    def subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        return self._subscribe(channel)

    async def _subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        queue: asyncio.Queue[SseEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(channel, []).append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            # Detach on cancel / consumer break so leaked queues do not
            # accumulate memory over long sessions.
            async with self._lock:
                bucket = self._subscribers.get(channel)
                if bucket is not None:
                    try:
                        bucket.remove(queue)
                    except ValueError:
                        pass
                    if not bucket:
                        self._subscribers.pop(channel, None)

    # ---- Test helpers --------------------------------------------------------

    def subscriber_count(self, channel: str) -> int:
        """Return the number of subscribers currently attached to ``channel``."""
        return len(self._subscribers.get(channel, ()))


__all__ = ["InMemorySseSink"]
