"""Tests for health-derived Pantheon runtime-state publication."""

from __future__ import annotations

import pytest

from fdai.delivery.read_api.streaming.agent_activity_stream import (
    runtime_agent_state_snapshot,
)
from fdai.delivery.read_api.streaming.agent_runtime_state_publisher import (
    AgentRuntimeStatePublisher,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def test_publishes_observed_state_for_every_live_agent() -> None:
    event_bus = InMemoryEventBus()
    health = {
        "consumers_live": 2,
        "agent_health": {
            "Odin": {"status": "ok"},
            "Huginn": {"status": "ok"},
        },
    }
    publisher = AgentRuntimeStatePublisher(
        event_bus=event_bus,
        snapshot_factory=lambda: runtime_agent_state_snapshot(health),
    )

    assert await publisher.publish_once() == 2
    payloads = [
        envelope.payload
        async for envelope in event_bus.subscribe("aw.pipeline.stages", "test-reader")
    ]

    assert [payload["agent"] for payload in payloads] == ["Odin", "Huginn"]
    assert [payload["state"] for payload in payloads] == ["idle", "watching"]
    assert all(payload["type"] == "agent.runtime-state" for payload in payloads)
    assert all(payload["source"] == "runtime-observed" for payload in payloads)


async def test_does_not_publish_when_consumers_are_not_live() -> None:
    event_bus = InMemoryEventBus()
    publisher = AgentRuntimeStatePublisher(
        event_bus=event_bus,
        snapshot_factory=lambda: runtime_agent_state_snapshot(
            {
                "consumers_live": 0,
                "agent_health": {"Odin": {"status": "ok"}},
            }
        ),
    )

    assert await publisher.publish_once() == 0


@pytest.mark.parametrize("interval", [0.0, -1.0, float("nan"), float("inf")])
def test_rejects_invalid_configuration(interval: float) -> None:
    with pytest.raises(ValueError, match="interval_seconds MUST be finite and positive"):
        AgentRuntimeStatePublisher(
            event_bus=InMemoryEventBus(),
            snapshot_factory=tuple,
            interval_seconds=interval,
        )
