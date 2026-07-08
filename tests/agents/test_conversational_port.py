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
