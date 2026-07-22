"""Publish observed Pantheon health as cross-process runtime-state snapshots."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Sequence

from fdai.delivery.read_api.streaming.agent_activity_stream import AgentStateEvent
from fdai.shared.providers.event_bus import EventBus

DEFAULT_RUNTIME_STATE_TOPIC = "aw.pipeline.stages"
DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS = 15.0
DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS = 0.25

_LOGGER = logging.getLogger(__name__)


class AgentRuntimeStatePublisher:
    """Project live Pantheon health onto the shared object bus."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        snapshot_factory: Callable[[], Sequence[AgentStateEvent]],
        topic: str = DEFAULT_RUNTIME_STATE_TOPIC,
        interval_seconds: float = DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS,
    ) -> None:
        if not topic:
            raise ValueError("topic MUST be non-empty")
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("interval_seconds MUST be finite and positive")
        self._event_bus = event_bus
        self._snapshot_factory = snapshot_factory
        self._topic = topic
        self._interval_seconds = interval_seconds
        self._stopped = asyncio.Event()

    async def publish_once(self) -> int:
        """Publish one current health snapshot and return its agent count."""
        events = tuple(self._snapshot_factory())
        for event in events:
            payload = event.to_payload()
            payload["type"] = "agent.runtime-state"
            await self._event_bus.publish(self._topic, event.agent, payload)
        return len(events)

    async def run(self) -> None:
        """Publish immediately and then refresh until stopped."""
        while not self._stopped.is_set():
            published = 0
            try:
                published = await self.publish_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - telemetry failure must not stop the Pantheon
                _LOGGER.warning(
                    "agent_runtime_state_publish_failed",
                    extra={"topic": self._topic},
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=(
                        self._interval_seconds
                        if published > 0
                        else min(
                            self._interval_seconds,
                            DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS,
                        )
                    ),
                )
            except TimeoutError:
                continue

    async def stop(self) -> None:
        """Stop the periodic publisher without stopping the shared bus."""
        self._stopped.set()


__all__ = [
    "DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS",
    "DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS",
    "DEFAULT_RUNTIME_STATE_TOPIC",
    "AgentRuntimeStatePublisher",
]
