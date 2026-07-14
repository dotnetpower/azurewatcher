"""Pantheon-backed Command Deck delegation tests."""

from __future__ import annotations

import asyncio

from fdai.agents import PantheonRuntime
from fdai.delivery.read_api.routes.chat_agent_delegate import PantheonChatDelegate
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


def _delegate() -> PantheonChatDelegate:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )
    return PantheonChatDelegate(runtime)


def test_routes_question_to_owning_agent() -> None:
    result = asyncio.run(
        _delegate().delegate(
            prompt="cost breakdown",
            user_id="operator-1",
            session_id="conversation-1",
        )
    )

    assert result is not None
    assert result["primary_agent"] == "Njord"
    assert result["facts"]["agent"] == "Njord"


def test_same_client_session_is_isolated_between_users() -> None:
    delegate = _delegate()

    first = asyncio.run(
        delegate.delegate(
            prompt="cost breakdown",
            user_id="operator-1",
            session_id="shared",
        )
    )
    second = asyncio.run(
        delegate.delegate(
            prompt="cost breakdown",
            user_id="operator-2",
            session_id="shared",
        )
    )

    assert first is not None
    assert second is not None


def test_action_and_no_route_return_no_agent_evidence() -> None:
    delegate = _delegate()

    action = asyncio.run(
        delegate.delegate(
            prompt="restart svc-1",
            user_id="operator-1",
            session_id="conversation-1",
        )
    )
    unknown = asyncio.run(
        delegate.delegate(
            prompt="zzzz qqqq wxyz",
            user_id="operator-1",
            session_id="conversation-1",
        )
    )

    assert action is None
    assert unknown is None
