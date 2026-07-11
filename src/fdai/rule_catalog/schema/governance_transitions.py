"""Governance effect-transition validation across two catalog versions.

rule-governance.md requires that any effect transition not in the allowed table
is rejected in CI, and that raising a shadow (``audit``) assignment to an enforce
effect (``deny`` / ``remediate``) needs a separate promotion approval. This
module is the pure core of that gate: given the previous and current
:class:`~fdai.rule_catalog.schema.governance_catalog.GovernanceCatalog`, it
validates every per-rule effective-effect transition and returns the issues. A
thin CI script wires it to ``git`` (load previous vs working-tree catalog).

Pure and I/O-free. A new assignment is validated as a transition from the
mandated default (``audit``), so a catalog cannot introduce a rule already at
``deny`` / ``remediate`` without the promotion approval.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.rule_catalog.schema.effect import (
    Effect,
    EffectTransitionError,
    default_effect,
    validate_effect_transition,
)
from fdai.rule_catalog.schema.governance_catalog import GovernanceCatalog


@dataclass(frozen=True, slots=True)
class TransitionIssue:
    """One rejected effect transition."""

    assignment_id: str
    rule_id: str
    message: str


def _check(
    issues: list[TransitionIssue],
    assignment_id: str,
    rule_id: str,
    from_effect: Effect,
    to_effect: Effect,
    promotion_approved: bool,
) -> None:
    try:
        validate_effect_transition(
            from_effect=from_effect,
            to_effect=to_effect,
            promotion_approved=promotion_approved,
        )
    except EffectTransitionError as exc:
        issues.append(
            TransitionIssue(assignment_id=assignment_id, rule_id=rule_id, message=str(exc))
        )


def validate_catalog_transition(
    *,
    previous: GovernanceCatalog,
    current: GovernanceCatalog,
    promotions_approved: frozenset[str] = frozenset(),
) -> list[TransitionIssue]:
    """Validate every per-rule effective-effect transition from ``previous`` to
    ``current``.

    For each assignment in ``current`` and each rule it targets, the effective
    effect (top-level or per-rule override) is compared to the same rule's
    effective effect in the matching previous assignment - or the mandated
    ``audit`` default when the assignment or rule is new. Raising to an enforce
    effect requires the assignment id in ``promotions_approved``. Removed
    assignments/rules need no check (removal is always allowed). Returns every
    issue; an empty list means the change set is clean.
    """
    issues: list[TransitionIssue] = []
    prev_by_id = {a.id: a for a in previous.assignments}
    for curr in current.assignments:
        prev = prev_by_id.get(curr.id)
        approved = curr.id in promotions_approved
        for rule_id in sorted(curr.target_rule_ids):
            new_effect = curr.effect_for(rule_id)
            if prev is not None and rule_id in prev.target_rule_ids:
                old_effect = prev.effect_for(rule_id)
            else:
                old_effect = default_effect()
            _check(issues, curr.id, rule_id, old_effect, new_effect, approved)
    return issues


__all__ = ["TransitionIssue", "validate_catalog_transition"]
