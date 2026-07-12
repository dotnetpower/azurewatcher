"""Real-path projection: control-loop ``StageEvent`` -> agent-activity events.

The ``Now > Agents`` panel is fed by a synthetic emitter in dev
(:mod:`fdai.delivery.read_api.streaming.agent_activity_emitter`). This module
is the **real-path** counterpart: it deterministically translates the stage
frames a real :class:`~fdai.core.control_loop.ControlLoop` emits (ingest ->
route -> verify -> gate -> execute -> audit) into the agent-centric
``agent.state`` / ``incident.ticket`` events the panel renders, so the
constellation lights up from the actual pipeline rather than a canned
narrative.

Design
------

- **Pure reducer, no I/O.** :func:`project_stage` takes the prior
  :class:`AgentActivityProjection` plus one :class:`StageEvent` and returns a
  new projection and the events to publish. The relay
  (:mod:`fdai.delivery.read_api.streaming.agent_activity_relay`) owns the I/O;
  this stays trivially unit-testable.
- **Single source of truth for stage -> agent.** :data:`STAGE_AGENT` and
  :func:`stage_agent` are the one mapping the live cockpit and this projection
  share, so the two agent attributions never drift.
- **No fabricated conversation.** A deterministic pipeline has no real
  agent-to-agent dialogue, so this projection emits only ``agent.state`` and
  ``incident.ticket`` - never a ``conversation.turn`` it cannot ground. The
  A2A conversation stays with the synthetic/demo emitter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentState,
    AgentStateEvent,
    IncidentTicketEvent,
    TicketStatus,
)
from fdai.shared.providers.stage_publisher import StageEvent, StageName, StagePhase

# The one stage -> owning pantheon agent map, shared with the live cockpit's
# attribution (fdai.delivery.read_api.streaming.live_control_loop imports it).
# Gate frames split by decision: a HIL verdict is Var's approval, everything
# else is Forseti's judgment (see :func:`stage_agent`).
STAGE_AGENT: dict[StageName, str] = {
    StageName.INGEST: "Huginn",
    StageName.ROUTE: "Heimdall",
    StageName.VERIFY: "Forseti",
    StageName.GATE: "Forseti",
    StageName.EXECUTE: "Thor",
    StageName.AUDIT: "Saga",
}

# The active status ring each stage's owning agent shows while working it.
_STAGE_ACTIVE_STATE: dict[StageName, AgentState] = {
    StageName.INGEST: AgentState.COLLECTING,
    StageName.ROUTE: AgentState.ANALYZING,
    StageName.VERIFY: AgentState.ANALYZING,
    StageName.GATE: AgentState.DECIDING,
    StageName.EXECUTE: AgentState.EXECUTING,
    StageName.AUDIT: AgentState.AUDITING,
}

_UNKNOWN_AGENT = "unknown"
_DEFAULT_SEVERITY = "info"


def stage_agent(stage: StageName, detail: Mapping[str, object]) -> str:
    """Return the pantheon agent that owns ``stage``.

    A ``gate`` frame whose ``gate_decision`` is ``hil`` is Var's approval
    (human-in-the-loop), not Forseti's judgment; every other stage maps
    through :data:`STAGE_AGENT`. An unmapped stage returns ``"unknown"``.
    """
    if stage is StageName.GATE and str(detail.get("gate_decision")) == "hil":
        return "Var"
    return STAGE_AGENT.get(stage, _UNKNOWN_AGENT)


def _active_state(stage: StageName, agent: str) -> AgentState:
    if agent == "Var":
        return AgentState.APPROVING
    return _STAGE_ACTIVE_STATE.get(stage, AgentState.WATCHING)


@dataclass(frozen=True, slots=True)
class IncidentProjection:
    """The accumulated view of one incident (keyed by ``correlation_id``)."""

    ticket_id: str
    correlation_id: str
    status: TicketStatus
    title: str
    severity: str
    involved: tuple[str, ...] = ()

    def with_agent(self, agent: str) -> IncidentProjection:
        if agent == _UNKNOWN_AGENT or agent in self.involved:
            return self
        return replace(self, involved=(*self.involved, agent))


@dataclass(frozen=True, slots=True)
class AgentActivityProjection:
    """Immutable accumulated state across stage frames.

    Keyed by ``correlation_id`` so concurrent incidents never cross-talk.
    Bounded in the relay, not here - this stays a pure value.
    """

    incidents: Mapping[str, IncidentProjection] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """The next projection plus the events to publish, in order."""

    projection: AgentActivityProjection
    events: Sequence[AgentStateEvent | IncidentTicketEvent]


def _ticket_id(correlation_id: str) -> str:
    return f"INC-{correlation_id}"


def _incident_title(event: StageEvent) -> str:
    rule = event.detail.get("rule")
    if isinstance(rule, str) and rule:
        return f"Rule {rule}"
    return f"Event {event.event_id}"


def _incident_severity(event: StageEvent) -> str:
    severity = event.detail.get("severity")
    if isinstance(severity, str) and severity:
        return severity
    return _DEFAULT_SEVERITY


def project_stage(projection: AgentActivityProjection, event: StageEvent) -> ProjectionResult:
    """Fold one :class:`StageEvent` into ``projection``.

    Emits, in order:

    1. an ``incident.ticket`` when the ticket is first opened or changes
       status (``open`` on first sighting, ``investigating`` at verify/gate,
       ``resolved`` when the audit stage completes);
    2. an ``agent.state`` for the stage's owning agent - the active ring for
       any successful stage frame (the agent performed that stage), and
       ``idle`` only on a ``failed`` frame. The real ControlLoop reports a
       stage as a single ``done`` frame, so ``done`` shows the active ring
       (the pantheon lit up with what each agent just did), not ``idle``.

    Deterministic and side-effect-free; ``ts`` is taken from the event so a
    replay reproduces identical output.
    """
    ts = event.ts.isoformat()
    agent = stage_agent(event.stage, event.detail)
    correlation_id = event.correlation_id

    incidents = dict(projection.incidents)
    ticket_events: list[IncidentTicketEvent] = []

    prior = incidents.get(correlation_id)
    if prior is None:
        incident = IncidentProjection(
            ticket_id=_ticket_id(correlation_id),
            correlation_id=correlation_id,
            status=TicketStatus.OPEN,
            title=_incident_title(event),
            severity=_incident_severity(event),
        ).with_agent(agent)
        incidents[correlation_id] = incident
        ticket_events.append(_ticket_event(incident, ts))
    else:
        incident = replace(
            prior.with_agent(agent),
            status=_next_status(prior.status, event),
        )
        incidents[correlation_id] = incident
        # Emit a ticket frame whenever the incident changed - the console
        # populates an incident's `involved` set only from ticket frames, so a
        # newly-engaged agent MUST ride a ticket event or it never lights up.
        if incident != prior:
            ticket_events.append(_ticket_event(incident, ts))

    active = event.phase is not StagePhase.FAILED
    state = _active_state(event.stage, agent) if active else AgentState.IDLE
    agent_event = AgentStateEvent(
        agent=agent,
        state=state,
        ts=ts,
        correlation_id=correlation_id,
        detail=_state_detail(event),
    )

    events: list[AgentStateEvent | IncidentTicketEvent] = [*ticket_events, agent_event]
    return ProjectionResult(projection=AgentActivityProjection(incidents=incidents), events=events)


def _next_status(current: TicketStatus, event: StageEvent) -> TicketStatus:
    if current is TicketStatus.RESOLVED:
        return current
    if event.stage is StageName.AUDIT and event.phase is StagePhase.DONE:
        return TicketStatus.RESOLVED
    if event.stage in (StageName.VERIFY, StageName.GATE, StageName.EXECUTE):
        return TicketStatus.INVESTIGATING
    return current


def _ticket_event(incident: IncidentProjection, ts: str) -> IncidentTicketEvent:
    return IncidentTicketEvent(
        ticket_id=incident.ticket_id,
        correlation_id=incident.correlation_id,
        status=incident.status,
        title=incident.title,
        severity=incident.severity,
        involved_agents=incident.involved,
        ts=ts,
    )


def _state_detail(event: StageEvent) -> str | None:
    if event.error is not None:
        return f"{event.stage.value} failed: {event.error}"
    tier = event.detail.get("tier")
    if isinstance(tier, str) and tier:
        return f"{event.stage.value} ({tier})"
    return event.stage.value


__all__ = [
    "STAGE_AGENT",
    "AgentActivityProjection",
    "IncidentProjection",
    "ProjectionResult",
    "project_stage",
    "stage_agent",
]
