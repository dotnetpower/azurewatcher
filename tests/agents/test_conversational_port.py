"""Conversational-port wiring: PantheonRuntime.ask routes through Bragi."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents.runtime import PantheonRuntime
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_RAW_TOPIC = "fdai.events"


def _runtime(**kwargs: object) -> PantheonRuntime:
    return PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic=_RAW_TOPIC, **kwargs)


def test_ask_routes_to_primary_agent() -> None:
    runtime = _runtime()
    turn = asyncio.run(
        runtime.ask(session_id="s1", user_id="u1", question="what is the action status")
    )
    assert turn is not None
    assert turn.primary_agent == "Thor"  # Thor owns question_domain 'action_status'
    assert turn.answer["primary_agent"] == "Thor"


def test_ask_tracks_session_turns() -> None:
    runtime = _runtime()
    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="action status"))
    turn2 = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="approval backlog"))
    assert turn2 is not None
    assert turn2.turn_index == 1


def test_ask_enforces_user_ownership() -> None:
    runtime = _runtime()
    asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="action status"))
    with pytest.raises(PermissionError):
        asyncio.run(runtime.ask(session_id="s1", user_id="u2", question="action status"))


def test_conversational_port_present_in_health() -> None:
    runtime = _runtime()
    assert runtime.health()["conversational_port"] is True


def test_conversational_port_absent_when_bragi_disabled() -> None:
    runtime = _runtime(disabled_agents=frozenset({"Bragi"}))
    assert runtime.health()["conversational_port"] is False
    result = asyncio.run(runtime.ask(session_id="s", user_id="u", question="action status"))
    assert result is None


def test_ask_handoff_when_no_route() -> None:
    runtime = _runtime()
    turn = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="zzzz qqqq wxyz"))
    assert turn is not None
    assert turn.primary_agent is None
    assert turn.answer["handoff_needed"] is True


def test_ask_answers_from_owned_state_not_stub() -> None:
    # The routed agent answers from its owned data (grounded), not a bare
    # not-implemented abstain.
    runtime = _runtime()
    turn = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="cost breakdown"))
    assert turn is not None
    assert turn.primary_agent == "Njord"
    assert turn.answer["answer"] is not None
    assert turn.answer["abstain_reason"] is None
    assert turn.answer["facts"]["agent"] == "Njord"


def test_ask_refuses_action_intent_and_routes_to_typed_pipeline() -> None:
    # A command ("restart ...") is not answered or executed by the
    # conversational port; Bragi translates it into a typed ActionProposal and
    # submits it to the pipeline via Huginn (agent-pantheon.md 7.7). The full
    # pantheon here wires the proposal sink, so the request is SUBMITTED, not
    # merely signalled - and the port never executes it.
    runtime = _runtime()
    turn = asyncio.run(runtime.ask(session_id="s1", user_id="u1", question="restart svc-1 now"))
    assert turn is not None
    assert turn.answer["answer"] is None  # the port did not answer/execute
    assert turn.answer["requires_typed_pipeline"] is True
    assert turn.answer["submitted"] is True
    assert turn.answer["action_type"] == "ops.restart-service"
    assert turn.answer["correlation_id"].startswith("conv-")
    assert turn.answer["initiator_principal"] == "u1"


# ---------------------------------------------------------------------------
# Agent-to-agent (A2A) introspection (agent-pantheon.md 6.2)
# ---------------------------------------------------------------------------


def test_introspect_a2a_answers_from_target_agent() -> None:
    runtime = _runtime()
    result = asyncio.run(
        runtime.introspect("Njord", "what is the cost breakdown", requester="Forseti")
    )
    assert result is not None
    assert result["primary_agent"] == "Njord"
    assert result["answer"] is not None
    assert result["requester"] == "Forseti"


def test_introspect_a2a_threads_correlation_trace() -> None:
    runtime = _runtime()
    result = asyncio.run(
        runtime.introspect(
            "Saga",
            "who executed correlation c-1",
            requester="Odin",
            correlation_id="c-1",
        )
    )
    assert result is not None
    assert result["trace_ref"] == "c-1"
    assert result["requester"] == "Odin"


def test_introspect_a2a_refuses_action_intent() -> None:
    runtime = _runtime()
    result = asyncio.run(runtime.introspect("Thor", "restart vm-1", requester="Odin"))
    assert result is not None
    assert result["abstain_reason"] == "requires_typed_pipeline"
    assert result["requester"] == "Odin"


def test_introspect_a2a_unknown_agent_abstains() -> None:
    runtime = _runtime()
    result = asyncio.run(runtime.introspect("Bragi", "anything", requester="Odin"))
    # Bragi does not register itself as a responder.
    assert result is not None
    assert result["abstain_reason"] == "responder_not_registered"


def test_introspect_a2a_none_when_bragi_disabled() -> None:
    runtime = _runtime(disabled_agents=frozenset({"Bragi"}))
    result = asyncio.run(runtime.introspect("Njord", "cost", requester="Forseti"))
    assert result is None
