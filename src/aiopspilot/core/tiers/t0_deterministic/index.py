"""Rule lookup index for the T0 engine.

Given a loaded rule catalog, the index answers "which rules apply to a
Signal of type ``S`` targeting a Resource of type ``R``?" in O(indexed
lookup), never a linear scan (see
``docs/roadmap/llm-strategy.md § Rule-to-Decision Lookup Pipeline``).

P1 W-2 implementation
---------------------
The Rule contract today carries ``resource_type`` (a single value) as the
primary ``applies_to`` axis. Full ontology dispatch (multi-value
``applies_to`` × ``triggered_by`` × ``evaluates`` × ``required_interfaces``
× ``submission_criteria``) is documented and reserved - the loader
already validates every rule's ``remediates`` cross-reference against the
ActionType catalog. This module's index widens deterministically as those
fields land on the Rule model; the public API (:meth:`rules_for_type`,
:meth:`rules_for_signal`) does not change.

Determinism guarantees
----------------------
- The order of returned rules is stable: by ``severity`` desc, then
  ``rule.id`` asc. That is the same ordering
  ``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Precedence`` prescribes,
  so a downstream verdict emitter can pick the top match without a
  second sort.
- Duplicate ``resource_type`` entries are grouped, not overwritten - the
  loader already forbids duplicate ``rule.id`` across files, so grouping
  is safe.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from aiopspilot.shared.contracts.models import Rule, Severity

# Severity precedence (higher = more urgent). Matches the
# `critical > high > medium > low` ordering documented in
# `phase-1-rule-catalog-t0.md § Precedence`.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}


def _severity_order_key(rule: Rule) -> tuple[int, str]:
    # Negative rank so higher severity sorts first with a plain ascending sort.
    return (-_SEVERITY_RANK[rule.severity], rule.id)


@dataclass(frozen=True, slots=True)
class RuleIndex:
    """Immutable lookup index over a loaded rule catalog.

    Instances are created with :meth:`build`; direct construction is not
    part of the public contract (the internal mappings may grow).
    """

    _by_resource_type: dict[str, tuple[Rule, ...]]
    _by_id: dict[str, Rule]

    @classmethod
    def build(cls, rules: Iterable[Rule]) -> RuleIndex:
        by_type: dict[str, list[Rule]] = {}
        by_id: dict[str, Rule] = {}
        for rule in rules:
            if rule.id in by_id:
                # The catalog loader rejects duplicates; if a caller
                # bypasses it, fail loudly rather than silently overwrite.
                raise ValueError(f"duplicate rule id in index build: {rule.id!r}")
            by_id[rule.id] = rule
            by_type.setdefault(rule.resource_type, []).append(rule)

        frozen: dict[str, tuple[Rule, ...]] = {
            key: tuple(sorted(items, key=_severity_order_key)) for key, items in by_type.items()
        }
        return cls(_by_resource_type=frozen, _by_id=by_id)

    def rules_for_type(self, resource_type: str) -> tuple[Rule, ...]:
        """Return every rule whose ``resource_type`` matches, severity-ordered."""
        return self._by_resource_type.get(resource_type, ())

    def rules_for_signal(
        self, *, resource_type: str, signal_type: str | None = None
    ) -> tuple[Rule, ...]:
        """Return every rule that would evaluate for this Signal.

        ``signal_type`` is accepted for API stability - the future
        ``applies_to ∩ triggered_by`` intersection will filter on it. In
        P1 W-2 we route strictly by ``resource_type`` and treat
        ``signal_type`` as informational so the trust router can already
        thread it through without a follow-up API change.
        """
        del signal_type  # reserved for full ontology dispatch (see docstring)
        return self.rules_for_type(resource_type)

    def rule(self, rule_id: str) -> Rule:
        try:
            return self._by_id[rule_id]
        except KeyError as exc:
            raise LookupError(f"unknown rule id: {rule_id!r}") from exc

    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id.keys())

    def resource_types(self) -> frozenset[str]:
        return frozenset(self._by_resource_type.keys())

    def __len__(self) -> int:
        return len(self._by_id)


__all__ = ["RuleIndex"]
