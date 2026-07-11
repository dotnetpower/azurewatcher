"""T2 reasoning tier orchestrator - propose + quality-gate.

Phase 2 T2 (see [`docs/roadmap/scope-expansion.md § 3.7`] and
[`architecture.instructions.md § LLM Quality Gate`]). Mirrors the T1 tier
structure: a small orchestrator over DI seams, no concrete LLM import in
``core/``.

Contract
--------

Given a novel / ambiguous :class:`Event` that T0 and T1 could not resolve, the
T2 tier asks an injected :class:`T2Proposer` (frontier-model backed in a fork)
for a :class:`~fdai.core.quality_gate.gate.QualityCandidate` - the ActionType +
params + cited rules it would emit. The candidate is then run through the
existing :class:`~fdai.core.quality_gate.gate.QualityGate` (mixed-model
cross-check + deterministic verifier + RAG grounding). The tier maps the gate's
outcome onto a tier decision the control loop routes to the risk-gate:

- gate ``ELIGIBLE`` -> :attr:`T2Outcome.PROPOSED` - the deterministic gate
  cleared the candidate; the risk-gate MAY consider auto-execution.
- gate ``ABSTAIN`` / ``DISAGREE`` -> :attr:`T2Outcome.ESCALATE` - hand off to
  HIL, never auto-resolve.
- gate ``DENY`` -> :attr:`T2Outcome.DENIED` - no execution.
- proposer returns ``None`` -> :attr:`T2Outcome.ABSTAIN` - nothing to gate.

Execution eligibility is granted by the deterministic gate, never by the
model's prose. The tier never executes; it returns a decision.

DI seams
--------

- :class:`T2Proposer` - turns an Event into a candidate action. Real backends
  (frontier LLMs behind the mixed-model cross-check) go in a fork; a test fake
  returns a preset candidate.
- :class:`QualityGateProtocol` - the quality gate. The concrete
  :class:`~fdai.core.quality_gate.gate.QualityGate` satisfies it structurally;
  tests inject a trivial fake to exercise the outcome mapping in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.quality_gate.gate import (
    QualityCandidate,
    QualityDecision,
    QualityOutcome,
)
from fdai.shared.contracts.models import Event


class T2Outcome(StrEnum):
    """Terminal outcome for one :meth:`T2Tier.evaluate` call."""

    PROPOSED = "proposed"
    """Quality gate cleared the candidate; eligible for the risk-gate."""

    ESCALATE = "escalate"
    """Gate abstained or the cross-check disagreed; route to HIL."""

    DENIED = "denied"
    """Verifier explicitly rejected the candidate; no execution."""

    ABSTAIN = "abstain"
    """The proposer produced no candidate; nothing to gate."""


@dataclass(frozen=True, slots=True)
class T2Decision:
    """Result of a T2 tier evaluation."""

    outcome: T2Outcome
    candidate: QualityCandidate | None
    quality_decision: QualityDecision | None
    reason: str

    @property
    def eligible_for_risk_gate(self) -> bool:
        """True only when the quality gate cleared the candidate."""
        return self.outcome is T2Outcome.PROPOSED


@runtime_checkable
class T2Proposer(Protocol):
    """Produces a quality-gate candidate for a novel/ambiguous event."""

    async def propose(self, *, event: Event) -> QualityCandidate | None:
        """Return a candidate action, or ``None`` to abstain.

        A fork's real proposer MUST populate
        :attr:`~fdai.core.quality_gate.gate.QualityCandidate.reasoning_trace`
        with the model's natural-language justification when the
        hallucination rubric leg is wired: the rubric scores that text
        for faithfulness, and a blank trace makes the rubric abstain
        (route to HIL) for lack of a scoring target. Leaving it empty is
        valid only when no rubric evaluator is bound.
        """
        ...


@runtime_checkable
class QualityGateProtocol(Protocol):
    """The quality gate seam the tier depends on (structural)."""

    async def evaluate(self, candidate: QualityCandidate) -> QualityDecision: ...


_OUTCOME_MAP = {
    QualityOutcome.ELIGIBLE: T2Outcome.PROPOSED,
    QualityOutcome.ABSTAIN: T2Outcome.ESCALATE,
    QualityOutcome.DISAGREE: T2Outcome.ESCALATE,
    QualityOutcome.DENY: T2Outcome.DENIED,
}


class T2Tier:
    """Frontier-model reasoning tier - propose, quality-gate, map."""

    __slots__ = ("_proposer", "_quality_gate")

    def __init__(
        self,
        *,
        proposer: T2Proposer,
        quality_gate: QualityGateProtocol,
    ) -> None:
        self._proposer = proposer
        self._quality_gate = quality_gate

    async def evaluate(self, *, event: Event) -> T2Decision:
        """Propose a candidate for ``event`` and gate it.

        Fail-closed: an abstaining proposer or any non-eligible gate outcome
        yields a non-executing decision. Only a gate ``ELIGIBLE`` verdict
        makes the candidate eligible for the risk-gate.
        """
        candidate = await self._proposer.propose(event=event)
        if candidate is None:
            return T2Decision(
                outcome=T2Outcome.ABSTAIN,
                candidate=None,
                quality_decision=None,
                reason="t2_proposer_abstained",
            )
        decision = await self._quality_gate.evaluate(candidate)
        outcome = _OUTCOME_MAP[decision.outcome]
        reason = (
            "quality_gate_eligible"
            if outcome is T2Outcome.PROPOSED
            else f"quality_gate_{decision.outcome.value}"
        )
        return T2Decision(
            outcome=outcome,
            candidate=candidate,
            quality_decision=decision,
            reason=reason,
        )


__all__ = ["QualityGateProtocol", "T2Decision", "T2Outcome", "T2Proposer", "T2Tier"]
