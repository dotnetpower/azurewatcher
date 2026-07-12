"""Synthetic agent-activity emitter - dev / demo producer for the console.

Publishes an idle/watching **heartbeat** for the 15 pantheon agents plus a
periodic **incident narrative** (detect -> ticket -> RCA conversation ->
resolve) onto the agent-activity SSE channel, so the ``Now > Agents`` panel
shows the collaboration alive without the real pantheon driving the hot
path. This is the agent-centric counterpart of
:class:`~fdai.delivery.read_api.streaming.live_stream.SyntheticLiveEmitter`.

**Dev only.** It is not a substitute for the real relay; the wire contract
(:mod:`fdai.delivery.read_api.streaming.agent_activity_stream`) is identical
so swapping in the real producer needs no console change.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentState,
    AgentStateEvent,
    ConversationTurnEvent,
    IncidentTicketEvent,
    SseAgentActivityPublisher,
    TicketStatus,
    TurnKind,
)
from fdai.shared.providers.sse import SseSink

_LOGGER = logging.getLogger(__name__)

# Plain-language task description per state, streamed as the event `detail`
# so the console hover card can tell the operator what an agent is doing
# (not just the coarse state ring). English-only (L0 wire surface).
_STATE_DETAIL: dict[AgentState, str] = {
    AgentState.COLLECTING: "Ingesting and correlating signals for the event",
    AgentState.ANALYZING: "Grounded root-cause reasoning on the incident",
    AgentState.DECIDING: "Issuing a verdict at the risk gate",
    AgentState.EXECUTING: "Applying the approved remediation",
    AgentState.APPROVING: "Reviewing the human-in-the-loop approval",
    AgentState.AUDITING: "Writing the append-only audit record",
}

# The 15 pantheon agents (dev constant - the synthetic emitter needs no
# dependency on the agents package; the real relay carries the names).
_SENSING = ("Huginn", "Heimdall")
_ALL_AGENTS: tuple[str, ...] = (
    "Odin",
    "Thor",
    "Forseti",
    "Huginn",
    "Heimdall",
    "Var",
    "Vidar",
    "Bragi",
    "Saga",
    "Mimir",
    "Norns",
    "Muninn",
    "Njord",
    "Freyr",
    "Loki",
)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True, slots=True)
class _Step:
    """One beat of an incident narrative."""

    delay: float
    kind: str  # "state" | "ticket" | "turn"
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Scenario:
    """A named incident narrative (detect -> ticket -> RCA -> resolve)."""

    title: str
    severity: str
    involved: Sequence[str]
    detector: str
    turns: Sequence[tuple[str, str, TurnKind, str]]  # from, to, kind, text
    rca: str


# A handful of realistic collaboration narratives (mirror the validated
# chaos scenarios). Customer-agnostic: only pantheon names + generic text.
_SCENARIOS: tuple[_Scenario, ...] = (
    _Scenario(
        title="AKS pod restart storm on nginx workload",
        severity="high",
        involved=("Heimdall", "Forseti", "Loki", "Var", "Thor", "Saga"),
        detector="Heimdall",
        turns=(
            (
                "Heimdall",
                "Forseti",
                TurnKind.HANDOFF,
                "anomaly score 0.92 - pod restart rate 3/min over baseline",
            ),
            (
                "Forseti",
                "Loki",
                TurnKind.QUESTION,
                "is a chaos experiment scheduled on this workload?",
            ),
            (
                "Loki",
                "Forseti",
                TurnKind.ANSWER,
                "yes - aks-pod-kill, blast radius capped at 1 target",
            ),
            (
                "Forseti",
                "Var",
                TurnKind.HANDOFF,
                "proposed auto-heal: scale-out replica set; requesting approval",
            ),
            ("Var", "Thor", TurnKind.HANDOFF, "approved - within blast-radius policy"),
        ),
        rca="Scheduled chaos experiment (aks-pod-kill); blast radius contained, auto-heal applied",
    ),
    _Scenario(
        title="MySQL sustained CPU pressure",
        severity="medium",
        involved=("Heimdall", "Forseti", "Njord", "Thor", "Saga"),
        detector="Heimdall",
        turns=(
            ("Heimdall", "Forseti", TurnKind.HANDOFF, "db cpu_percent held at 100% for 3 minutes"),
            ("Forseti", "Njord", TurnKind.QUESTION, "cost impact of scaling the tier up?"),
            ("Njord", "Forseti", TurnKind.ANSWER, "negligible - burstable tier, within budget"),
            ("Forseti", "Thor", TurnKind.HANDOFF, "auto-heal: throttle the load generator"),
        ),
        rca="Query-load spike saturated the burstable tier; load shed, CPU recovered",
    ),
    _Scenario(
        title="Azure OpenAI 429 rate-limit surge",
        severity="high",
        involved=("Heimdall", "Forseti", "Njord", "Var", "Thor", "Saga"),
        detector="Heimdall",
        turns=(
            (
                "Heimdall",
                "Forseti",
                TurnKind.HANDOFF,
                "429 rate crossed threshold on the chat deployment",
            ),
            ("Forseti", "Njord", TurnKind.QUESTION, "raise TPM quota, or shed traffic?"),
            ("Njord", "Forseti", TurnKind.ANSWER, "quota raise is cheapest for the SLA window"),
            ("Forseti", "Var", TurnKind.HANDOFF, "propose TPM increase; requesting approval"),
            ("Var", "Thor", TurnKind.HANDOFF, "approved"),
        ),
        rca="Traffic burst exceeded deployment TPM; capacity raised to restore headroom",
    ),
)


class SyntheticAgentActivityEmitter:
    """Publish idle heartbeat + periodic incident narratives to the SSE channel.

    Lifecycle mirrors the other synthetic emitters: :meth:`start` spawns one
    background task; :meth:`stop` cancels it and drains cleanly.
    """

    def __init__(
        self,
        *,
        sink: SseSink,
        channel: str,
        incident_interval_seconds: float = 12.0,
        beat_seconds: float = 1.4,
        seed: int | None = None,
    ) -> None:
        self._publisher = SseAgentActivityPublisher(sink=sink, channel=channel)
        self._interval = incident_interval_seconds
        self._beat = beat_seconds
        self._rng = random.Random(seed)  # noqa: S311 - dev emitter narrative, not cryptographic
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name="fdai.agents.synthetic-emitter"
        )

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        try:
            await self._heartbeat()
            while self._running:
                await asyncio.sleep(self._interval)
                if not self._running:
                    break
                await self._run_incident(self._rng.choice(_SCENARIOS))
                await self._heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a dev emitter must never crash the app
            _LOGGER.warning("synthetic_agent_emitter_failed", exc_info=True)

    async def _heartbeat(self) -> None:
        """Reset every agent to its resting state (sensing agents watch)."""

        for agent in _ALL_AGENTS:
            state = AgentState.WATCHING if agent in _SENSING else AgentState.IDLE
            await self._publisher.publish(AgentStateEvent(agent=agent, state=state, ts=_now()))

    async def _state(self, agent: str, state: AgentState, correlation_id: str) -> None:
        await self._publisher.publish(
            AgentStateEvent(
                agent=agent,
                state=state,
                ts=_now(),
                correlation_id=correlation_id,
                detail=_STATE_DETAIL.get(state),
            )
        )
        await asyncio.sleep(self._beat)

    async def _run_incident(self, scenario: _Scenario) -> None:
        correlation_id = f"incident-{uuid4().hex[:10]}"
        ticket_id = f"FDAI-{self._rng.randint(1000, 9999)}"

        # 1. Detection: the sensing agent moves watching -> collecting.
        await self._state(scenario.detector, AgentState.COLLECTING, correlation_id)

        # 2. Saga opens the ticket.
        await self._publisher.publish(
            IncidentTicketEvent(
                ticket_id=ticket_id,
                correlation_id=correlation_id,
                status=TicketStatus.OPEN,
                title=scenario.title,
                severity=scenario.severity,
                involved_agents=scenario.involved,
                ts=_now(),
            )
        )
        await self._state("Saga", AgentState.AUDITING, correlation_id)

        # 3. Forseti analyses; the A2A conversation drives the collaboration.
        await self._state("Forseti", AgentState.ANALYZING, correlation_id)
        for from_agent, to_agent, kind, text in scenario.turns:
            await self._publisher.publish(
                ConversationTurnEvent(
                    correlation_id=correlation_id,
                    from_agent=from_agent,
                    to_agent=to_agent,
                    kind=kind,
                    text=text,
                    ts=_now(),
                )
            )
            # Light up the addressed agent as it engages.
            if to_agent == "Var":
                await self._state("Var", AgentState.APPROVING, correlation_id)
            elif to_agent == "Thor":
                await self._state("Thor", AgentState.EXECUTING, correlation_id)
            else:
                await asyncio.sleep(self._beat)

        # 4. Ticket advances with the RCA.
        await self._publisher.publish(
            IncidentTicketEvent(
                ticket_id=ticket_id,
                correlation_id=correlation_id,
                status=TicketStatus.INVESTIGATING,
                title=scenario.title,
                severity=scenario.severity,
                involved_agents=scenario.involved,
                ts=_now(),
                rca=scenario.rca,
            )
        )

        # 5. Saga records the outcome and resolves the ticket.
        await self._state("Saga", AgentState.AUDITING, correlation_id)
        await self._publisher.publish(
            IncidentTicketEvent(
                ticket_id=ticket_id,
                correlation_id=correlation_id,
                status=TicketStatus.RESOLVED,
                title=scenario.title,
                severity=scenario.severity,
                involved_agents=scenario.involved,
                ts=_now(),
                rca=scenario.rca,
            )
        )


__all__ = ["SyntheticAgentActivityEmitter"]
