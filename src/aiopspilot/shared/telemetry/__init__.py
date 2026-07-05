"""Structured logging, tracing, metric helpers.

Public API. Every subsystem that emits telemetry imports from here — never
from the sub-modules directly — so the module surface can change without
touching consumers.
"""

from .correlation import current_correlation_id, with_correlation
from .logging import JsonFormatter, configure_logging, get_logger, log_extra
from .metrics import configure_metrics, get_meter, in_memory_reader
from .metrics_derivation import DashboardMetrics, derive_dashboard_metrics
from .setup import configure_telemetry
from .tracing import configure_tracing, get_tracer

__all__ = [
    "DashboardMetrics",
    "JsonFormatter",
    "configure_logging",
    "configure_metrics",
    "configure_telemetry",
    "configure_tracing",
    "current_correlation_id",
    "derive_dashboard_metrics",
    "get_logger",
    "get_meter",
    "get_tracer",
    "in_memory_reader",
    "log_extra",
    "with_correlation",
]
