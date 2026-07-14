"""Cross-language parity: the deck's action-intent guard MUST mirror the server.

The command deck (``console/src/deck/action-intent.ts``) decides client-side
whether an operator turn is a mutation command (route to ``POST /chat/action``)
or a question (stay with the read-only narrator). That decision MUST match the
authoritative server guard
:func:`fdai.agents._framework.introspection.is_action_intent`; a drift would
misroute a question to the action endpoint (or, worse, let a command slip to the
narrator). The two guards deliberately duplicate four small token sets - this
test pins them so a change on one side that is not mirrored on the other fails
CI instead of silently diverging (critique #6 / #7 of the disallowed-request
path review).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fdai.agents._framework.introspection import (
    _ACTION_VERBS,
    _AMBIGUOUS_ACTION_VERBS,
    _FILLER_PREFIX,
    _QUESTION_MARKERS,
)

_DECK_FILE = Path(__file__).resolve().parents[2] / "console" / "src" / "deck" / "action-intent.ts"


def _extract_set(source: str, const_name: str) -> frozenset[str]:
    """Return the string literals inside ``const <const_name> ... new Set([...])``.

    Deterministic, dependency-free parse: locate the named ``new Set([`` block,
    then collect every single/double-quoted token up to the closing ``])``.
    """
    marker = re.search(
        rf"{re.escape(const_name)}\s*:\s*ReadonlySet<string>\s*=\s*new Set\(\[",
        source,
    )
    if marker is None:
        raise AssertionError(
            f"could not find `const {const_name}: ReadonlySet<string> = new Set([`"
        )
    start = marker.end()
    end = source.index("])", start)
    body = source[start:end]
    return frozenset(re.findall(r"""["']([^"']+)["']""", body))


@pytest.fixture(scope="module")
def deck_source() -> str:
    if not _DECK_FILE.exists():
        pytest.skip(f"deck action-intent source not present: {_DECK_FILE}")
    return _DECK_FILE.read_text(encoding="utf-8")


def test_action_verbs_match(deck_source: str) -> None:
    assert _extract_set(deck_source, "ACTION_VERBS") == frozenset(_ACTION_VERBS)


def test_filler_prefix_matches(deck_source: str) -> None:
    assert _extract_set(deck_source, "FILLER") == frozenset(_FILLER_PREFIX)


def test_ambiguous_action_verbs_match(deck_source: str) -> None:
    assert _extract_set(deck_source, "AMBIGUOUS_ACTION_VERBS") == frozenset(_AMBIGUOUS_ACTION_VERBS)


def test_question_markers_match(deck_source: str) -> None:
    assert _extract_set(deck_source, "QUESTION_MARKERS") == frozenset(_QUESTION_MARKERS)


def test_ambiguous_is_subset_of_action_verbs(deck_source: str) -> None:
    # Server invariant mirrored: every ambiguous verb is also a command verb, so
    # an imperative phrasing still maps.
    ambiguous = _extract_set(deck_source, "AMBIGUOUS_ACTION_VERBS")
    assert ambiguous <= _extract_set(deck_source, "ACTION_VERBS")
