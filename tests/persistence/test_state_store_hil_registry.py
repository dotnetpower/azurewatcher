"""StateStore-backed HIL registry projection and decision tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.persistence.state_store_hil_registry import (
    StateStoreHilApprovalRegistry,
    add_pending_approval,
)
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilItemAlreadyResolvedError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def _seed(store: InMemoryStateStore) -> None:
    await store.write_state(
        "hil_park:approval-1",
        {
            "status": "pending",
            "approval_id": "approval-1",
            "idempotency_key": "event-1::rule-1::resource-1",
            "action_type": "remediate.tag-add",
            "submitter_oid": "submitter-1",
            "correlation_id": "corr-1",
            "parked_at": "2026-07-15T00:00:00+00:00",
            "execution_path": "pr_native",
            "action": {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "action_id": "00000000-0000-0000-0000-000000000002",
                "action_type": "remediate.tag-add",
                "target_resource_ref": "resource:example/one",
                "citing_rules": ["rule-1"],
            },
        },
    )
    await add_pending_approval(store, "approval-1")
    await add_pending_approval(store, "approval-1")


@pytest.mark.asyncio
async def test_registry_satisfies_protocol_and_projects_park() -> None:
    store = InMemoryStateStore()
    await _seed(store)
    registry = StateStoreHilApprovalRegistry(store=store)

    assert isinstance(registry, HilApprovalRegistry)
    pending = await registry.list_pending()
    assert len(pending) == 1
    assert pending[0].approval_id == "approval-1"
    assert pending[0].submitter_oid == "submitter-1"
    assert pending[0].citing_rule_ids == ("rule-1",)
    assert pending[0].requested_at == datetime(2026, 7, 15, tzinfo=UTC)


@pytest.mark.asyncio
async def test_registry_records_idempotent_decision_and_rejects_conflict() -> None:
    store = InMemoryStateStore()
    await _seed(store)
    registry = StateStoreHilApprovalRegistry(store=store)
    key = "event-1::rule-1::resource-1"

    first = await registry.record_decision(
        idempotency_key=key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        justification="Reviewed by the on-call approver.",
    )
    replay = await registry.record_decision(
        idempotency_key=key,
        decision=HilApprovalDecision.APPROVE,
        approver_oid="approver-1",
        justification="Reviewed by the on-call approver.",
    )

    assert first.already_recorded is False
    assert replay.already_recorded is True
    assert replay.receipt_ref == first.receipt_ref
    with pytest.raises(HilItemAlreadyResolvedError):
        await registry.record_decision(
            idempotency_key=key,
            decision=HilApprovalDecision.REJECT,
            approver_oid="approver-2",
        )
