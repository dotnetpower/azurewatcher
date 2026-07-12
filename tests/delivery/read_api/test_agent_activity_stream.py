"""Tests for the agent-activity SSE surface (Track B, Phase 1).

Split by concern:

- ``TestWireEncoding`` - the three semantic events serialize to the
  documented JSON payloads.
- ``TestConfig`` - dataclass validation.
- ``TestPublisher`` - one event fans out through ``InMemorySseSink``.
- ``TestSyntheticEmitter`` - the heartbeat + incident narrative publishes
  the expected event kinds and ticket lifecycle on the channel.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from fdai.delivery.read_api.streaming.agent_activity_emitter import (
    SyntheticAgentActivityEmitter,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityStreamConfig,
    AgentState,
    AgentStateEvent,
    ConversationTurnEvent,
    IncidentTicketEvent,
    SseAgentActivityPublisher,
    TicketStatus,
    TurnKind,
)
from fdai.shared.providers.testing.sse import InMemorySseSink


class TestWireEncoding:
    def test_agent_state_payload(self) -> None:
        ev = AgentStateEvent(
            agent="Heimdall", state=AgentState.WATCHING, ts="2026-07-12T00:00:00+00:00"
        )
        payload = json.loads(ev.to_sse_event().data)
        assert payload["type"] == "agent.state"
        assert payload["agent"] == "Heimdall"
        assert payload["state"] == "watching"
        assert payload["correlation_id"] is None

    def test_incident_ticket_payload(self) -> None:
        ev = IncidentTicketEvent(
            ticket_id="FDAI-1234",
            correlation_id="incident-abc",
            status=TicketStatus.OPEN,
            title="t",
            severity="high",
            involved_agents=("Heimdall", "Forseti"),
            ts="2026-07-12T00:00:00+00:00",
        )
        payload = json.loads(ev.to_sse_event().data)
        assert payload["type"] == "incident.ticket"
        assert payload["status"] == "open"
        assert payload["involved_agents"] == ["Heimdall", "Forseti"]
        assert payload["rca"] is None

    def test_conversation_turn_payload(self) -> None:
        ev = ConversationTurnEvent(
            correlation_id="incident-abc",
            from_agent="Heimdall",
            to_agent="Forseti",
            kind=TurnKind.HANDOFF,
            text="anomaly 0.92",
            ts="2026-07-12T00:00:00+00:00",
        )
        payload = json.loads(ev.to_sse_event().data)
        assert payload["type"] == "conversation.turn"
        assert payload["from_agent"] == "Heimdall"
        assert payload["to_agent"] == "Forseti"
        assert payload["kind"] == "handoff"


class TestConfig:
    def test_defaults(self) -> None:
        cfg = AgentActivityStreamConfig()
        assert cfg.path == "/agents/stream"
        assert cfg.channel == "fdai.agents.events"

    def test_rejects_bad_path(self) -> None:
        with pytest.raises(ValueError, match="MUST start with"):
            AgentActivityStreamConfig(path="agents")

    def test_rejects_empty_channel(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            AgentActivityStreamConfig(channel="")

    def test_rejects_non_positive_keepalive(self) -> None:
        with pytest.raises(ValueError, match="keepalive_seconds"):
            AgentActivityStreamConfig(keepalive_seconds=0)


class TestPublisher:
    async def test_publish_fans_out_on_channel(self) -> None:
        sink = InMemorySseSink()
        pub = SseAgentActivityPublisher(sink=sink, channel="c")
        received: list[dict[str, object]] = []

        async def collect() -> None:
            async for ev in sink.subscribe("c"):
                received.append(json.loads(ev.data))
                return

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # let the subscriber register
        await pub.publish(
            AgentStateEvent(agent="Odin", state=AgentState.IDLE, ts="2026-07-12T00:00:00+00:00")
        )
        await asyncio.wait_for(task, timeout=2.0)
        assert received[0]["agent"] == "Odin"


class TestSyntheticEmitter:
    async def test_incident_narrative_publishes_lifecycle(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticAgentActivityEmitter(
            sink=sink,
            channel="c",
            incident_interval_seconds=0.02,
            beat_seconds=0.001,
            seed=7,
        )
        seen: list[dict[str, object]] = []

        async def collect() -> None:
            async for ev in sink.subscribe("c"):
                payload = json.loads(ev.data)
                seen.append(payload)
                if payload["type"] == "incident.ticket" and payload["status"] == "resolved":
                    return

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)
        await emitter.start()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        finally:
            await emitter.stop()

        kinds = {p["type"] for p in seen}
        assert kinds == {"agent.state", "incident.ticket", "conversation.turn"}
        # Ticket lifecycle: open -> ... -> resolved.
        ticket_statuses = [p["status"] for p in seen if p["type"] == "incident.ticket"]
        assert ticket_statuses[0] == "open"
        assert ticket_statuses[-1] == "resolved"
        assert "investigating" in ticket_statuses
        # RCA present on the resolved ticket.
        resolved = next(
            p for p in seen if p["type"] == "incident.ticket" and p["status"] == "resolved"
        )
        assert resolved["rca"]
        # At least one A2A conversation turn and an executing/approving state.
        assert any(p["type"] == "conversation.turn" for p in seen)
        states = {p["state"] for p in seen if p["type"] == "agent.state"}
        assert "executing" in states or "approving" in states

    async def test_stop_is_idempotent(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticAgentActivityEmitter(sink=sink, channel="c")
        await emitter.stop()  # never started - must not raise
        await emitter.start()
        await emitter.stop()
        await emitter.stop()  # double stop - must not raise
