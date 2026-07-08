"""Wave 2 governance staff behavior tests."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents.adapters import AuditChainError, InMemoryAuditChain
from fdai.agents.bus import InMemoryBus
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.registry import load_pantheon
from fdai.agents.saga import Saga, compute_fingerprint

# ---------------------------------------------------------------------------
# Saga - audit chain + issue dedup
# ---------------------------------------------------------------------------


def test_saga_audit_chain_appends_hash_linked_entries() -> None:
    saga = Saga()
    asyncio.run(
        saga.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "correlation_id": "corr-1",
                "risk_verdict": "auto",
            },
        )
    )
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Thor",
                "correlation_id": "corr-1",
                "state": "succeeded",
            },
        )
    )
    assert len(saga.audit_chain.entries) == 2
    saga.audit_chain.verify()


def test_saga_audit_chain_detects_tamper() -> None:
    chain = InMemoryAuditChain()
    chain.append(principal="Thor", topic="object.action-run", correlation_id="c", payload={})
    chain.append(principal="Thor", topic="object.action-run", correlation_id="c", payload={})
    # Tamper: mutate a payload_digest in place (frozen dataclass -> replace via list)
    tampered = chain.entries[1]
    chain.entries[1] = tampered.__class__(
        seq=tampered.seq,
        prev_hash=tampered.prev_hash,
        entry_hash=tampered.entry_hash,
        principal=tampered.principal,
        topic=tampered.topic,
        correlation_id=tampered.correlation_id,
        payload_digest="deadbeef",
    )
    with pytest.raises(AuditChainError):
        chain.verify()


def test_saga_issue_dedup_creates_once_and_appends_comment_on_repeat() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="cost_query_failed",
        resource_type="storage_account",
        normalized_selector="public_network_field",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )
    first = saga.escalate_to_github_issue(
        fingerprint=fp,
        emitting_agent="Heimdall",
        intent_category="cost_query_failed",
        failure_reason_code="no_owned_data",
        correlation_id="corr-1",
    )
    second = saga.escalate_to_github_issue(
        fingerprint=fp,
        emitting_agent="Heimdall",
        intent_category="cost_query_failed",
        failure_reason_code="no_owned_data",
        correlation_id="corr-2",
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["issue_number"] == first["issue_number"]
    assert second["occurrence_count"] == 2
    # Muninn index reflects the count
    idx = saga.state_store.get("issue_fingerprint_index", fp)
    assert idx is not None
    assert idx["occurrence_count"] == 2


def test_saga_close_issue_records_promoting_pr() -> None:
    saga = Saga()
    fp = compute_fingerprint(
        intent_category="x",
        resource_type="y",
        normalized_selector="z",
        primary_agent="Bragi",
        failure_reason_code="low_confidence",
    )
    saga.escalate_to_github_issue(
        fingerprint=fp,
        emitting_agent="Bragi",
        intent_category="x",
        failure_reason_code="low_confidence",
        correlation_id="corr-close",
    )
    saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/42")
    issue = saga.github.issues[fp]
    assert issue.open is False
    assert issue.closed_by_pr == "https://example.invalid/pr/42"


def test_saga_replay_returns_ordered_slice_for_correlation() -> None:
    saga = Saga()
    for i in range(3):
        asyncio.run(
            saga.on_typed_message(
                "object.action-run",
                {"producer_principal": "Thor", "correlation_id": "keep", "seq": i},
            )
        )
    asyncio.run(
        saga.on_typed_message(
            "object.action-run",
            {"producer_principal": "Thor", "correlation_id": "other", "seq": 99},
        )
    )
    slice_entries = saga.replay_for_correlation("keep")
    assert len(slice_entries) == 3
    assert [e.correlation_id for e in slice_entries] == ["keep"] * 3


# ---------------------------------------------------------------------------
# Muninn - context store
# ---------------------------------------------------------------------------


def test_muninn_indexes_conversation_turns() -> None:
    muninn = Muninn()
    asyncio.run(
        muninn.on_typed_message(
            "object.turn",
            {"turn_id": "t1", "question": "hi", "answer": "hello"},
        )
    )
    stored = muninn.get_context("conversation_turns", "t1")
    assert stored is not None
    assert stored["question"] == "hi"


def test_muninn_put_get_generic() -> None:
    muninn = Muninn()
    muninn.put_context("resource_state", "vm-1", {"public": False})
    assert muninn.get_context("resource_state", "vm-1") == {"public": False}
    assert muninn.get_context("resource_state", "missing") is None


# ---------------------------------------------------------------------------
# Mimir - promotion state
# ---------------------------------------------------------------------------


def test_mimir_accepts_and_drains_rule_candidates() -> None:
    mimir = Mimir()
    asyncio.run(
        mimir.on_typed_message(
            "object.rule-candidate",
            {
                "target_rule_id": "storage.public.deny",
                "proposal_kind": "new",
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1
    mimir.promote("storage.public.deny", source="handoff")
    status = mimir.status("storage.public.deny")
    assert status is not None
    assert status.state == "enforce"
    # promoted candidate is removed from the pending list
    assert all(
        c.get("target_rule_id") != "storage.public.deny" for c in mimir.pending_candidates()
    )


def test_mimir_revoke_flips_state_to_retired() -> None:
    mimir = Mimir()
    mimir.promote("r1", source="manual")
    mimir.revoke("r1")
    assert mimir.status("r1").state == "retired"


# ---------------------------------------------------------------------------
# Norns - fingerprint aggregator
# ---------------------------------------------------------------------------


def test_norns_proposes_candidate_after_threshold() -> None:
    norns = Norns(promotion_threshold=3)
    payload = {"fingerprint": "abc123"}
    for _ in range(3):
        asyncio.run(norns.on_typed_message("object.issue", payload))
    assert norns.occurrences("abc123") == 3
    assert len(norns.pending_candidates) == 1
    assert norns.pending_candidates[0]["evidence"]["fingerprint"] == "abc123"


def test_norns_dedups_candidate_proposals() -> None:
    norns = Norns(promotion_threshold=2)
    payload = {"fingerprint": "same-fp"}
    for _ in range(5):
        asyncio.run(norns.on_typed_message("object.issue", payload))
    # Threshold crossed once, proposal must not repeat.
    assert len(norns.pending_candidates) == 1


# ---------------------------------------------------------------------------
# End-to-end via InMemoryBus
# ---------------------------------------------------------------------------


def test_end_to_end_handoff_flow_via_bus() -> None:
    """A handoff escalation flows through Saga -> Norns -> Mimir."""
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    norns = Norns(promotion_threshold=3)
    mimir = Mimir()

    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    fp = compute_fingerprint(
        intent_category="q",
        resource_type="r",
        normalized_selector="s",
        primary_agent="Heimdall",
        failure_reason_code="no_owned_data",
    )

    # Saga escalates three times => Norns crosses threshold, proposes candidate
    for i in range(3):
        saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Heimdall",
            intent_category="q",
            failure_reason_code="no_owned_data",
            correlation_id=f"corr-{i}",
        )
        asyncio.run(
            bus.publish(
                "Saga",
                "object.issue",
                {
                    "producer_principal": "Saga",
                    "correlation_id": f"corr-{i}",
                    "fingerprint": fp,
                },
            )
        )

    # Norns should have produced a candidate.
    assert len(norns.pending_candidates) == 1
    # Publish the candidate to Mimir via the bus (Norns as publisher).
    asyncio.run(
        bus.publish(
            "Norns",
            "object.rule-candidate",
            {
                "producer_principal": "Norns",
                "correlation_id": "corr-cand",
                **norns.pending_candidates[0],
                "target_rule_id": "auto-generated",
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1

    # Mimir promotes; Saga can now close the fingerprinted issue.
    mimir.promote("auto-generated", source="handoff")
    saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/1")
    assert saga.github.issues[fp].open is False
