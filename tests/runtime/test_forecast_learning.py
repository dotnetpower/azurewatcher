from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from fdai.delivery.forecast_tick_cli import forecast_tick_id
from fdai.runtime.forecast_learning import (
    build_forecast_learning_runtime,
    parse_forecast_targets,
)
from fdai.shared.providers.metric import NoopMetricProvider


def _target() -> dict[str, object]:
    return {
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "scorer_version": "1.0.0",
        "access_scope_digest": "a" * 64,
        "resource_ref": "resource-1",
        "metric": "capacity_percent",
        "threshold": 90.0,
        "horizon_seconds": 3600,
        "lookback_seconds": 900,
        "telemetry_grace_seconds": 300,
    }


def test_forecast_runtime_is_disabled_without_targets() -> None:
    assert parse_forecast_targets(None) == ()
    assert (
        build_forecast_learning_runtime(
            dsn=None,
            targets_json=None,
            metric_provider=NoopMetricProvider(),
        )
        is None
    )


def test_forecast_runtime_requires_store_when_targets_exist() -> None:
    with pytest.raises(RuntimeError, match="STATE_STORE_DSN"):
        build_forecast_learning_runtime(
            dsn=None,
            targets_json=json.dumps([_target()]),
            metric_provider=NoopMetricProvider(),
        )


def test_forecast_targets_reject_duplicates_and_malformed_json() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        parse_forecast_targets("not-json")
    with pytest.raises(ValueError, match="duplicate"):
        parse_forecast_targets(json.dumps([_target(), _target()]))


def test_forecast_tick_identity_is_stable_per_minute() -> None:
    first = datetime(2026, 7, 23, 15, 0, 1, tzinfo=UTC)
    second = datetime(2026, 7, 23, 15, 0, 59, tzinfo=UTC)
    assert forecast_tick_id(first) == forecast_tick_id(second)
