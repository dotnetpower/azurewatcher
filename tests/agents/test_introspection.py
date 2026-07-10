"""Unit tests for the conversational-port introspection primitives."""

from __future__ import annotations

import asyncio

from fdai.agents.base import Agent
from fdai.agents.introspection import (
    capability_facts,
    capability_sentence,
    is_action_intent,
    mentioned,
)
from fdai.agents.pantheon import _MUNINN, _NJORD, _SAGA


class TestActionIntentGuard:
    """agent-pantheon.md 7.7: the port describes actions, never runs them."""

    def test_interrogatives_are_not_action_intent(self) -> None:
        for question in (
            "what is the cost of rg-abc",
            "why was this action denied",
            "who executed correlation c-1",
            "show me the audit log",
            "list pending approvals",
            "how much capacity is left",
        ):
            assert is_action_intent(question) is False

    def test_leading_command_verbs_are_action_intent(self) -> None:
        for question in (
            "restart vm-1",
            "delete rg-abc",
            "scale the cluster up",
            "failover to secondary",
            "approve correlation c-1",
        ):
            assert is_action_intent(question) is True

    def test_polite_prefix_is_stripped_before_the_verb(self) -> None:
        assert is_action_intent("please restart vm-1") is True
        assert is_action_intent("can you delete rg-abc") is True
        assert is_action_intent("could you tell me the cost") is False

    def test_empty_question_is_not_action_intent(self) -> None:
        assert is_action_intent("") is False
        assert is_action_intent("???") is False


class TestMentioned:
    def test_matches_named_candidate_tokens(self) -> None:
        assert mentioned("cost for rg-abc please", ["rg-abc", "rg-xyz"]) == ["rg-abc"]

    def test_is_case_insensitive(self) -> None:
        assert mentioned("what about RG-ABC", ["rg-abc"]) == ["rg-abc"]

    def test_preserves_candidate_order(self) -> None:
        assert mentioned("a and b", ["b", "a"]) == ["b", "a"]

    def test_no_match_returns_empty(self) -> None:
        assert mentioned("nothing relevant here", ["rg-abc"]) == []


class TestCapability:
    def test_capability_facts_mirror_the_spec(self) -> None:
        facts = capability_facts(_NJORD)
        assert facts["agent"] == "Njord"
        assert facts["layer"] == "domain"
        assert facts["owns"] == list(_NJORD.owns)
        assert facts["question_domains"] == list(_NJORD.question_domains)

    def test_capability_sentence_names_the_agent(self) -> None:
        sentence = capability_sentence(_SAGA)
        assert "Saga" in sentence
        assert "governance" in sentence


class TestBaseIntrospect:
    """The base conversational port answers a spec-grounded self-description."""

    def test_base_introspect_falls_back_to_capability(self) -> None:
        agent = Agent(spec=_MUNINN)
        result = asyncio.run(agent.introspect("what can you do", {}))
        assert result.answer is not None
        assert "Muninn" in result.answer
        assert result.abstain_reason is None
        assert result.facts["agent"] == "Muninn"
        assert result.facts["owns"] == list(_MUNINN.owns)

