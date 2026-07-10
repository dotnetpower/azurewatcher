"""Tests for the on-demand cross-resource investigation module."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.investigation import (
    KIND_AKS,
    KIND_APP_GATEWAY,
    KIND_AZURE_OPENAI,
    KIND_MYSQL,
    InvestigationCoordinator,
    InvestigationOutcome,
    InvestigationRequest,
    MetricSnapshot,
    Priority,
    default_analyzers,
)
from fdai.core.investigation.analyzer import (
    Comparison,
    Threshold,
    ThresholdAnalyzer,
)
from fdai.shared.contracts.models import Severity

_BASE = datetime(2026, 7, 10, 17, 50, tzinfo=UTC)


class _FixtureMetricProvider:
    """Deterministic metric provider driven by a static snapshot table."""

    def __init__(self, table: Mapping[str, Mapping[str, float]]) -> None:
        self._table = table
        self._clock = _BASE

    async def snapshot(
        self, *, resource_ref: str, resource_kind: str, window_seconds: float
    ) -> MetricSnapshot:
        return MetricSnapshot(
            resource_ref=resource_ref,
            resource_kind=resource_kind,
            observed_at=self._clock,
            metrics=dict(self._table.get(resource_ref, {})),
        )


class _RaisingProvider:
    async def snapshot(
        self, *, resource_ref: str, resource_kind: str, window_seconds: float
    ) -> MetricSnapshot:
        raise RuntimeError("metric backend unreachable")


def _demo_table() -> dict[str, dict[str, float]]:
    return {
        "appgw-1": {
            "backend_first_byte_response_time_ms": 5_500.0,
            "healthy_host_count": 0.3,
        },
        "mysql-1": {"cpu_percent": 99.8, "active_connections": 120.0},
        "aoai-1": {"http_429_rate": 0.42, "request_surge_ratio": 54.0},
        "aks-1": {"node_cpu_percent": 88.0},
    }


def _demo_request(budget: float = 300.0) -> InvestigationRequest:
    return InvestigationRequest(
        requested_by="operator@example.com",
        resources=(
            ("appgw-1", KIND_APP_GATEWAY),
            ("mysql-1", KIND_MYSQL),
            ("aoai-1", KIND_AZURE_OPENAI),
            ("aks-1", KIND_AKS),
        ),
        budget_seconds=budget,
    )


@pytest.mark.asyncio
async def test_completed_investigation_produces_findings_and_recommendations() -> None:
    provider = _FixtureMetricProvider(_demo_table())
    coordinator = InvestigationCoordinator(analyzers=default_analyzers(provider))

    report = await coordinator.investigate(_demo_request())

    assert report.outcome is InvestigationOutcome.COMPLETED
    assert report.analyzer_errors == ()
    # Every unhealthy resource yields at least one finding.
    kinds_with_findings = {f.resource_kind for f in report.findings}
    assert {KIND_APP_GATEWAY, KIND_MYSQL, KIND_AZURE_OPENAI, KIND_AKS} <= kinds_with_findings
    # The AppGW healthy-host collapse is CRITICAL -> ranked P1.
    p1 = [r for r in report.recommendations if r.priority is Priority.P1]
    assert any(r.resource_ref == "appgw-1" for r in p1)
    assert report.root_cause is not None
    assert report.within_budget is True


@pytest.mark.asyncio
async def test_recommendations_sorted_p1_first() -> None:
    provider = _FixtureMetricProvider(_demo_table())
    coordinator = InvestigationCoordinator(analyzers=default_analyzers(provider))

    report = await coordinator.investigate(_demo_request())

    ranks = [r.priority for r in report.recommendations]
    # P1 entries never appear after a P2/P3 entry.
    order = {Priority.P1: 0, Priority.P2: 1, Priority.P3: 2}
    assert ranks == sorted(ranks, key=lambda p: order[p])


@pytest.mark.asyncio
async def test_timeline_is_time_ordered() -> None:
    provider = _FixtureMetricProvider(_demo_table())
    coordinator = InvestigationCoordinator(analyzers=default_analyzers(provider))

    report = await coordinator.investigate(_demo_request())

    times = [entry.occurred_at for entry in report.timeline]
    assert times == sorted(times)


@pytest.mark.asyncio
async def test_healthy_resources_yield_no_findings() -> None:
    provider = _FixtureMetricProvider(
        {"appgw-1": {"backend_first_byte_response_time_ms": 50.0, "healthy_host_count": 5.0}}
    )
    coordinator = InvestigationCoordinator(analyzers=default_analyzers(provider))

    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="op@example.com",
            resources=(("appgw-1", KIND_APP_GATEWAY),),
        )
    )

    assert report.outcome is InvestigationOutcome.COMPLETED
    assert report.findings == ()
    assert report.recommendations == ()
    assert report.root_cause is None


@pytest.mark.asyncio
async def test_analyzer_failure_marks_partial() -> None:
    coordinator = InvestigationCoordinator(analyzers=default_analyzers(_RaisingProvider()))

    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="op@example.com",
            resources=(("mysql-1", KIND_MYSQL),),
        )
    )

    assert report.outcome is InvestigationOutcome.PARTIAL
    assert report.analyzer_errors and report.analyzer_errors[0][0] == "mysql-1"
    assert report.findings == ()


@pytest.mark.asyncio
async def test_no_analyzer_for_kind_abstains() -> None:
    provider = _FixtureMetricProvider(_demo_table())
    coordinator = InvestigationCoordinator(analyzers=default_analyzers(provider))

    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="op@example.com",
            resources=(("unknown-1", "cosmos_db"),),
        )
    )

    assert report.outcome is InvestigationOutcome.ABSTAINED
    assert report.findings == ()


@pytest.mark.asyncio
async def test_budget_exceeded_when_monotonic_advances_past_budget() -> None:
    provider = _FixtureMetricProvider(_demo_table())
    ticks = iter([0.0, 500.0])  # start, end -> 500s elapsed
    coordinator = InvestigationCoordinator(
        analyzers=default_analyzers(provider),
        monotonic=lambda: next(ticks),
    )

    report = await coordinator.investigate(_demo_request(budget=300.0))

    assert report.outcome is InvestigationOutcome.BUDGET_EXCEEDED
    assert report.within_budget is False
    assert report.elapsed_seconds == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_kpi_view_is_derived() -> None:
    provider = _FixtureMetricProvider(_demo_table())
    ticks = iter([0.0, 42.0])
    coordinator = InvestigationCoordinator(
        analyzers=default_analyzers(provider),
        monotonic=lambda: next(ticks),
    )

    report = await coordinator.investigate(_demo_request())
    kpi = report.kpi()

    assert kpi["investigation.latency_seconds"] == pytest.approx(42.0)
    assert kpi["investigation.within_budget"] == 1.0
    assert kpi["investigation.resource_count"] == 4.0


def test_threshold_breach_direction() -> None:
    gte = Threshold(
        metric="m",
        compare=Comparison.GTE,
        bound=10.0,
        severity=Severity.HIGH,
        signal="s",
        observation="o",
    )
    lte = Threshold(
        metric="m",
        compare=Comparison.LTE,
        bound=1.0,
        severity=Severity.CRITICAL,
        signal="s",
        observation="o",
    )
    assert gte.breached(10.0) is True
    assert gte.breached(9.9) is False
    assert lte.breached(1.0) is True
    assert lte.breached(1.1) is False


@pytest.mark.asyncio
async def test_correlation_statements_link_distinct_resources() -> None:
    # Two analyzers with distinct kinds but staggered timestamps.
    aks = ThresholdAnalyzer(
        resource_kind=KIND_AKS,
        provider=_StaggeredProvider(_BASE),
        thresholds=(
            Threshold(
                metric="node_cpu_percent",
                compare=Comparison.GTE,
                bound=80.0,
                severity=Severity.MEDIUM,
                signal="node_cpu",
                observation="AKS CPU high",
            ),
        ),
    )
    mysql = ThresholdAnalyzer(
        resource_kind=KIND_MYSQL,
        provider=_StaggeredProvider(_BASE + timedelta(minutes=10)),
        thresholds=(
            Threshold(
                metric="cpu_percent",
                compare=Comparison.GTE,
                bound=90.0,
                severity=Severity.HIGH,
                signal="db_cpu",
                observation="MySQL CPU saturated",
            ),
        ),
    )
    coordinator = InvestigationCoordinator(analyzers=(aks, mysql))

    report = await coordinator.investigate(
        InvestigationRequest(
            requested_by="op@example.com",
            resources=(("a", KIND_AKS), ("b", KIND_MYSQL)),
        )
    )

    assert report.correlation
    assert "preceded" in report.correlation[0]


class _StaggeredProvider:
    def __init__(self, at: datetime) -> None:
        self._at = at

    async def snapshot(
        self, *, resource_ref: str, resource_kind: str, window_seconds: float
    ) -> MetricSnapshot:
        metrics = {"node_cpu_percent": 90.0} if resource_kind == KIND_AKS else {"cpu_percent": 99.0}
        return MetricSnapshot(
            resource_ref=resource_ref,
            resource_kind=resource_kind,
            observed_at=self._at,
            metrics=metrics,
        )
