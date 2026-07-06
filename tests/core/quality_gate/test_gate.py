"""QualityGate - outcome + property invariants."""

from __future__ import annotations

import pytest

from aiopspilot.core.quality_gate import (
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
)
from aiopspilot.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    MismatchCrossCheckModel,
    StaticVerifier,
)
from aiopspilot.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)


def _rule(rule_id: str) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="object-storage",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _candidate(
    *,
    action_type: str = "remediate.tag-add",
    cited: tuple[str, ...] = ("r.known",),
    confidence: dict[str, float] | None = None,
) -> QualityCandidate:
    signals: dict[str, float] = (
        {"retrieval": 0.9, "verifier_margin": 0.9} if confidence is None else confidence
    )
    return QualityCandidate(
        action_type=action_type,
        target_resource_ref="rid-1",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=cited,
        confidence_signals=signals,
    )


def _grounding(rule_ids: tuple[str, ...] = ("r.known",)) -> InMemoryGroundingSource:
    return InMemoryGroundingSource({rid: _rule(rid) for rid in rule_ids})


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_out_of_range_confidence_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="confidence_threshold"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(confidence_threshold=1.5),
        )


def test_zero_quorum_is_rejected() -> None:
    with pytest.raises(ValueError, match="require_cross_check_quorum"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(require_cross_check_quorum=0),
        )


def test_quorum_larger_than_models_is_rejected() -> None:
    with pytest.raises(ValueError, match="not enough cross-check models"):
        QualityGate(
            verifier=StaticVerifier(outcome=True),
            cross_check_models=(MatchTypeCrossCheckModel(),),
            grounding=_grounding(),
            config=QualityGateConfig(require_cross_check_quorum=3),
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eligible_when_all_gates_pass() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert decision.reasons == ()
    assert decision.grounded_rule_ids == ("r.known",)
    assert decision.aggregate_confidence > 0.7


# ---------------------------------------------------------------------------
# Verifier paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_deny_short_circuits() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=False),  # explicit deny
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DENY
    assert decision.reasons == ("verifier_rejected",)


@pytest.mark.asyncio
async def test_verifier_abstain_is_recorded_but_not_fatal_alone() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=None),  # abstain
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    # Abstain alone shifts outcome to ABSTAIN (a reason is recorded).
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert "verifier_abstained" in decision.reasons


# ---------------------------------------------------------------------------
# Grounding paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_cited_rule_flags_and_may_still_pass_when_others_ground() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(("r.known",)),
    )
    decision = await gate.evaluate(_candidate(cited=("r.known", "r.made-up")))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert any("unknown_cited_rule:r.made-up" in r for r in decision.reasons)
    assert "r.known" in decision.grounded_rule_ids


@pytest.mark.asyncio
async def test_no_grounded_citation_when_require_grounding_true() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(("r.known",)),
    )
    decision = await gate.evaluate(_candidate(cited=("r.other",)))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert "no_grounded_citation" in decision.reasons


@pytest.mark.asyncio
async def test_grounding_disabled_does_not_require_citations() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(("r.known",)),
        config=QualityGateConfig(require_grounding=False),
    )
    decision = await gate.evaluate(_candidate(cited=()))
    assert decision.outcome is QualityOutcome.ELIGIBLE


# ---------------------------------------------------------------------------
# Cross-check paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_check_disagreement_below_quorum_becomes_disagree() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE
    assert any("cross_check_below_quorum" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_cross_check_agreement_below_quorum_still_disagrees() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(),
            MismatchCrossCheckModel(),
            MismatchCrossCheckModel(),
        ),
        grounding=_grounding(),
        config=QualityGateConfig(require_cross_check_quorum=2),
    )
    decision = await gate.evaluate(_candidate())
    assert decision.outcome is QualityOutcome.DISAGREE


# ---------------------------------------------------------------------------
# Confidence threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_confidence_abstains_even_when_other_gates_pass() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(
        _candidate(confidence={"retrieval": 0.3, "verifier_margin": 0.3})
    )
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert any("confidence=0.30" in r for r in decision.reasons)


@pytest.mark.asyncio
async def test_aggregate_confidence_zero_when_no_signals() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate(confidence={}))
    assert decision.outcome is QualityOutcome.ABSTAIN
    assert decision.aggregate_confidence == 0.0


def test_candidate_aggregate_ignores_non_numeric_signals() -> None:
    candidate = QualityCandidate(
        action_type="a",
        target_resource_ref="r",
        params={},
        cited_rule_ids=(),
        confidence_signals={"good": 0.8, "bad": "not-a-number"},  # type: ignore[dict-item]
    )
    assert candidate.aggregate_confidence == 0.8


def test_candidate_aggregate_excludes_bool_values() -> None:
    """`bool` subtypes `int`; letting it slip through would silently
    inflate the aggregate to 1.0. Ensure it is excluded."""
    candidate = QualityCandidate(
        action_type="a",
        target_resource_ref="r",
        params={},
        cited_rule_ids=(),
        confidence_signals={"passed": True, "score": 0.6},
    )
    # Only 0.6 counts; True → excluded.
    assert candidate.aggregate_confidence == 0.6


def test_candidate_aggregate_bool_only_returns_zero() -> None:
    candidate = QualityCandidate(
        action_type="a",
        target_resource_ref="r",
        params={},
        cited_rule_ids=(),
        confidence_signals={"passed": True, "failed": False},
    )
    assert candidate.aggregate_confidence == 0.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_decision_is_immutable() -> None:
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel()),
        grounding=_grounding(),
    )
    decision = await gate.evaluate(_candidate())
    assert isinstance(decision, QualityDecision)
    with pytest.raises((AttributeError, TypeError)):
        decision.outcome = QualityOutcome.DENY  # type: ignore[misc]
