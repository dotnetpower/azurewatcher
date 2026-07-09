"""MetricBurnRateSource - bridge the MetricProvider seam to the evaluator.

Covers the fail-closed contract (empty / inconsistent telemetry abstains) and
the happy paths (breach when both windows burn hot, no breach when cool).
Uses the in-memory ``StaticMetricProvider`` and the upstream-default
``NoopMetricProvider`` so no network or real backend is involved. Async tests
run under ``asyncio_mode = "auto"`` (see pyproject.toml); no per-test marker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.slo import MetricBurnRateSource
from fdai.core.slo.models import SLI, SLO, BurnRateAlertDef, SLIKind
from fdai.shared.providers.metric import (
    MetricPoint,
    NoopMetricProvider,
    StaticMetricProvider,
)

_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _slo(*, labels: dict[str, str] | None = None) -> SLO:
    return SLO(
        id="api.checkout.availability",
        objective_ratio=0.99,  # allowed bad ratio = 0.01
        window_days=28,
        sli=SLI(
            kind=SLIKind.AVAILABILITY,
            good_query="good_events",
            total_query="total_events",
            labels=labels or {},
        ),
        burn_rate_alerts=(
            BurnRateAlertDef(
                name="fast-burn",
                short_window_minutes=5,
                long_window_minutes=60,
                burn_rate_threshold=1.0,
            ),
        ),
    )


def _point(metric_name: str, value: float, *, labels: dict[str, str] | None = None) -> MetricPoint:
    # One minute before _NOW, so the sample falls inside both the 5-min and
    # the 60-min windows.
    return MetricPoint(
        metric_name=metric_name,
        at=_NOW - timedelta(minutes=1),
        value=value,
        labels=labels or {},
    )


# ---------------------------------------------------------------------------
# Fail-closed: no data / inconsistent data abstains
# ---------------------------------------------------------------------------


async def test_noop_provider_reports_insufficient_data() -> None:
    source = MetricBurnRateSource(NoopMetricProvider())
    result = await source.evaluate(_slo(), now=_NOW)
    assert result.insufficient_data is True
    assert result.breaches == ()
    assert result.breached is False


async def test_zero_total_reports_insufficient_data() -> None:
    provider = StaticMetricProvider([_point("good_events", 0.0), _point("total_events", 0.0)])
    result = await MetricBurnRateSource(provider).evaluate(_slo(), now=_NOW)
    assert result.insufficient_data is True


async def test_good_exceeds_total_is_inconsistent_and_abstains() -> None:
    provider = StaticMetricProvider([_point("good_events", 1000.0), _point("total_events", 500.0)])
    result = await MetricBurnRateSource(provider).evaluate(_slo(), now=_NOW)
    assert result.insufficient_data is True
    assert result.breaches == ()


# ---------------------------------------------------------------------------
# Happy paths: breach vs no breach
# ---------------------------------------------------------------------------


async def test_hot_burn_in_both_windows_breaches() -> None:
    # bad_ratio = 20/1000 = 0.02; rate = 0.02 / 0.01 = 2.0 >= threshold 1.0.
    provider = StaticMetricProvider([_point("good_events", 980.0), _point("total_events", 1000.0)])
    result = await MetricBurnRateSource(provider).evaluate(_slo(), now=_NOW)
    assert result.insufficient_data is False
    assert result.breached is True
    assert result.breaches[0].alert.slo_id == "api.checkout.availability"


async def test_cool_burn_does_not_breach() -> None:
    # bad_ratio = 1/1000 = 0.001; rate = 0.1 < threshold 1.0.
    provider = StaticMetricProvider([_point("good_events", 999.0), _point("total_events", 1000.0)])
    result = await MetricBurnRateSource(provider).evaluate(_slo(), now=_NOW)
    assert result.insufficient_data is False
    assert result.breached is False


async def test_no_burn_rate_alerts_yields_empty_non_insufficient() -> None:
    slo = SLO(
        id="api.no-alerts",
        objective_ratio=0.99,
        window_days=28,
        sli=SLI(kind=SLIKind.AVAILABILITY, good_query="g", total_query="t"),
    )
    result = await MetricBurnRateSource(NoopMetricProvider()).evaluate(slo, now=_NOW)
    assert result.insufficient_data is False
    assert result.breaches == ()


async def test_labels_prefilter_is_passed_through() -> None:
    # Only samples carrying the SLI label are counted; an unlabeled sample is
    # filtered out by the provider, leaving zero total -> insufficient.
    provider = StaticMetricProvider(
        [
            _point("good_events", 980.0),
            _point("total_events", 1000.0),
        ]
    )
    result = await MetricBurnRateSource(provider).evaluate(
        _slo(labels={"resource_id": "vm-01"}), now=_NOW
    )
    assert result.insufficient_data is True
