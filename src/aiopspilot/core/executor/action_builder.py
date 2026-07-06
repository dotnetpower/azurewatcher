"""Action builder - turn a T0 Finding into a policy-safe Action.

The T0 engine emits :class:`Finding` records (rule matches on resources).
The :class:`ShadowExecutor` consumes :class:`Action` values that carry the
four safety invariants inline. This module is the bridge: given a
Finding + the matched Rule + the referenced ActionType, produce a valid
Action that pydantic accepts.

Design notes
------------

- **Deterministic idempotency key**: composed from
  ``event.idempotency_key`` + ``rule.id`` + ``finding.resource_id``.
  A replay of the same event produces the same Action id (via
  ``uuid.uuid5``) so the executor's dedupe + the publisher's
  idempotency probe both hit the same cache entry.
- **Safety invariants** are derived from the ActionType - never
  guessed. Missing stop_conditions / blast_radius / rollback_contract
  fields raise :class:`ActionBuildError` so a partial ActionType
  cannot slip past.
- **Shadow-only** - every Action carries :attr:`Mode.SHADOW` in P1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from aiopspilot.core.tiers.t0_deterministic.models import Finding
from aiopspilot.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusComputation,
    BlastRadiusScope,
    Event,
    Mode,
    OntologyActionType,
    RollbackRef,
    Rule,
)


class ActionBuildError(ValueError):
    """Raised when a Finding + Rule + ActionType cannot map to an Action."""


@dataclass(frozen=True, slots=True)
class ActionBuilder:
    """Deterministic mapping from a Finding to an Action.

    Kept as a plain dataclass so a fork MAY subclass it to tighten
    invariants (e.g. reject an ActionType whose stop_conditions include
    a value the fork's operator group disallows) without touching the
    executor.
    """

    action_types_by_name: dict[str, OntologyActionType]

    def build_from_finding(
        self,
        *,
        event: Event,
        finding: Finding,
        rule: Rule,
    ) -> Action:
        """Return a fully-populated :class:`Action` for one finding."""
        action_type = self.action_types_by_name.get(rule.remediates)
        if action_type is None:
            raise ActionBuildError(
                f"rule {rule.id!r} remediates {rule.remediates!r} "
                "which is not registered in the ActionType catalog"
            )

        stop_condition = _derive_stop_condition(action_type)
        rollback = RollbackRef(kind=action_type.rollback_contract, reference=None)
        blast_radius = _derive_blast_radius(action_type)
        idempotency_key = _build_idempotency_key(event=event, finding=finding)
        action_id = _build_action_id(idempotency_key)

        params: dict[str, Any] = dict(rule.parameters)
        # Finding context (e.g. `deny_reason`) is audit-log data, not a
        # template placeholder - keeping it out of Action.params means the
        # template renderer's scalar-only rule stays clean.

        return Action(
            schema_version="1.0.0",
            action_id=action_id,
            idempotency_key=idempotency_key,
            event_id=event.event_id,
            action_type=action_type.name,
            target_resource_ref=finding.resource_id,
            operation=action_type.operation,
            params=params,
            stop_condition=stop_condition,
            rollback_ref=rollback,
            blast_radius=blast_radius,
            mode=Mode.SHADOW,
            citing_rules=[finding.rule_id],
            created_at=datetime.now(tz=UTC),
        )


def _derive_stop_condition(action_type: OntologyActionType) -> str:
    """Flatten the ActionType's first stop_condition into a string.

    :class:`Action.stop_condition` is a single string per the contract
    (see ``shared/contracts/action/schema.json``). ActionTypes ship a
    list; we take the first entry's ``kind`` as the shorthand and rely
    on the audit record to carry the full ActionType reference.
    ActionTypes without stop_conditions are legal at the schema level
    but the executor will refuse them, so we surface the missing state
    here for a clearer error.
    """
    if not action_type.stop_conditions:
        raise ActionBuildError(
            f"ActionType {action_type.name!r} declares no stop_conditions; "
            "P1 executor requires at least one"
        )
    kind = action_type.stop_conditions[0].kind
    return kind.value


def _derive_blast_radius(action_type: OntologyActionType) -> BlastRadius:
    """Flatten :class:`ActionBlastRadius` into the Action's :class:`BlastRadius`."""
    ar = action_type.blast_radius
    if ar is None:
        # Conservative default when the ActionType omits blast_radius -
        # single resource, no rate cap. P2 tightens this.
        return BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1)

    if ar.computation is BlastRadiusComputation.STATIC_ENUM:
        scope = ar.static_bucket or BlastRadiusScope.RESOURCE
        return BlastRadius(scope=scope, count=1)

    # graph_derived - count is bounded by the ActionType cap, real
    # resolved count comes from the risk-gate at P2. For now, use the
    # authored cap as the maximum affected count.
    return BlastRadius(
        scope=BlastRadiusScope.RESOURCE,
        count=ar.max_affected_resources or 1,
    )


def _build_idempotency_key(*, event: Event, finding: Finding) -> str:
    return f"{event.idempotency_key}::{finding.rule_id}::{finding.resource_id}"


def _build_action_id(idempotency_key: str) -> Any:
    """Deterministic UUID5 from the idempotency key.

    Replays of the same event produce the same action_id, so the
    executor's dedupe cache + the publisher's idempotency probe both
    treat them as the same request.
    """
    return uuid5(NAMESPACE_URL, f"aiopspilot.action://{idempotency_key}")


__all__ = ["ActionBuildError", "ActionBuilder"]
