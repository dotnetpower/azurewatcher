"""Detection signals - anomaly / forecast finding producers.

See [observability](../../../../docs/roadmap/rules-and-detection/observability-and-detection.md).
Detectors are out-of-band producers: they emit normalized findings that
re-enter ``event-ingest`` and flow through the same trust-router ->
risk-gate path, never a side channel.
"""

from __future__ import annotations

from fdai.core.detection.anomaly import AnomalyFinding, MetricAnomalyDetector
from fdai.core.detection.composite import (
    CompositeAnomalyDetector,
    CompositeAnomalyFinding,
)
from fdai.core.detection.forecast import ForecastFinding, LinearForecastDetector
from fdai.core.detection.forecast_band import ForecastBand, prediction_band
from fdai.core.detection.metric_source import MetricSeries, MetricSeriesSource
from fdai.core.detection.seasonal import PhaseFn, SeasonalAnomalyDetector
from fdai.core.detection.series import MetricSample

__all__ = [
    "AnomalyFinding",
    "CompositeAnomalyDetector",
    "CompositeAnomalyFinding",
    "ForecastBand",
    "ForecastFinding",
    "LinearForecastDetector",
    "MetricAnomalyDetector",
    "MetricSample",
    "MetricSeries",
    "MetricSeriesSource",
    "PhaseFn",
    "SeasonalAnomalyDetector",
    "prediction_band",
]
