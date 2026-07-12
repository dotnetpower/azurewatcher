"""Reference KQL query templates for the SRE demo five-metric capture.

The SRE demo pack (see
``docs/internals/sre-demo-scenarios-08-fdai-coverage.md`` C.5 and C.11)
captures **five metrics** at each incident so the coverage matrix and the
harness agree on what the demo asserts VALIDATED against:

- ``host.cpu.percent``            - VM guest-OS CPU (scenario S5).
- ``host.memory.available_pct``   - VM guest-OS free memory (scenario S6, C4).
- ``k8s.pod.restarts``            - AKS pod restart count (scenarios S1, C2).
- ``http.server.request.failure_rate`` - request failure rate (scenario S4).
- ``k8s.deployment.rollout_stall_seconds`` - stall seconds past the
  progress deadline (scenario S12).

Every template is **author-controlled configuration**, never derived from
untrusted input. Untrusted labels (``resource_id``, ``deployment``, ...)
stay out of the KQL body and are filtered in memory by
:class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsMetricProvider`
- this matches the metric adapter's KQL-injection contract.

These templates are the CSP-neutral **catalog** the metric adapter is
initialized with at the composition root. A fork MAY override a template
(different table, different KDL predicate) but MUST keep the returned
``value_column``, ``timestamp_column``, and ``label_columns`` shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.azure.metric_logs import MetricKqlTemplate

# CSP-neutral metric names shared with the analyzer / detector layer.
METRIC_HOST_CPU_PERCENT = "host.cpu.percent"
METRIC_HOST_MEMORY_AVAILABLE_PCT = "host.memory.available_pct"
METRIC_POD_RESTARTS = "k8s.pod.restarts"
METRIC_REQUEST_FAILURE_RATE = "http.server.request.failure_rate"
METRIC_ROLLOUT_STALL_SECONDS = "k8s.deployment.rollout_stall_seconds"

# The five-metric capture (C.5) plus S12's rollout-stall probe. Each
# template targets one Log Analytics table and returns exactly the
# columns the metric adapter parses. Every template's KQL is static text
# (no interpolation, no format strings) - the ONLY variable input is the
# ``timespan`` sent as the server-side query parameter.

_HOST_CPU_PERCENT = MetricKqlTemplate(
    kql=(
        "InsightsMetrics "
        "| where Namespace == 'Processor' and Name == 'UtilizationPercentage' "
        "| summarize v = avg(Val) by "
        "  bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId)"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_HOST_MEMORY_AVAILABLE_PCT = MetricKqlTemplate(
    kql=(
        "InsightsMetrics "
        "| where Namespace == 'Memory' and Name == 'AvailableMemoryPercentage' "
        "| summarize v = avg(Val) by "
        "  bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId)"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_POD_RESTARTS = MetricKqlTemplate(
    kql=(
        "KubePodInventory "
        "| where isnotempty(PodRestartCount) "
        "| summarize v = max(toint(PodRestartCount)) by "
        "  bin(TimeGenerated, 1m), resource_id = tolower(ClusterId), "
        "  pod = Name, namespace = Namespace"
    ),
    value_column="v",
    label_columns=("resource_id", "pod", "namespace"),
)

_REQUEST_FAILURE_RATE = MetricKqlTemplate(
    kql=(
        "AppRequests "
        "| summarize "
        "  failures = countif(Success == false), total = count() "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId) "
        "| extend v = iif(total == 0, 0.0, todouble(failures) / total) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_ROLLOUT_STALL_SECONDS = MetricKqlTemplate(
    kql=(
        "KubeEvents "
        "| where Reason in ('FailedCreate','ProgressDeadlineExceeded',"
        "'ImagePullBackOff','ErrImagePull') "
        "| summarize v = todouble(datetime_diff('second', now(), min(TimeGenerated))) "
        "  by resource_id = tolower(ClusterId), deployment = Name "
        "| extend TimeGenerated = now()"
    ),
    value_column="v",
    label_columns=("resource_id", "deployment"),
)


_DEMO_CAPTURE: Mapping[str, MetricKqlTemplate] = MappingProxyType(
    {
        METRIC_HOST_CPU_PERCENT: _HOST_CPU_PERCENT,
        METRIC_HOST_MEMORY_AVAILABLE_PCT: _HOST_MEMORY_AVAILABLE_PCT,
        METRIC_POD_RESTARTS: _POD_RESTARTS,
        METRIC_REQUEST_FAILURE_RATE: _REQUEST_FAILURE_RATE,
        METRIC_ROLLOUT_STALL_SECONDS: _ROLLOUT_STALL_SECONDS,
    }
)


def sre_demo_capture_queries() -> Mapping[str, MetricKqlTemplate]:
    """Return the five-metric-capture template map for a demo baseline.

    A fork wires this into
    :class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsConfig` at the
    composition root::

        AzureMonitorLogsConfig(
            workspace_id=...,
            queries=sre_demo_capture_queries(),
        )

    The returned mapping is a read-only view; a fork that needs to add or
    override templates copies into its own dict first.
    """
    return _DEMO_CAPTURE


__all__ = [
    "METRIC_HOST_CPU_PERCENT",
    "METRIC_HOST_MEMORY_AVAILABLE_PCT",
    "METRIC_POD_RESTARTS",
    "METRIC_REQUEST_FAILURE_RATE",
    "METRIC_ROLLOUT_STALL_SECONDS",
    "sre_demo_capture_queries",
]
