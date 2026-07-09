"""WorkflowOrchestrator (shadow) tests.

Covers the P1 shadow run: plan approvals, walk the compiled Runbook with a
non-mutating step executor, and audit the whole run. Proves the shadow
invariant (no mutation), the audit trail shape, idempotent Process ids, and
that a gated step carries its resolved approver assignment into the audit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import (
    ProcessStatus,
    ShadowWorkflowStepExecutor,
    WorkflowOrchestrator,
    derive_process_id,
)
from fdai.shared.contracts.models import (
    Autonomy,
    CeilingByTier,
    CeilingRole,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    TierCeiling,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TRIGGER_TS = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _group_mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="grp-readers",
        contributor_group_id="grp-contributors",
        approver_group_id="grp-approvers",
        owner_group_id="grp-owners",
        break_glass_group_id="grp-break-glass",
    )


def _matrix():  # type: ignore[no-untyped-def]
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "hil_approval",
                "routes": {
                    "hil_approval": {
                        "trust_tier": "a1_hil_approval",
                        "primary": "teams-hil-prd",
                        "fallback": ["slack-hil-prd"],
                    }
                },
            }
        }
    )


def _action(name: str, *, ceiling: CeilingByTier | None = None) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        description="Test action.",
        ceiling_by_tier=ceiling,
    )


_GATED = _action(
    "ops.gated",
    ceiling=CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
    ),
)
_AUTO = _action(
    "remediate.auto",
    ceiling=CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.CONTRIBUTOR),
    ),
)
_ACTION_TYPES = {a.name: a for a in (_GATED, _AUTO)}


def _workflow() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="sample-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[
            WorkflowStep(id="auto_step", action_type_ref="remediate.auto"),
            WorkflowStep(id="gated_step", action_type_ref="ops.gated"),
        ],
    )


def _orchestrator(audit: InMemoryStateStore) -> WorkflowOrchestrator:
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    return WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
    )


async def test_shadow_run_succeeds_and_judges_every_step() -> None:
    audit = InMemoryStateStore()
    run = await _orchestrator(audit).run(
        _workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS
    )
    assert run.status is ProcessStatus.SUCCEEDED
    assert [r.outcome for r in run.step_results] == [
        RunbookStepOutcome.SUCCESS,
        RunbookStepOutcome.SUCCESS,
    ]
    assert all(r.reason == "shadow_judge_and_log" for r in run.step_results)


async def test_audit_trail_shape() -> None:
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    kinds = [row["entry"]["action_kind"] for row in audit.audit_entries]
    # process-plan, then one workflow.step per step, then the runner terminal.
    assert kinds == [
        "workflow.process-plan",
        "workflow.step",
        "workflow.step",
        "runbook.terminal",
    ]
    # Every workflow entry is shadow-mode.
    for row in audit.audit_entries:
        entry = row["entry"]
        if entry["action_kind"].startswith("workflow."):
            assert entry["mode"] == "shadow"


async def test_gated_step_carries_approver_assignment_into_audit() -> None:
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    step_rows = [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.step"
    ]
    by_step = {e["step_id"]: e for e in step_rows}
    assert by_step["gated_step"]["requires_approval"] is True
    assert by_step["gated_step"]["required_role"] == "Approver"
    assert by_step["gated_step"]["approver_group"] == "grp-approvers"
    assert by_step["gated_step"]["notify_channels"] == ["teams-hil-prd", "slack-hil-prd"]
    # The auto step is not a gate.
    assert by_step["auto_step"]["requires_approval"] is False
    assert by_step["auto_step"]["approver_group"] is None


async def test_process_id_is_idempotent() -> None:
    audit = InMemoryStateStore()
    orch = _orchestrator(audit)
    run_a = await orch.run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    run_b = await orch.run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    assert run_a.process_id == run_b.process_id
    # A different target yields a different id.
    run_c = await orch.run(_workflow(), target_resource_id="res-2", trigger_ts=_TRIGGER_TS)
    assert run_c.process_id != run_a.process_id


def test_derive_process_id_is_stable() -> None:
    a = derive_process_id(workflow_name="wf", target_resource_id="r", trigger_ts=_TRIGGER_TS)
    b = derive_process_id(workflow_name="wf", target_resource_id="r", trigger_ts=_TRIGGER_TS)
    assert a == b


async def test_unknown_action_type_step_fails_closed() -> None:
    # The executor branch for an ActionType absent from the catalog: it audits
    # and reports FAILURE rather than pretending success.
    audit = InMemoryStateStore()
    executor = ShadowWorkflowStepExecutor(
        process_id="p-1",
        action_types=_ACTION_TYPES,
        audit_store=audit,
        approvals={},
    )
    result = await executor.execute(
        runbook_id="wf", step=RunbookStep(id="ghost", action_type="ops.absent")
    )
    assert result.outcome is RunbookStepOutcome.FAILURE
    assert result.reason == "unknown_action_type"
