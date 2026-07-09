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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome, RunbookStepResult
from fdai.core.runbook.runner import RunbookRunner
from fdai.core.workflow.approval import ApprovalPlan, StepApproval, WorkflowApprovalPlanner
from fdai.core.workflow.compiler import compile_workflow
from fdai.shared.contracts.models import OntologyActionType, Workflow
from fdai.shared.providers.state_store import StateStore

_ACTOR = "fdai.core.workflow.orchestrator"


class ProcessStatus(StrEnum):
    """Terminal status of a shadow :class:`Process` run.

    Mirrors the ``Process`` ObjectType ``status`` values; a shadow run only ever
    reaches ``SUCCEEDED`` or ``FAILED`` (compensation is inert in P1).
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"


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

    __slots__ = ("_process_id", "_action_types", "_audit", "_approvals")

    def __init__(
        self,
        *,
        process_id: str,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
        approvals: Mapping[str, StepApproval],
    ) -> None:
        self._process_id = process_id
        self._action_types = action_types
        self._audit = audit_store
        self._approvals = approvals

    async def execute(self, *, runbook_id: str, step: RunbookStep) -> RunbookStepResult:
        approval = self._approvals.get(step.id)
        known = step.action_type in self._action_types

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

    __slots__ = ("_planner", "_action_types", "_audit")

    def __init__(
        self,
        *,
        planner: WorkflowApprovalPlanner,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
    ) -> None:
        self._planner = planner
        self._action_types = action_types
        self._audit = audit_store

    async def run(
        self,
        workflow: Workflow,
        *,
        target_resource_id: str,
        trigger_ts: datetime,
    ) -> ProcessRun:
        """Execute ``workflow`` in shadow over ``target_resource_id`` and return
        the :class:`ProcessRun`. Never mutates a resource."""
        plan = self._planner.plan(workflow)
        approvals = {s.step_id: s for s in plan.steps}
        process_id = derive_process_id(
            workflow_name=workflow.name,
            target_resource_id=target_resource_id,
            trigger_ts=trigger_ts,
        )

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

        compiled = compile_workflow(workflow)
        executor = ShadowWorkflowStepExecutor(
            process_id=process_id,
            action_types=self._action_types,
            audit_store=self._audit,
            approvals=approvals,
        )
        runner = RunbookRunner(executor=executor, audit_store=self._audit)
        result = await runner.run(compiled.runbook)

        status = (
            ProcessStatus.SUCCEEDED
            if result.terminal_outcome is RunbookStepOutcome.SUCCESS
            else ProcessStatus.FAILED
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
    "WorkflowOrchestrator",
    "derive_process_id",
]
