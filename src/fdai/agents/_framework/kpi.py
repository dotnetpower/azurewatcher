"""KPI collector primitives (Wave 8).

Every pantheon agent MUST emit its declared KPIs into the measurement
pipeline (`docs/roadmap/architecture/goals-and-metrics.md`). Wave 8 ships a simple
in-memory collector so shadow-mode promotion gates can evaluate
against the KPI table in `agent-pantheon.md` \u00a74.2 without a real
telemetry backend. Fork adapters swap in the actual sink (Application
Insights, Prometheus).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KpiSample:
    agent: str
    metric: str
    value: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class KpiCollector:
    """In-memory KPI sink. Deterministic; test-friendly."""

    samples: list[KpiSample] = field(default_factory=list)

    def record(
        self,
        *,
        agent: str,
        metric: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> KpiSample:
        sample = KpiSample(agent=agent, metric=metric, value=value, tags=dict(tags or {}))
        self.samples.append(sample)
        return sample

    def latest(self, *, agent: str, metric: str) -> KpiSample | None:
        for sample in reversed(self.samples):
            if sample.agent == agent and sample.metric == metric:
                return sample
        return None

    def all_for(self, agent: str) -> tuple[KpiSample, ...]:
        return tuple(s for s in self.samples if s.agent == agent)


@dataclass
class PromotionGateThreshold:
    metric: str
    min: float | None = None
    max: float | None = None

    def evaluate(self, sample: KpiSample | None) -> bool:
        if sample is None:
            return False
        if self.min is not None and sample.value < self.min:
            return False
        if self.max is not None and sample.value > self.max:
            return False
        return True


@dataclass
class PromotionGate:
    workflow_id: str
    thresholds: tuple[PromotionGateThreshold, ...]

    def evaluate(self, collector: KpiCollector) -> tuple[bool, dict[str, bool]]:
        outcomes: dict[str, bool] = {}
        overall = True
        for th in self.thresholds:
            agent, metric = th.metric.split(".", 1) if "." in th.metric else ("", th.metric)
            sample = collector.latest(agent=agent, metric=metric) if agent else None
            passed = th.evaluate(sample)
            outcomes[th.metric] = passed
            overall = overall and passed
        return overall, outcomes


__all__ = ["KpiCollector", "KpiSample", "PromotionGate", "PromotionGateThreshold"]
