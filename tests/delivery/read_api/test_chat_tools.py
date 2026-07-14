"""Deterministic Command Deck read-tool tests."""

from __future__ import annotations

import asyncio

from fdai.delivery.read_api.read_model import HilQueueItem, InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat_tools import ReadModelChatTools


def _model() -> InMemoryConsoleReadModel:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "correlation_id": "corr-1",
            "outcome": "auto",
            "tier": "t0",
        },
        actor="Thor",
        action_kind="ops.restart-service",
        mode="shadow",
    )
    model.record_hil_pending(
        HilQueueItem(
            idempotency_key="idem-1",
            event_id="event-2",
            action_kind="ops.failover-primary",
            reason="high risk",
            requested_at="2026-07-15T00:00:00Z",
            correlation_id="corr-2",
        )
    )
    return model


def test_resolves_kpi_hil_and_audit_from_read_model() -> None:
    tools = ReadModelChatTools(_model())

    kpi = asyncio.run(tools.resolve("show KPI"))
    hil = asyncio.run(tools.resolve("pending approvals"))
    audit = asyncio.run(tools.resolve("latest audit log"))

    assert kpi is not None and kpi["result"]["event_count"] == 1
    assert hil is not None and hil["result"]["total"] == 1
    assert audit is not None and audit["result"]["items"][0]["actor"] == "Thor"


def test_unmatched_question_does_not_call_a_tool() -> None:
    assert asyncio.run(ReadModelChatTools(_model()).resolve("explain T2")) is None


def test_explicit_agent_request_precedes_generic_tool() -> None:
    assert asyncio.run(ReadModelChatTools(_model()).resolve("Ask Var for approval backlog")) is None
