"""Workflow orchestrator (shadow) - run a Workflow's steps through the
existing RunbookRunner, judge-and-log only, never mutating.

This is the P1 process orchestrator the action ontology reserved as
declared-but-not-yet-live (see docs/roadmap/process-automation.md 4-5). It
closes the gap between a compiled Workflow and an audited run:

1. build the :class:`~fdai.core.workflow.approval.ApprovalPlan` (who approves
   each step, resolved from Entra RBAC + the notification matrix);
2. derive an idempotent :class:`Process` id from
   ``(workflow, target_resource_id, trigger_ts)``;
3. compile the Workflow to a :class:`~fdai.core.runbook.models.Runbook` and walk
   it with :class:`~fdai.core.runbook.runner.RunbookRunner`, using a
   **shadow** step executor that writes an audit entry per step and returns
   success without ever mutating a resource.

Shadow-only by construction
---------------------------

:class:`ShadowWorkflowStepExecutor` has no publisher, no direct-API executor,
and no resource lock - it structurally cannot mutate. A step is judged and
logged (with its resolved approval requirement) and reported ``SUCCESS``.
Promotion to a live (enforce) executor that re-enters the risk-gate ->
executor -> delivery path is a separate, gated change; until then a workflow
run cannot change cloud state. This mirrors the "new capabilities ship in
shadow" invariant in architecture.instructions.md.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome, RunbookStepResult
from fdai.core.runbook.runner import RunbookRunner
from fdai.core.workflow.approval import ApprovalPlan, StepApproval, WorkflowApprovalPlanner
from fdai.core.workflow.compiler import compile_workflow
from fdai.shared.contracts.models import OntologyActionType, Workflow
from fdai.shared.providers.state_store import StateStore

_ACTOR = "fdai.core.workflow.orchestrator"

_PARAM_TOKEN = re.compile(r"\$\{([a-z0-9_.]+)\}")


def _resolve_params(params: Mapping[str, object], context: Mapping[str, str]) -> dict[str, object]:
    """Substitute ``${token}`` in string param values from ``context``.

    Only string values are templated; a token with no context entry is left
    verbatim so the unresolved reference is visible in the audit rather than
    silently blanked. Non-string values pass through unchanged.
    """
    resolved: dict[str, object] = {}
    for key, value in params.items():
        if isinstance(value, str):
            resolved[key] = _PARAM_TOKEN.sub(lambda m: context.get(m.group(1), m.group(0)), value)
        else:
            resolved[key] = value
    return resolved


@runtime_checkable
class WorkflowGuardEvaluator(Protocol):
    """Evaluate a step's ``guard_rule_ref`` at run time.

    A guard is the deterministic "when" for a step - a policy-as-code predicate,
    never model text. The upstream default injects no evaluator, so a guard is
    load-validated but recorded as ``not_evaluated`` at run time; a fork (or the
    enforce path) binds a concrete OPA-backed evaluator via this seam. The
    implementation MUST be deterministic and side-effect free.
    """

    async def evaluate(self, *, rule_id: str, step_id: str, process_id: str) -> bool:
        """Return True when the guard permits the step to proceed."""
        ...


class ProcessStatus(StrEnum):
    """Status of a shadow :class:`Process` run.

    Mirrors the ``Process`` ObjectType ``status`` values; a shadow run moves
    ``RUNNING`` -> ``SUCCEEDED`` / ``FAILED`` (compensation is inert in P1).
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_PROCESS_KEY_PREFIX = "process:"


def process_state_key(process_id: str) -> str:
    """State-store key holding the :class:`Process` record for ``process_id``."""
    return f"{_PROCESS_KEY_PREFIX}{process_id}"


def _process_record(
    *,
    process_id: str,
    workflow_name: str,
    status: ProcessStatus,
    current_step: str,
    target_resource_id: str,
    started_at: datetime,
) -> dict[str, object]:
    """Build a ``Process`` ObjectType row (process-automation.md 3.1)."""
    return {
        "id": process_id,
        "workflow_ref": workflow_name,
        "status": status.value,
        "current_step": current_step,
        "target_resource_id": target_resource_id,
        "started_at": started_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class ProcessRun:
    """The result of one shadow Workflow run."""

    process_id: str
    workflow_name: str
    status: ProcessStatus
    step_results: tuple[RunbookStepResult, ...]
    approval_plan: ApprovalPlan


class ShadowWorkflowStepExecutor:
    """A :class:`~fdai.core.runbook.runner.StepExecutor` that judges and logs a
    step without mutating. It has no path to a publisher or executor, so the
    shadow invariant is structural, not conventional."""

    __slots__ = (
        "_process_id",
        "_action_types",
        "_audit",
        "_approvals",
        "_guards",
        "_guard_evaluator",
        "_params",
    )

    def __init__(
        self,
        *,
        process_id: str,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
        approvals: Mapping[str, StepApproval],
        guards: Mapping[str, str] | None = None,
        guard_evaluator: WorkflowGuardEvaluator | None = None,
        params: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        self._process_id = process_id
        self._action_types = action_types
        self._audit = audit_store
        self._approvals = approvals
        self._guards = guards or {}
        self._guard_evaluator = guard_evaluator
        self._params = params or {}

    async def execute(self, *, runbook_id: str, step: RunbookStep) -> RunbookStepResult:
        approval = self._approvals.get(step.id)
        known = step.action_type in self._action_types
        guard_ref = self._guards.get(step.id)

        guard_evaluated = False
        guard_passed: bool | None = None
        if guard_ref is not None and self._guard_evaluator is not None:
            guard_evaluated = True
            guard_passed = await self._guard_evaluator.evaluate(
                rule_id=guard_ref, step_id=step.id, process_id=self._process_id
            )

        await self._audit.append_audit_entry(
            {
                "actor": _ACTOR,
                "action_kind": "workflow.step",
                "mode": "shadow",
                "process_id": self._process_id,
                "workflow": runbook_id,
                "step_id": step.id,
                "action_type": step.action_type,
                "action_known": known,
                "requires_approval": approval.requires_approval if approval else False,
                "required_role": (
                    approval.required_role.value if approval and approval.required_role else None
                ),
                "approver_group": approval.entra_group_ref if approval else None,
                "notify_channels": list(approval.notify_channels) if approval else [],
                "guard_rule_ref": guard_ref,
                "guard_evaluated": guard_evaluated,
                "guard_passed": guard_passed,
                "params": dict(self._params.get(step.id, {})),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

        if not known:
            return RunbookStepResult(
                step_id=step.id,
                action_type=step.action_type,
                outcome=RunbookStepOutcome.FAILURE,
                reason="unknown_action_type",
            )
        if guard_evaluated and guard_passed is False:
            # The guard blocked the step. In shadow the action would not apply,
            # so this is a judged no-op, not a run failure - the run continues.
            return RunbookStepResult(
                step_id=step.id,
                action_type=step.action_type,
                outcome=RunbookStepOutcome.SUCCESS,
                reason="guard_blocked_shadow_noop",
            )
        return RunbookStepResult(
            step_id=step.id,
            action_type=step.action_type,
            outcome=RunbookStepOutcome.SUCCESS,
            reason="shadow_judge_and_log",
        )


def derive_process_id(*, workflow_name: str, target_resource_id: str, trigger_ts: datetime) -> str:
    """Idempotent Process id from ``(workflow, target, trigger_ts)``.

    A retried trigger with the same key reuses the id, so a re-delivery does not
    start a second Process (process-automation.md 3.1).
    """
    key = f"{workflow_name}:{target_resource_id}:{trigger_ts.isoformat()}"
    return str(uuid5(NAMESPACE_URL, key))


class WorkflowOrchestrator:
    """Run a Workflow in shadow: plan approvals, then walk the compiled Runbook
    with a non-mutating step executor, auditing the whole run."""

    __slots__ = ("_planner", "_action_types", "_audit", "_guard_evaluator")

    def __init__(
        self,
        *,
        planner: WorkflowApprovalPlanner,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
        guard_evaluator: WorkflowGuardEvaluator | None = None,
    ) -> None:
        self._planner = planner
        self._action_types = action_types
        self._audit = audit_store
        self._guard_evaluator = guard_evaluator

    async def run(
        self,
        workflow: Workflow,
        *,
        target_resource_id: str,
        trigger_ts: datetime,
        context: Mapping[str, str] | None = None,
    ) -> ProcessRun:
        """Execute ``workflow`` in shadow over ``target_resource_id`` and return
        the :class:`ProcessRun`. Never mutates a resource.

        ``context`` supplies additional ``${token}`` values for step param
        substitution (e.g. ``event.event_type`` from the coordinator); the
        target resource and trigger timestamp are always available as
        ``event.resource_ref`` / ``event.trigger_ts``.
        """
        plan = self._planner.plan(workflow)
        approvals = {s.step_id: s for s in plan.steps}
        process_id = derive_process_id(
            workflow_name=workflow.name,
            target_resource_id=target_resource_id,
            trigger_ts=trigger_ts,
        )
        started_at = datetime.now(tz=UTC)
        first_step = workflow.steps[0].id
        subst_context: dict[str, str] = {
            "event.resource_ref": target_resource_id,
            "event.trigger_ts": trigger_ts.isoformat(),
        }
        if context:
            subst_context.update(context)
        resolved_params = {s.id: _resolve_params(s.params, subst_context) for s in workflow.steps}

        await self._audit.append_audit_entry(
            {
                "actor": _ACTOR,
                "action_kind": "workflow.process-plan",
                "mode": "shadow",
                "process_id": process_id,
                "workflow": workflow.name,
                "target_resource_id": target_resource_id,
                "trigger_ts": trigger_ts.isoformat(),
                "plan": plan.to_audit_dict(),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

        # Persist the Process ObjectType row (running); the terminal write below
        # overwrites it. This is the runtime writer for the Process ontology
        # type (process-automation.md 3.1).
        await self._audit.write_state(
            process_state_key(process_id),
            _process_record(
                process_id=process_id,
                workflow_name=workflow.name,
                status=ProcessStatus.RUNNING,
                current_step=first_step,
                target_resource_id=target_resource_id,
                started_at=started_at,
            ),
        )

        compiled = compile_workflow(workflow)
        guards = {s.id: s.guard_rule_ref for s in workflow.steps if s.guard_rule_ref is not None}
        executor = ShadowWorkflowStepExecutor(
            process_id=process_id,
            action_types=self._action_types,
            audit_store=self._audit,
            approvals=approvals,
            guards=guards,
            guard_evaluator=self._guard_evaluator,
            params=resolved_params,
        )
        runner = RunbookRunner(executor=executor, audit_store=self._audit)
        result = await runner.run(compiled.runbook)

        status = (
            ProcessStatus.SUCCEEDED
            if result.terminal_outcome is RunbookStepOutcome.SUCCESS
            else ProcessStatus.FAILED
        )
        await self._audit.write_state(
            process_state_key(process_id),
            _process_record(
                process_id=process_id,
                workflow_name=workflow.name,
                status=status,
                current_step="",
                target_resource_id=target_resource_id,
                started_at=started_at,
            ),
        )
        return ProcessRun(
            process_id=process_id,
            workflow_name=workflow.name,
            status=status,
            step_results=result.step_results,
            approval_plan=plan,
        )


__all__ = [
    "ProcessRun",
    "ProcessStatus",
    "ShadowWorkflowStepExecutor",
    "WorkflowGuardEvaluator",
    "WorkflowOrchestrator",
    "derive_process_id",
]
