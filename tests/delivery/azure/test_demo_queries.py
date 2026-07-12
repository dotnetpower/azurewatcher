"""Tests for the SRE demo five-metric capture KQL template catalog."""

from __future__ import annotations

from fdai.delivery.azure.demo_queries import (
    METRIC_HOST_CPU_PERCENT,
    METRIC_HOST_MEMORY_AVAILABLE_PCT,
    METRIC_POD_RESTARTS,
    METRIC_REQUEST_FAILURE_RATE,
    METRIC_ROLLOUT_STALL_SECONDS,
    sre_demo_capture_queries,
)
from fdai.delivery.azure.metric_logs import MetricKqlTemplate

_EXPECTED = {
    METRIC_HOST_CPU_PERCENT,
    METRIC_HOST_MEMORY_AVAILABLE_PCT,
    METRIC_POD_RESTARTS,
    METRIC_REQUEST_FAILURE_RATE,
    METRIC_ROLLOUT_STALL_SECONDS,
}


def test_catalog_contains_five_demo_metrics() -> None:
    got = set(sre_demo_capture_queries().keys())
    assert got == _EXPECTED, f"extra={got - _EXPECTED}, missing={_EXPECTED - got}"


def test_every_template_is_metric_kql_template() -> None:
    for template in sre_demo_capture_queries().values():
        assert isinstance(template, MetricKqlTemplate)


def test_no_template_interpolates_untrusted_input() -> None:
    """Injection guard: no {}, %, or shell metachars in the KQL body."""
    for name, template in sre_demo_capture_queries().items():
        # KQL is static text; presence of '{' or '%' would indicate a
        # format string that could ever have carried caller input.
        assert "{" not in template.kql, f"{name} KQL uses '{{' formatting"
        assert "%" not in template.kql, f"{name} KQL uses '%' formatting"


def test_every_template_declares_value_and_labels() -> None:
    """The metric adapter requires value_column + non-empty label_columns."""
    for name, template in sre_demo_capture_queries().items():
        assert template.value_column, f"{name}: value_column missing"
        assert "resource_id" in template.label_columns, (
            f"{name}: label_columns must include 'resource_id' "
            f"(shared label the adapter filters on)"
        )


def test_catalog_view_is_read_only() -> None:
    catalog = sre_demo_capture_queries()
    try:
        catalog["injected"] = _catalog_sentinel()  # type: ignore[index]
    except TypeError:
        return
    raise AssertionError("sre_demo_capture_queries() must be read-only")


def _catalog_sentinel() -> MetricKqlTemplate:
    return MetricKqlTemplate(
        kql="X | project TimeGenerated, v = 0.0, resource_id = 'r'",
        value_column="v",
        label_columns=("resource_id",),
    )
