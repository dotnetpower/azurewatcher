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

Label case-normalization contract
---------------------------------

Every template lowercases the identifier columns it emits
(``resource_id = tolower(_ResourceId)``, ``resource_id = tolower(ClusterId)``).
The metric adapter's in-memory label filter is a **case-sensitive raw
string equality** (see :func:`fdai.shared.providers.metric._labels_match`),
so callers passing ``MetricQuery(labels={"resource_id": "..."})`` MUST
supply the ``resource_id`` value in lowercase to match. This is the same
contract Azure Resource Manager already uses (resource ids are
case-insensitive by convention; lowercase is canonical).

Semantic notes per template
---------------------------

- ``host.cpu.percent`` - avg guest-OS CPU % per 1-minute bin per
  resource. Requires the VM Insights extension.
- ``host.memory.available_pct`` - **available** memory %, so a **LOW**
  value means memory pressure. Wire this to
  :attr:`fdai.core.investigation.analyzer.Comparison.LTE` in the
  threshold analyzer; a ``GTE`` binding would alert on healthy hosts.
- ``k8s.pod.restarts`` - the **delta** of PodRestartCount within the
  timespan per pod (grouped by ``PodUid`` so a StatefulSet pod that
  keeps its ``Name`` across a recreation does not conflate the two
  incarnations' restart counters).
- ``http.server.request.failure_rate`` - failed / total AppRequests per
  1-minute bin per resource.
- ``k8s.deployment.rollout_stall_seconds`` - the **observed span** of
  stall-signal KubeEvents in the timespan
  (``max(TimeGenerated) - min(TimeGenerated)``), NOT the total time the
  rollout has been stuck. If the stall started before the query
  timespan, ``v`` is a **lower bound** of the true stall duration - a
  fork tuning a threshold around this metric should account for that.
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
    # PodRestartCount is a cumulative counter per pod. Grouping by
    # ``PodUid`` (the immutable object UID) rather than ``Name`` defends
    # against StatefulSet pods that keep their name across a
    # delete/recreate - two different incarnations would otherwise share
    # a group and the delta 'max - min' would surface as a spurious
    # restart (e.g. old pod at rc=3 + new pod at rc=0 -> min=0, max=3,
    # v=3, "3 restarts" when the true answer is zero). The label set
    # still exposes pod / namespace for the operator.
    kql=(
        "KubePodInventory "
        "| where isnotempty(PodRestartCount) and isnotempty(PodUid) "
        "| extend rc = toint(PodRestartCount) "
        "| summarize "
        "    rc_max = max(rc), rc_min = min(rc), "
        "    at = max(TimeGenerated), "
        "    pod = any(Name), namespace = any(Namespace) "
        "  by resource_id = tolower(ClusterId), pod_uid = tostring(PodUid) "
        "| extend v = todouble(rc_max - rc_min) "
        "| project TimeGenerated = at, v, resource_id, pod, namespace, pod_uid"
    ),
    value_column="v",
    label_columns=("resource_id", "pod", "namespace", "pod_uid"),
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
    # Emits one row per (cluster, involved object) with:
    #   - TimeGenerated = the earliest stall-signal event's own time
    #     (NOT now() - that would poison rolling-window anomaly
    #     detection with a fake "just now" timestamp),
    #   - v = seconds elapsed from that earliest event to the max event
    #     observed in the timespan (i.e. the *observed span* of the
    #     stall in this query window). See module docstring - this is a
    #     LOWER BOUND on the true stall duration, not the exact age.
    # The involved-object name is a pod / replica-set / deployment
    # depending on which event fired, so the label is ``involved_object``.
    kql=(
        "KubeEvents "
        "| where Reason in ('FailedCreate','ProgressDeadlineExceeded',"
        "'ImagePullBackOff','ErrImagePull') "
        "| summarize "
        "    first_at = min(TimeGenerated), last_at = max(TimeGenerated) "
        "  by resource_id = tolower(ClusterId), involved_object = Name "
        "| extend v = todouble(datetime_diff('second', last_at, first_at)) "
        "| project TimeGenerated = first_at, v, resource_id, involved_object"
    ),
    value_column="v",
    label_columns=("resource_id", "involved_object"),
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
