"""Unit tests for :mod:`fdai.delivery.read_api.postgres_read_model`.

The DB-touching integration test lives in
``tests/persistence/test_postgres_console_read_model.py`` (skipped unless
``FDAI_DATABASE_URL`` is set). This file covers the pure helpers so the
adapter's mappers, cursor logic, and KPI aggregation carry coverage even
on a laptop without Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.read_api.postgres_read_model import (
    PostgresConsoleReadModel,
    PostgresConsoleReadModelConfig,
    _parse_cursor,
    aggregate_kpi,
    row_to_audit_item,
    row_to_hil_queue_item,
)
from fdai.delivery.read_api.read_model import AuditItem


def _row(
    *,
    seq: int = 1,
    event_id: str = "00000000-0000-0000-0000-000000000001",
    correlation_id: str | None = "corr-1",
    actor: str = "fdai",
    action_kind: str = "risk_gate.decide",
    mode: str = "shadow",
    entry: object = None,
    entry_hash: str = "abc",
    previous_hash: str = "0" * 64,
    created_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "seq": seq,
        "event_id": event_id,
        "correlation_id": correlation_id,
        "actor": actor,
        "action_kind": action_kind,
        "mode": mode,
        "entry": entry if entry is not None else {"outcome": "auto", "tier": "T0"},
        "entry_hash": entry_hash,
        "previous_hash": previous_hash,
        "created_at": created_at or datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
    }


# ---------------------------------------------------------------------------
# Config guards
# ---------------------------------------------------------------------------


def test_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresConsoleReadModel(config=PostgresConsoleReadModelConfig(dsn=""))


def test_config_rejects_non_positive_statement_timeout() -> None:
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        PostgresConsoleReadModel(
            config=PostgresConsoleReadModelConfig(dsn="postgresql://x", statement_timeout_ms=0)
        )


def test_config_rejects_non_positive_connect_timeout() -> None:
    with pytest.raises(ValueError, match="connect_timeout_s"):
        PostgresConsoleReadModel(
            config=PostgresConsoleReadModelConfig(dsn="postgresql://x", connect_timeout_s=0)
        )


# ---------------------------------------------------------------------------
# Cursor parsing
# ---------------------------------------------------------------------------


def test_parse_cursor_none_and_empty_return_none() -> None:
    assert _parse_cursor(None) is None
    assert _parse_cursor("") is None


def test_parse_cursor_returns_int_seq() -> None:
    assert _parse_cursor("42") == 42


def test_parse_cursor_rejects_non_int() -> None:
    with pytest.raises(ValueError, match="invalid cursor"):
        _parse_cursor("not-a-number")


# ---------------------------------------------------------------------------
# row_to_audit_item
# ---------------------------------------------------------------------------


def test_row_to_audit_item_maps_dict_entry() -> None:
    item = row_to_audit_item(_row(entry={"outcome": "auto", "tier": "T0"}))
    assert isinstance(item, AuditItem)
    assert item.seq == 1
    assert item.actor == "fdai"
    assert item.action_kind == "risk_gate.decide"
    assert item.mode == "shadow"
    assert item.entry == {"outcome": "auto", "tier": "T0"}
    assert item.recorded_at.startswith("2026-07-13T10:00:00")


def test_row_to_audit_item_decodes_string_entry() -> None:
    item = row_to_audit_item(_row(entry='{"outcome":"auto","tier":"T1"}'))
    assert item.entry == {"outcome": "auto", "tier": "T1"}


def test_row_to_audit_item_rejects_unsupported_entry_type() -> None:
    with pytest.raises(TypeError, match="JSONB"):
        row_to_audit_item(_row(entry=12345))


def test_row_to_audit_item_preserves_null_correlation_id() -> None:
    item = row_to_audit_item(_row(correlation_id=None))
    assert item.correlation_id is None


# ---------------------------------------------------------------------------
# row_to_hil_queue_item
# ---------------------------------------------------------------------------


def _park(
    *,
    approval_id: str = "aid-1",
    status: str = "pending",
    parked_at: str = "2026-07-13T10:00:00+00:00",
    idempotency_key: str = "idem-1",
    action_type: str = "compute.restart_vmss",
    rule_id: str = "azure.compute.stop_condition_required",
    submitter_oid: str = "user-1",
    correlation_id: str | None = "corr-1",
    event_id: str = "00000000-0000-0000-0000-000000000002",
) -> dict[str, object]:
    return {
        "value": {
            "status": status,
            "approval_id": approval_id,
            "action": {
                "idempotency_key": idempotency_key,
                "event_id": event_id,
                "action_type": action_type,
            },
            "rule_id": rule_id,
            "action_type": action_type,
            "submitter_oid": submitter_oid,
            "assignee_oid": None,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "parked_at": parked_at,
            "on_call": None,
        },
        "updated_at": datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
    }


def test_row_to_hil_queue_item_full_shape() -> None:
    item = row_to_hil_queue_item(_park())
    assert item is not None
    assert item.idempotency_key == "idem-1"
    assert item.action_kind == "compute.restart_vmss"
    assert item.event_id == "00000000-0000-0000-0000-000000000002"
    assert item.requested_at == "2026-07-13T10:00:00+00:00"
    assert item.correlation_id == "corr-1"
    assert "rule:azure.compute.stop_condition_required" in item.reason
    assert "submitter:user-1" in item.reason


def test_row_to_hil_queue_item_decodes_string_value() -> None:
    import json as _json

    row = _park()
    row["value"] = _json.dumps(row["value"])
    item = row_to_hil_queue_item(row)
    assert item is not None
    assert item.idempotency_key == "idem-1"


def test_row_to_hil_queue_item_returns_none_on_missing_required_fields() -> None:
    row = _park()
    del row["value"]["approval_id"]  # type: ignore[union-attr]
    assert row_to_hil_queue_item(row) is None


def test_row_to_hil_queue_item_returns_none_on_missing_parked_at() -> None:
    row = _park()
    del row["value"]["parked_at"]  # type: ignore[union-attr]
    assert row_to_hil_queue_item(row) is None


def test_row_to_hil_queue_item_falls_back_action_event_id_placeholder() -> None:
    row = _park()
    row["value"]["action"] = {"idempotency_key": "idem-1"}  # type: ignore[union-attr]
    item = row_to_hil_queue_item(row)
    assert item is not None
    assert item.event_id == "00000000-0000-0000-0000-000000000000"
    assert item.action_kind == "compute.restart_vmss"  # falls back to top-level action_type


def test_row_to_hil_queue_item_returns_none_on_invalid_json_string() -> None:
    row = {"value": "{not-json}", "updated_at": datetime(2026, 7, 13, tzinfo=UTC)}
    assert row_to_hil_queue_item(row) is None


def test_row_to_hil_queue_item_returns_none_on_wrong_value_type() -> None:
    row = {"value": 12345, "updated_at": datetime(2026, 7, 13, tzinfo=UTC)}
    assert row_to_hil_queue_item(row) is None


def test_row_to_hil_queue_item_reason_defaults_when_no_rule_or_submitter() -> None:
    row = _park(rule_id="", submitter_oid="")
    # empty strings pass through the value fields but the projection guards
    # them out, so we get the fallback reason
    row["value"]["rule_id"] = ""  # type: ignore[union-attr]
    row["value"]["submitter_oid"] = ""  # type: ignore[union-attr]
    item = row_to_hil_queue_item(row)
    assert item is not None
    assert item.reason == "hil.requested"


# ---------------------------------------------------------------------------
# aggregate_kpi
# ---------------------------------------------------------------------------


def test_aggregate_kpi_empty_returns_zero_shares() -> None:
    kpi = aggregate_kpi([], hil_pending=3)
    assert kpi.event_count == 0
    assert kpi.shadow_share == 0.0
    assert kpi.enforce_share == 0.0
    assert kpi.hil_pending == 3
    assert kpi.by_action_kind == {}
    assert kpi.by_outcome == {}
    assert kpi.by_tier == {}
    assert kpi.last_recorded_at is None


def test_aggregate_kpi_counts_modes_kinds_outcomes_tiers() -> None:
    rows = [
        {
            "action_kind": "risk_gate.decide",
            "mode": "shadow",
            "entry": {"outcome": "auto", "tier": "T0"},
            "created_at": datetime(2026, 7, 13, 10, 0, tzinfo=UTC),
        },
        {
            "action_kind": "risk_gate.decide",
            "mode": "enforce",
            "entry": {"outcome": "auto", "tier": "T0"},
            "created_at": datetime(2026, 7, 13, 10, 5, tzinfo=UTC),
        },
        {
            "action_kind": "hil.requested",
            "mode": "shadow",
            "entry": {"outcome": "hil"},
            "created_at": datetime(2026, 7, 13, 10, 10, tzinfo=UTC),
        },
    ]
    # rows arrive newest-first from `ORDER BY seq DESC`; last iteration wins
    # for last_recorded_at, so we pass them in DB order:
    kpi = aggregate_kpi(list(reversed(rows)), hil_pending=1)
    assert kpi.event_count == 3
    assert kpi.by_action_kind == {"risk_gate.decide": 2, "hil.requested": 1}
    assert kpi.by_outcome == {"auto": 2, "hil": 1}
    assert kpi.by_tier == {"T0": 2}
    assert kpi.shadow_share == pytest.approx(2 / 3)
    assert kpi.enforce_share == pytest.approx(1 / 3)
    assert kpi.hil_pending == 1


def test_aggregate_kpi_handles_string_entry_and_missing_fields() -> None:
    rows = [
        {
            "action_kind": "risk_gate.decide",
            "mode": "shadow",
            "entry": '{"outcome":"auto","tier":"T2"}',
            "created_at": None,
        },
        {
            "action_kind": "unknown",
            "mode": "shadow",
            "entry": {},  # no outcome / tier
            "created_at": None,
        },
        {
            "action_kind": "malformed",
            "mode": "",
            "entry": 12345,  # unsupported type -> defaults
            "created_at": None,
        },
    ]
    kpi = aggregate_kpi(rows, hil_pending=0)
    assert kpi.event_count == 3
    assert kpi.by_tier == {"T2": 1}
    assert kpi.by_outcome == {"auto": 1, "unknown": 2}
    # Two shadow, zero enforce, one unrecognized mode.
    assert kpi.shadow_share == pytest.approx(2 / 3)
    assert kpi.enforce_share == 0.0
