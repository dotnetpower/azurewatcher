"""Deterministic handover-document extractor tests."""

from __future__ import annotations

from fdai.core.stewardship.handover_bootstrap import (
    DeterministicExtractor,
    DocumentKind,
    HandoverDocument,
    MappingSource,
)
from fdai.core.stewardship.handover_bootstrap.agent_domains import (
    AGENT_DOMAINS,
    match_agents,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.core.stewardship.names import AGENT_NAME_SET


def _doc(text: str, *, kind: DocumentKind = DocumentKind.RACI) -> HandoverDocument:
    return HandoverDocument(doc_id="doc-1", kind=kind, text=text)


def test_domain_catalog_covers_exactly_the_pantheon() -> None:
    assert frozenset(AGENT_DOMAINS) == AGENT_NAME_SET


def test_match_agents_returns_longest_keyword_hit() -> None:
    hits = match_agents("our cost governance program tracks spend")
    agents = {name for name, _spec, _kw in hits}
    assert "Njord" in agents
    njord = next(kw for name, _spec, kw in hits if name == "Njord")
    assert njord == "cost governance"


def test_extracts_grounded_accountable_owner() -> None:
    doc = _doc("Cost governance owner: Jane Kim is accountable for spend.")
    mappings = DeterministicExtractor().extract(doc)
    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.agent_name == "Njord"
    assert mapping.person.display_name == "Jane Kim"
    assert mapping.person.kind is StewardKind.USER
    assert mapping.responsibility is Responsibility.ACCOUNTABLE
    assert mapping.source is MappingSource.DETERMINISTIC
    assert mapping.grounded
    assert mapping.citations[0].doc_id == "doc-1"
    assert mapping.citations[0].line == 1
    assert mapping.confidence >= 0.9


def test_team_mention_is_a_group_subject_and_informed() -> None:
    doc = _doc("Monitoring dashboards - consulted: Platform Team")
    mappings = DeterministicExtractor().extract(doc)
    assert mappings
    mapping = mappings[0]
    assert mapping.agent_name == "Heimdall"
    assert mapping.person.kind is StewardKind.GROUP
    assert mapping.responsibility is Responsibility.INFORMED


def test_line_without_domain_keyword_yields_nothing() -> None:
    doc = _doc("Weekly sync every Monday at 10am with the whole crew.")
    assert DeterministicExtractor().extract(doc) == ()


def test_bare_name_without_explicit_cue_scores_lower() -> None:
    explicit = DeterministicExtractor().extract(
        _doc("Rollback owner: Alex Park handles failover.")
    )[0]
    bare = DeterministicExtractor().extract(_doc("Rollback and failover: Alex Park"))[0]
    assert explicit.confidence > bare.confidence
    assert explicit.agent_name == bare.agent_name == "Vidar"


def test_email_local_part_is_a_user_subject() -> None:
    doc = _doc("FinOps budget owned by jane.kim@example.com")
    mappings = DeterministicExtractor().extract(doc)
    assert mappings
    assert mappings[0].person.display_name == "jane.kim"
    assert mappings[0].person.kind is StewardKind.USER
