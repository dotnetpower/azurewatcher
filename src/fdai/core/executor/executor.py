"""Shadow-mode executor - the safety-invariant enforcement point.

Every autonomous change MUST carry the four invariants declared in
[`.github/instructions/coding-conventions.instructions.md § Safety`]:

1. **Stop-condition** - comes from the rule's ``ActionType`` (declared at
   catalog authoring, enforced at execute time by refusing an :class:`Action`
   whose ``stop_condition`` slot is empty).
2. **Rollback path** - recorded on the Action + embedded in the shadow PR
   body so an operator can revert with a single follow-up PR.
3. **Blast-radius limit** - the executor abstains and escalates when the
   Action's :attr:`~fdai.shared.contracts.models.BlastRadius.count`
   or ``rate_per_minute`` exceeds the executor-side cap.
4. **Audit-log entry** - every terminal outcome (published, dedup-hit,
   abstain, render error, blast-radius refusal, precondition failure)
   writes one and only one hash-chained record via
   :class:`~fdai.shared.providers.state_store.StateStore.append_audit_entry`.

Shadow-only
-----------

P1 does not have an enforce path. Every :class:`ExecutionResult` produced
here MUST carry ``mode=Mode.SHADOW`` and the emitted :class:`RemediationPr`
MUST be a draft with the ``shadow`` label. The property-level invariant
"shadow mode never mutates state" is enforced by:

- refusing an Action whose :attr:`Action.mode` is enforce;
- delegating actual publish to a :class:`RemediationPrPublisher` that is
  contractually forbidden from merging.

Idempotency
-----------

Deduplication is keyed on :attr:`Action.idempotency_key`. The executor
keeps an in-process cache so a re-delivered event returns the same
receipt without republishing; a cross-process deployment relies on the
publisher's own idempotency check (also keyed on
``idempotency_key``) to handle a process restart between deliveries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from fdai.core.executor.lock import ResourceLockManager
from fdai.core.executor.renderer import (
    RenderError,
    RenderRequest,
    TemplateRenderer,
)
from fdai.shared.contracts.models import Action, Mode, Rule
from fdai.shared.providers.remediation_pr import (
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.state_store import StateStore

_DEFAULT_MAX_AFFECTED_RESOURCES: Final[int] = 10
_DEFAULT_MAX_RATE_PER_MINUTE: Final[int] = 30


class ExecutorOutcome(StrEnum):
    """Terminal outcome for one :meth:`ShadowExecutor.execute` call."""

    PUBLISHED = "published"
    """Fresh publish; a new shadow PR now exists on the delivery side."""

    ALREADY_EXISTED = "already_existed"
    """Duplicate delivery: the publisher (or the executor's in-process
    dedupe) returned an existing PR."""

    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    """Action requested a change to more resources / higher rate than the
    executor cap; escalate to HIL rather than partial-apply."""

    ABSTAINED_RENDER_ERROR = "abstained_render_error"
    """Template rendering failed (missing placeholder, invalid syntax,
    template file missing). The action is dropped fail-closed."""

    REJECTED_MODE = "rejected_mode"
    """Action carried ``Mode.ENFORCE`` but the executor is P1
    shadow-only. No PR opened; audit records the refusal."""

    REJECTED_INVARIANT = "rejected_invariant"
    """Action was missing one of the four safety invariants (empty
    ``stop_condition``, missing rollback, blast_radius, ...)."""


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    """Per-executor safety caps.

    A fork MAY tighten these values via composition; loosening requires
    an audited governance change (see
    [`docs/roadmap/rule-governance.md`](../../../../docs/roadmap/rule-governance.md)).
    """

    max_affected_resources: int = _DEFAULT_MAX_AFFECTED_RESOURCES
    max_rate_per_minute: int = _DEFAULT_MAX_RATE_PER_MINUTE


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Outcome of one :meth:`ShadowExecutor.execute` call, always audited."""

    action_id: str
    outcome: ExecutorOutcome
    mode: Mode = Mode.SHADOW
    pr_ref: str | None = None
    pr_url: str | None = None
    reason: str | None = None
    audit_context: dict[str, object] = field(default_factory=dict)


class ShadowExecutor:
    """The one execution surface for P1 remediation PRs."""

    def __init__(
        self,
        *,
        publisher: RemediationPrPublisher,
        audit_store: StateStore,
        renderer: TemplateRenderer,
        resource_lock: ResourceLockManager,
        config: ExecutorConfig | None = None,
    ) -> None:
        self._publisher = publisher
        self._audit_store = audit_store
        self._renderer = renderer
        self._resource_lock = resource_lock
        self._config = config or ExecutorConfig()
        # idempotency_key -> ExecutionResult
        self._dedupe: dict[str, ExecutionResult] = {}

    async def execute(self, *, action: Action, rule: Rule) -> ExecutionResult:
        """Execute one action against one rule; always writes an audit entry.

        Returns an :class:`ExecutionResult` describing the terminal state.
        Never raises for a business-logic failure - a broken template, a
        blast-radius overrun, or an enforce-mode Action all fail closed
        into an audited abstain, matching the "fail toward safety" rule
        in ``architecture.instructions.md § Design Principles``.
        """
        # Shadow-only path (P1): reject an enforce-mode Action BEFORE the
        # lock so we do not serialize with unrelated shadow work.
        if action.mode is not Mode.SHADOW:
            return await self._finish(
                action=action,
                rule=rule,
                outcome=ExecutorOutcome.REJECTED_MODE,
                reason="enforce mode is out of scope in P1 (phase-1 § Autonomy Level)",
            )

        invariant_reason = _missing_safety_invariant(action)
        if invariant_reason is not None:
            return await self._finish(
                action=action,
                rule=rule,
                outcome=ExecutorOutcome.REJECTED_INVARIANT,
                reason=invariant_reason,
            )

        # Idempotency check - MUST happen inside the resource lock so a
        # racing re-delivery cannot double-publish; but a quick check
        # outside the lock lets an obvious duplicate short-circuit.
        cached = self._dedupe.get(action.idempotency_key)
        if cached is not None:
            return cached

        async with self._resource_lock.acquire(action.target_resource_ref):
            cached = self._dedupe.get(action.idempotency_key)
            if cached is not None:
                return cached

            blast_reason = self._check_blast_radius(action)
            if blast_reason is not None:
                return await self._finish(
                    action=action,
                    rule=rule,
                    outcome=ExecutorOutcome.ABSTAINED_BLAST_RADIUS,
                    reason=blast_reason,
                )

            try:
                patch = self._renderer.render(
                    RenderRequest(
                        rule=rule,
                        resource_id=action.target_resource_ref,
                        params=dict(action.params),
                    )
                )
            except RenderError as exc:
                return await self._finish(
                    action=action,
                    rule=rule,
                    outcome=ExecutorOutcome.ABSTAINED_RENDER_ERROR,
                    reason=str(exc),
                )

            pr = _build_remediation_pr(action=action, rule=rule, patch=patch)
            receipt = await self._publisher.publish(pr)

            outcome = (
                ExecutorOutcome.ALREADY_EXISTED
                if receipt.already_existed
                else ExecutorOutcome.PUBLISHED
            )
            result = await self._finish(
                action=action,
                rule=rule,
                outcome=outcome,
                reason=None,
                pr_ref=receipt.pr_ref,
                pr_url=receipt.url,
            )
            return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _check_blast_radius(self, action: Action) -> str | None:
        count = action.blast_radius.count
        if count is not None and count > self._config.max_affected_resources:
            return (
                f"blast-radius count {count} exceeds executor cap "
                f"{self._config.max_affected_resources}"
            )
        rpm = action.blast_radius.rate_per_minute
        if rpm is not None and rpm > self._config.max_rate_per_minute:
            return (
                f"blast-radius rate {rpm}/min exceeds executor cap "
                f"{self._config.max_rate_per_minute}/min"
            )
        return None

    async def _finish(
        self,
        *,
        action: Action,
        rule: Rule,
        outcome: ExecutorOutcome,
        reason: str | None,
        pr_ref: str | None = None,
        pr_url: str | None = None,
    ) -> ExecutionResult:
        result = ExecutionResult(
            action_id=str(action.action_id),
            outcome=outcome,
            mode=Mode.SHADOW,
            pr_ref=pr_ref,
            pr_url=pr_url,
            reason=reason,
            audit_context={
                "rule_id": rule.id,
                "rule_version": rule.version,
                "resource_ref": action.target_resource_ref,
                "action_type": action.action_type,
                "operation": action.operation.value,
                "blast_radius_scope": action.blast_radius.scope.value,
            },
        )
        self._dedupe[action.idempotency_key] = result
        await self._write_audit(action=action, rule=rule, result=result)
        return result

    async def _write_audit(self, *, action: Action, rule: Rule, result: ExecutionResult) -> None:
        entry = {
            "event_id": str(action.event_id),
            "action_id": str(action.action_id),
            "idempotency_key": action.idempotency_key,
            "actor": "fdai.core.executor.shadow",
            "action_kind": action.action_type,
            "mode": Mode.SHADOW.value,
            "citing_rule_ids": list(action.citing_rules),
            "outcome": result.outcome.value,
            "pr_ref": result.pr_ref,
            "pr_url": result.pr_url,
            "reason": result.reason,
            "rule_id": rule.id,
            "rule_version": rule.version,
            "resource_ref": action.target_resource_ref,
            "operation": action.operation.value,
            "rollback_kind": action.rollback_ref.kind.value,
            "rollback_reference": action.rollback_ref.reference,
            "stop_condition": action.stop_condition,
            "blast_radius": {
                "scope": action.blast_radius.scope.value,
                "count": action.blast_radius.count,
                "rate_per_minute": action.blast_radius.rate_per_minute,
            },
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        await self._audit_store.append_audit_entry(entry)


def _missing_safety_invariant(action: Action) -> str | None:
    """Return a human message for the first missing safety invariant, or ``None``.

    The pydantic model already requires the fields; this guard is
    defense-in-depth against a caller that produced an ``Action`` via
    :func:`dataclasses.replace` or a partial dict.
    """
    if not action.stop_condition.strip():
        return "action.stop_condition MUST NOT be empty (safety invariant 1)"
    if not action.rollback_ref.kind:
        return "action.rollback_ref.kind MUST be set (safety invariant 2)"
    if action.blast_radius is None:
        # unreachable via pydantic, but keeps the intent legible.
        return "action.blast_radius MUST be set (safety invariant 3)"
    if not action.citing_rules:
        return "action.citing_rules MUST include at least one rule id"
    return None


def _build_remediation_pr(*, action: Action, rule: Rule, patch: str) -> RemediationPr:
    title = f"[shadow] {rule.id}: {action.action_type}"
    body_lines = [
        f"**Rule**: `{rule.id}` v{rule.version}",
        f"**ActionType**: `{action.action_type}`",
        f"**Target**: `{action.target_resource_ref}`",
        f"**Stop condition**: `{action.stop_condition}`",
        (
            f"**Rollback**: `{action.rollback_ref.kind.value}`"
            + (f" → `{action.rollback_ref.reference}`" if action.rollback_ref.reference else "")
        ),
        (
            "**Blast radius**: "
            f"scope=`{action.blast_radius.scope.value}`"
            + (
                f", count=`{action.blast_radius.count}`"
                if action.blast_radius.count is not None
                else ""
            )
            + (
                f", rate/min=`{action.blast_radius.rate_per_minute}`"
                if action.blast_radius.rate_per_minute is not None
                else ""
            )
        ),
        "",
        "Shadow-mode PR - NOT mergeable. Promoted to enforce only after the",
        "ActionType's `promotion_gate` clears on the frozen scenario set.",
    ]
    body = "\n".join(body_lines)
    return RemediationPr(
        action_id=action.action_id,
        idempotency_key=action.idempotency_key,
        rule_ids=tuple(action.citing_rules),
        title=title,
        body=body,
        patch=patch,
        patch_path=_default_patch_path(action=action, rule=rule),
        labels=("shadow", f"rule:{rule.id}", f"action:{action.action_type}"),
        mode=Mode.SHADOW,
    )


def _default_patch_path(*, action: Action, rule: Rule) -> str:
    """Derive a repo-relative Terraform target from the action + rule.

    Real deployment maps this to the tenant's IaC repo layout; the
    executor only produces a stable *hint* - the delivery adapter is
    responsible for the actual branch commit.
    """
    del rule  # reserved for a future rule → path mapping
    slug = action.target_resource_ref.replace("/", "_").replace(":", "_")
    return f"infra/envs/dev/{slug}.tf"


__all__ = [
    "ExecutionResult",
    "ExecutorConfig",
    "ExecutorOutcome",
    "ShadowExecutor",
]
