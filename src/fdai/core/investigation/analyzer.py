"""Per-resource analyzers - the ``ResourceAnalyzer`` seam + threshold base.

Each analyzer inspects **one resource kind** (Application Gateway, MySQL,
Azure OpenAI, AKS, API Management, ...) over a time window and returns
:class:`AnalyzerFinding` observations. Analyzers are deterministic-first:
the reference :class:`ThresholdAnalyzer` evaluates declared metric
thresholds against a :class:`MetricSnapshot` and never calls an LLM.

The snapshot is read through the :class:`MetricProvider` seam so the same
analyzer runs against a fixture in tests and against Azure Monitor / ARG in
production (the concrete provider lives under ``delivery/azure`` and
implements this exact Protocol). Analyzers are read-only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.investigation.contract import AnalyzerFinding
from fdai.shared.contracts.models import Severity


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    """A point-in-time metric read for one resource.

    ``metrics`` maps a metric name to its observed value over the window
    (already reduced - e.g. the max CPU %, the p95 latency, the 5xx rate).
    ``observed_at`` is when the window closed. ``metadata`` is neutral and
    never carries secrets.
    """

    resource_ref: str
    resource_kind: str
    observed_at: datetime
    metrics: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class MetricProvider(Protocol):
    """Read a reduced metric snapshot for one resource over a window."""

    async def snapshot(
        self, *, resource_ref: str, resource_kind: str, window_seconds: float
    ) -> MetricSnapshot:
        """Return the reduced metrics for ``resource_ref`` over the window."""
        ...


@runtime_checkable
class ResourceAnalyzer(Protocol):
    """Analyze one resource kind and emit findings."""

    @property
    def resource_kind(self) -> str:
        """The single resource kind this analyzer understands."""
        ...

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        """Return findings for ``resource_ref`` (empty when healthy)."""
        ...


class Comparison(StrEnum):
    """How a threshold compares an observed value to its bound."""

    GTE = "gte"
    LTE = "lte"


@dataclass(frozen=True, slots=True)
class Threshold:
    """One deterministic metric threshold.

    Fires a finding when ``metric`` breaches ``bound`` in the ``compare``
    direction. ``remediation_ref`` names the ActionType the breach implies
    (if any) - the finding proposes, the risk gate decides.
    """

    metric: str
    compare: Comparison
    bound: float
    severity: Severity
    signal: str
    observation: str
    remediation_ref: str | None = None

    def breached(self, value: float) -> bool:
        """True iff ``value`` breaches this threshold."""
        if self.compare is Comparison.GTE:
            return value >= self.bound
        return value <= self.bound


class ThresholdAnalyzer:
    """Reference analyzer: evaluate declared thresholds over a snapshot.

    Deterministic and network-free (given a :class:`MetricProvider`). A
    fork can register richer analyzers for the same kind by binding a
    different :class:`ResourceAnalyzer`; this one covers the demo's
    metric-threshold cases exactly.
    """

    __slots__ = ("_kind", "_provider", "_thresholds")

    def __init__(
        self,
        *,
        resource_kind: str,
        provider: MetricProvider,
        thresholds: Sequence[Threshold],
    ) -> None:
        if not resource_kind:
            raise ValueError("ThresholdAnalyzer.resource_kind MUST be non-empty")
        self._kind = resource_kind
        self._provider = provider
        self._thresholds = tuple(thresholds)

    @property
    def resource_kind(self) -> str:
        return self._kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        snapshot = await self._provider.snapshot(
            resource_ref=resource_ref,
            resource_kind=self._kind,
            window_seconds=window_seconds,
        )
        findings: list[AnalyzerFinding] = []
        for threshold in self._thresholds:
            if threshold.metric not in snapshot.metrics:
                continue
            value = snapshot.metrics[threshold.metric]
            if not threshold.breached(value):
                continue
            findings.append(
                AnalyzerFinding(
                    resource_ref=resource_ref,
                    resource_kind=self._kind,
                    signal=threshold.signal,
                    observation=threshold.observation,
                    severity=threshold.severity,
                    occurred_at=snapshot.observed_at,
                    evidence_refs=(f"{threshold.metric}={value:g}",),
                    remediation_ref=threshold.remediation_ref,
                )
            )
        return tuple(findings)


__all__ = [
    "Comparison",
    "MetricProvider",
    "MetricSnapshot",
    "ResourceAnalyzer",
    "Threshold",
    "ThresholdAnalyzer",
]
