"""Reference fault-injection scenarios (demo parity, CSP-neutral).

These mirror the injected faults in the Azure SRE Agent demo (session notes
slide 9), expressed with opaque, customer-agnostic ``target_selector``
handles. Each scenario names the ``expected_signal`` the control loop
SHOULD raise, so the harness can decide VALIDATED vs NOT_DETECTED.
"""

from __future__ import annotations

from fdai.core.chaos.contract import FaultScenario

AKS_POD_CPU_SPIKE = FaultScenario(
    scenario_id="aks-pod-cpu-spike",
    fault_type="cpu_stress",
    description="Drive AKS pod CPU up to induce backend latency downstream.",
    target_selector="workload:api-backend",
    expected_signal="node_cpu",
    blast_radius_cap=3,
    duration_seconds=120.0,
    params={"cpu_workers": "4"},
    rollback_note="Remove the Chaos Mesh StressChaos resource.",
)

AOAI_TPM_THROTTLE = FaultScenario(
    scenario_id="aoai-tpm-throttle",
    fault_type="rate_limit",
    description="Shrink Azure OpenAI TPM to induce HTTP 429 rate-limit errors.",
    target_selector="model-deployment:chat",
    expected_signal="rate_limit",
    blast_radius_cap=1,
    duration_seconds=180.0,
    params={"tpm_reduction_pct": "80"},
    rollback_note="Restore the prior TPM quota on the deployment.",
)

MYSQL_CPU_PRESSURE = FaultScenario(
    scenario_id="mysql-cpu-pressure",
    fault_type="query_load",
    description="Sustain MySQL CPU pressure to surface slow queries.",
    target_selector="db:orders",
    expected_signal="db_cpu",
    blast_radius_cap=1,
    duration_seconds=300.0,
    params={"concurrent_queries": "50"},
    rollback_note="Stop the load generator.",
)

APPGW_BACKEND_FAILURE = FaultScenario(
    scenario_id="appgw-backend-failure",
    fault_type="pod_kill",
    description="Fail a backend pool member to collapse healthy host count.",
    target_selector="workload:api-backend",
    expected_signal="backend_health",
    blast_radius_cap=2,
    duration_seconds=90.0,
    rollback_note="Allow the deployment to reschedule the pod.",
)

NETWORK_RTT_DELAY = FaultScenario(
    scenario_id="network-rtt-delay",
    fault_type="network_delay",
    description="Add outbound RTT to inflate dependency latency.",
    target_selector="workload:api-backend",
    expected_signal="gateway_latency",
    blast_radius_cap=2,
    duration_seconds=120.0,
    params={"delay_ms": "250"},
    rollback_note="Remove the Chaos Mesh NetworkChaos resource.",
)


def default_scenarios() -> tuple[FaultScenario, ...]:
    """The reference chaos catalog matching the demo's injected faults."""
    return (
        AKS_POD_CPU_SPIKE,
        AOAI_TPM_THROTTLE,
        MYSQL_CPU_PRESSURE,
        APPGW_BACKEND_FAILURE,
        NETWORK_RTT_DELAY,
    )


__all__ = [
    "AKS_POD_CPU_SPIKE",
    "AOAI_TPM_THROTTLE",
    "APPGW_BACKEND_FAILURE",
    "MYSQL_CPU_PRESSURE",
    "NETWORK_RTT_DELAY",
    "default_scenarios",
]
