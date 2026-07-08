"""Detection signals - anomaly / forecast finding producers.

See [observability-and-detection.md](../../../../docs/roadmap/observability-and-detection.md).
Detectors are out-of-band producers: they emit normalized findings that
re-enter ``event-ingest`` and flow through the same trust-router ->
risk-gate path, never a side channel.
"""

from __future__ import annotations

from fdai.core.detection.anomaly import AnomalyFinding, MetricAnomalyDetector
from fdai.core.detection.forecast import ForecastFinding, LinearForecastDetector
from fdai.core.detection.seasonal import PhaseFn, SeasonalAnomalyDetector
from fdai.core.detection.series import MetricSample

__all__ = [
    "AnomalyFinding",
    "ForecastFinding",
    "LinearForecastDetector",
    "MetricAnomalyDetector",
    "MetricSample",
    "PhaseFn",
    "SeasonalAnomalyDetector",
]
