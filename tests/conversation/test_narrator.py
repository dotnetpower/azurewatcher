"""Narrator translator + coordinator hook tests (Chunk 27)."""

from __future__ import annotations

import pytest

from fdai.core.conversation.narrator import (
    DeterministicKeywordNarrator,
    ToolSchema,
    default_tool_schemas,
    format_prompt_tool_list,
)


class TestDeterministicKeywordNarrator:
    def test_english_verb_keyword_returns_verb(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="please list_rules for storage",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "explore_catalog"
        )

    def test_korean_keyword_returns_english_verb(self) -> None:
        n = DeterministicKeywordNarrator()
        # Compound Korean phrase for "resource group list" MUST map to
        # `query_inventory resource-group` (longer keyword wins over
        # the plain "resource list" prefix).
        assert (
            n.translate(
                utterance="\ub9ac\uc18c\uc2a4 \uadf8\ub8f9 \ubaa9\ub85d",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_inventory resource-group"
        )

    def test_korean_audit_keyword_maps_to_query_audit(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="\ucd5c\uadfc \uac10\uc0ac \ub85c\uadf8 \ubcf4\uc5ec\uc918",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_audit"
        )

    def test_longer_keyword_wins_over_shorter(self) -> None:
        n = DeterministicKeywordNarrator()
        # Same principle stated positively: when a longer keyword is a
        # superstring of a shorter one, the narrator MUST return the
        # longer one so we never emit a narrower verb than intended.
        assert (
            n.translate(
                utterance=(
                    "\ud504\ub85c\uc81d\ud2b8 "
                    "\ub9ac\uc18c\uc2a4 \uadf8\ub8f9 \ubaa9\ub85d "
                    "\uc785\ub2c8\ub2e4"
                ),
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_inventory resource-group"
        )

    def test_no_keyword_match_returns_none(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="hello there, what do you think?",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_empty_utterance_returns_none(self) -> None:
        n = DeterministicKeywordNarrator()
        assert (
            n.translate(
                utterance="   ",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_english_keyword_respects_word_boundaries(self) -> None:
        n = DeterministicKeywordNarrator()
        # `list_rules` MUST NOT trigger on `list_rules_deprecated`.
        result = n.translate(
            utterance="list_rules_deprecated please",
            tools=default_tool_schemas(),
            principal_role="reader",
        )
        assert result is None

    def test_empty_table_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 1 keyword"):
            DeterministicKeywordNarrator(table=[])

    def test_custom_table_supersedes_default(self) -> None:
        n = DeterministicKeywordNarrator(table=[("magic", "explore_catalog")])
        assert (
            n.translate(
                utterance="magic please",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "explore_catalog"
        )


class TestToolSchemaDefaults:
    def test_default_schemas_cover_every_known_verb(self) -> None:
        """Every shipped verb has a schema entry (drift-guard).

        A new verb in coordinator._VERB_PATTERNS MUST also land in
        `default_tool_schemas()` or the narrator prompt is stale.
        """
        from fdai.core.conversation.coordinator import _VERB_PATTERNS

        # tool_name is the target verb we route to; take the unique set.
        coordinator_tool_names = {tool for _pattern, tool in _VERB_PATTERNS}
        schema_tool_names = {s.tool_name for s in default_tool_schemas()}
        missing = coordinator_tool_names - schema_tool_names
        assert not missing, f"coordinator verbs missing from default_tool_schemas(): {missing}"

    def test_reader_prompt_hides_write_tools(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="reader")
        # Reader gets Reader-floor tools + activate_break_glass (Reader
        # floor per chat invariant 7). approve_hil / list_hil (Approver)
        # MUST NOT appear.
        assert "approve_hil" not in rendered
        assert "list_hil" not in rendered
        assert "explore_catalog" in rendered

    def test_approver_prompt_includes_write_tools(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="approver")
        assert "approve_hil" in rendered
        assert "list_hil" in rendered
        assert "explore_catalog" in rendered

    def test_owner_prompt_includes_everything(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="owner")
        for verb in ("explore_catalog", "approve_hil", "run_runbook", "activate_break_glass"):
            assert verb in rendered

    def test_unknown_role_defaults_to_reader_visibility(self) -> None:
        rendered = format_prompt_tool_list(default_tool_schemas(), principal_role="unknown-role")
        assert "approve_hil" not in rendered
        assert "explore_catalog" in rendered

    def test_tool_schema_is_frozen(self) -> None:
        schema = ToolSchema(
            verb="v",
            tool_name="t",
            argument_hint="",
            summary="s",
            rbac_floor="reader",
            side_effect_class="read",
        )
        with pytest.raises(AttributeError):
            schema.verb = "hijack"  # type: ignore[misc]


class TestCoordinatorNarratorHook:
    def _tools(self):  # type: ignore[no-untyped-def]
        from fdai.core.conversation import ExploreCatalogTool

        return [ExploreCatalogTool(rules=[], action_types=[])]

    def _session(self, role: str = "reader"):  # type: ignore[no-untyped-def]
        from fdai.core.conversation import (
            ConversationSession,
            Principal,
            Role,
        )

        return ConversationSession(
            session_id="s-1",
            principal=Principal(id="p-1", role=Role(role)),
            channel_id="cli",
            turns=[],
        )

    def test_no_narrator_leaves_regex_behaviour_intact(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
        )

        coord = ConversationCoordinator(tools=self._tools())
        result = coord.handle_turn(session=self._session(), message="\ubb50\uac00 \uc788\ub098")
        assert isinstance(result, AbstainResult)

    def test_narrator_hits_when_regex_misses(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            DeterministicKeywordNarrator,
            ToolResult,
            default_tool_schemas,
        )

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=DeterministicKeywordNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        # Korean utterance no regex would match; narrator translates it
        # via the "\uce74\ud0c8\ub85c\uadf8" keyword to `explore_catalog`, coordinator
        # re-runs the regex, ExploreCatalogTool fires (tool call happens
        # regardless of whether the empty query succeeds - the point is
        # the narrator routed a Korean prompt into a tool dispatch).
        result = coord.handle_turn(
            session=self._session(),
            message="\uce74\ud0c8\ub85c\uadf8\uc5d0\uc11c \ubcf4\uc5ec\uc918",
        )
        # Coordinator DID reach a tool (any status), not an abstain.
        assert isinstance(result, ToolResult)

    def test_narrator_returning_none_falls_through_to_abstain(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
        )

        class _NullNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                return None

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=_NullNarrator(),
            narrator_tool_schemas=[],
        )
        result = coord.handle_turn(
            session=self._session(),
            message="\uc774\uac74 \uc544\ubb34\uac83\ub3c4 \uc548 \ub9de\ub294 \ub9d0",
        )
        assert isinstance(result, AbstainResult)

    def test_narrator_error_falls_through_to_abstain(self) -> None:
        from fdai.core.conversation import (
            AbstainResult,
            ConversationCoordinator,
        )

        class _BoomNarrator:
            def translate(self, *, utterance, tools, principal_role):  # type: ignore[no-untyped-def]
                raise RuntimeError("network down")

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=_BoomNarrator(),
            narrator_tool_schemas=[],
        )
        result = coord.handle_turn(
            session=self._session(), message="\uc544\ubb34\ub7f0 \uc785\ub825"
        )
        assert isinstance(result, AbstainResult)

    def test_narrator_translation_logged_as_system_turn(self) -> None:
        from fdai.core.conversation import (
            ConversationCoordinator,
            DeterministicKeywordNarrator,
            default_tool_schemas,
        )

        coord = ConversationCoordinator(
            tools=self._tools(),
            narrator=DeterministicKeywordNarrator(),
            narrator_tool_schemas=default_tool_schemas(),
        )
        session = self._session()
        coord.handle_turn(
            session=session,
            message="\uce74\ud0c8\ub85c\uadf8\uc5d0\uc11c \ubcf4\uc5ec\uc918",
        )
        # Should have a system turn recording the narrator translation.
        system_turns = [t.content for t in session.turns if t.direction == "system"]
        assert any("narrator translated to:" in c for c in system_turns)
