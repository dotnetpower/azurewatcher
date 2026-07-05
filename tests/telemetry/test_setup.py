"""End-to-end telemetry setup from AppConfig."""

from __future__ import annotations

from aiopspilot.shared.config import AppConfig
from aiopspilot.shared.telemetry import (
    configure_telemetry,
    get_meter,
    get_tracer,
    in_memory_reader,
)


def test_configure_telemetry_wires_everything(app_config: AppConfig) -> None:
    configure_telemetry(app_config)
    tracer = get_tracer("aiopspilot.tests.setup")
    meter = get_meter("aiopspilot.tests.setup")

    with tracer.start_as_current_span("smoke"):
        counter = meter.create_counter("aw.tests.smoke")
        counter.add(1)

    # In-memory reader is installed (day-zero exporter path).
    reader = in_memory_reader()
    assert reader is not None


def test_configure_telemetry_is_idempotent(app_config: AppConfig) -> None:
    # Calling twice must not raise — the underlying OTel API only accepts
    # one provider install and our wrappers guard against duplicates.
    configure_telemetry(app_config)
    configure_telemetry(app_config)
