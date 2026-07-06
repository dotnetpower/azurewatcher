"""One-call telemetry initialization for the composition root.

Wires up JSON logging, OpenTelemetry tracing (console exporter), and OTel
metrics (in-memory reader) using values pulled from :class:`AppConfig`.
Callers do NOT need to configure the individual sub-systems - they call
:func:`configure_telemetry` once and inherit the rest.
"""

from __future__ import annotations

import logging

from aiopspilot.shared.config.models import AppConfig

from .logging import configure_logging
from .metrics import configure_metrics
from .tracing import configure_tracing

_SERVICE_NAME = "aiopspilot"


def configure_telemetry(config: AppConfig, *, level: int = logging.INFO) -> None:
    """Wire logging + tracing + metrics from :class:`AppConfig`.

    Idempotent at the sub-system layer - each of ``configure_logging``,
    ``configure_tracing``, and ``configure_metrics`` guards against
    repeated installation.
    """
    configure_logging(level=level)
    configure_tracing(service_name=_SERVICE_NAME, env=config.runtime.env)
    configure_metrics(service_name=_SERVICE_NAME, env=config.runtime.env)


__all__ = ["configure_telemetry"]
