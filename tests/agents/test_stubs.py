"""Smoke test: every pantheon agent instantiates and produces the right spec.

Wave 1 stubs implement no behavior beyond returning a "not yet
implemented" abstain payload on their conversational port. This test
ensures the 15 concrete classes wire correctly to the registry and
that the conversational-port default is honest.
"""

from __future__ import annotations

import asyncio

from fdai.agents import (
    HARD_DEPENDENCY_AGENTS,
    LLM_HOT_PATH_ALLOWLIST,
    PANTHEON_NAMES,
    instantiate_pantheon,
    load_pantheon,
)


def test_all_fifteen_stubs_instantiate() -> None:
    agents = instantiate_pantheon()
    assert set(agents.keys()) == PANTHEON_NAMES
    for name, agent in agents.items():
        assert agent.spec.name == name


def test_stub_health_returns_stub_status() -> None:
    for agent in instantiate_pantheon().values():
        health = agent.health()
        assert health["agent"] == agent.spec.name
        # Most agents still return the base stub; agents with real state
        # (Thor / Huginn) override to "ok". Either way health carries an
        # agent name + a status.
        assert health["status"] in {"stub", "ok"}


def test_stub_conversation_returns_not_yet_implemented_abstain() -> None:
    for agent in instantiate_pantheon().values():
        result = asyncio.run(agent.on_conversation_turn("hello", {}))
        assert result["primary_agent"] == agent.spec.name
        assert result["answer"] is None
        assert result["abstain_reason"] == "not_yet_implemented"


def test_stub_typed_handler_is_a_noop() -> None:
    # Wave 1 typed handler is a no-op; asserting it does not raise and
    # returns None keeps the contract honest.
    for agent in instantiate_pantheon().values():
        result = asyncio.run(agent.on_typed_message("object.event", {}))
        assert result is None


def test_hard_dependencies_have_concrete_classes() -> None:
    agents = instantiate_pantheon()
    for name in HARD_DEPENDENCY_AGENTS:
        assert name in agents, f"hard-dependency agent {name!r} missing"


def test_hot_path_llm_allowlist_have_concrete_classes() -> None:
    agents = instantiate_pantheon()
    for name in LLM_HOT_PATH_ALLOWLIST:
        assert name in agents, f"LLM-hot-path agent {name!r} missing"


def test_registry_owner_lookups_match_instantiated_specs() -> None:
    reg = load_pantheon()
    agents = instantiate_pantheon()
    for name, agent in agents.items():
        for obj_type in agent.spec.owns:
            assert reg.owner_of_object_type(obj_type) == name
