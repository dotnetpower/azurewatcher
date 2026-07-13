"""Ingest Azure Chaos Studio fault library into the FDAI catalog.

Azure Chaos Studio publishes ~50 faults across VM, VMSS, AKS, Key
Vault, Cosmos DB, Redis, AAD, Service Bus, Load Balancer, Storage,
and more. This ingester is a hand-curated CSP-neutral projection of
that library into the FDAI chaos-scenarios schema.

Source: Microsoft Learn - Azure Chaos Studio fault library. Every
entry uses the upstream fault name (`fault_name`) verbatim so an
operator can cross-reference; the injector shim ships as
`needs-injector` because FDAI has no Azure Chaos Studio delivery
adapter yet (adding it means wiring the Chaos Studio ARM API through
delivery/chaos/).

Output: `rule-catalog/chaos-scenarios/collected/azure-chaos-studio/`.
Idempotent.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[1]
_OUT_DIR = (
    _REPO_ROOT
    / "rule-catalog"
    / "chaos-scenarios"
    / "collected"
    / "azure-chaos-studio"
)
_ALERT_WINDOW_S = 360.0


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str
    fault_name: str  # Azure Chaos Studio spelling
    description: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    params: dict[str, str]
    rollback_note: str
    blast_radius_cap: int = 1
    tags: tuple[str, ...] = ("azure-chaos-studio",)


# CSP-neutral entries. Each carries the upstream fault_name as a param
# so the eventual Azure delivery adapter can dispatch by that name.
_ENTRIES: tuple[Entry, ...] = (
    # -- Compute (VM / VMSS) ---------------------------------------------
    Entry(
        slug="vm-shutdown",
        fault_name="urn:csci:microsoft:virtualMachine:shutdown/1.0",
        description="Cleanly shut down a Virtual Machine via Azure Chaos "
        "Studio; the guest OS receives the shutdown signal.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"fault_name": "urn:csci:microsoft:virtualMachine:shutdown/1.0", "abrupt": "false"},
        rollback_note="`az vm start` restores the VM; workload reschedules.",
        tags=("azure-chaos-studio", "vm"),
    ),
    Entry(
        slug="vm-redeploy",
        fault_name="urn:csci:microsoft:virtualMachine:redeploy/1.0",
        description="Redeploy a Virtual Machine to a new host - forces a "
        "hardware-level reset. Emulates hardware failure recovery.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={"fault_name": "urn:csci:microsoft:virtualMachine:redeploy/1.0"},
        rollback_note="Redeploy is one-way; monitor the VM comes back Ready.",
        tags=("azure-chaos-studio", "vm"),
    ),
    Entry(
        slug="vmss-shutdown",
        fault_name="urn:csci:microsoft:virtualMachineScaleSet:shutdown/1.0",
        description="Shut down one or more instances of a VMSS via Chaos "
        "Studio; the scale set replaces per its upgrade policy.",
        category="compute",
        target_type="vmss",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={"fault_name": "urn:csci:microsoft:virtualMachineScaleSet:shutdown/1.0"},
        rollback_note="`az vmss start` and the upgrade policy restores the "
        "instance count.",
        blast_radius_cap=2,
        tags=("azure-chaos-studio", "vmss"),
    ),
    Entry(
        slug="agent-cpu-pressure",
        fault_name="urn:csci:microsoft:agent:cpuPressure/1.0",
        description="Sustain CPU pressure on a VM via the Chaos Studio "
        "agent-based fault - percentage of cores loaded for a bounded window.",
        category="compute",
        target_type="vm",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_cpu",
        params={
            "fault_name": "urn:csci:microsoft:agent:cpuPressure/1.0",
            "pressure_level": "95",
        },
        rollback_note="Chaos Studio agent removes the pressure at duration end; "
        "no manual rollback needed inside the window.",
        tags=("azure-chaos-studio", "vm", "cpu"),
    ),
    Entry(
        slug="agent-physical-memory-pressure",
        fault_name="urn:csci:microsoft:agent:physicalMemoryPressure/1.0",
        description="Sustain physical memory pressure on a VM via the Chaos "
        "Studio agent-based fault.",
        category="resource_saturation",
        target_type="vm",
        fault_family="saturate",
        intensity="high",
        expected_signal="host_memory",
        params={
            "fault_name": "urn:csci:microsoft:agent:physicalMemoryPressure/1.0",
            "pressure_level": "95",
        },
        rollback_note="Agent releases memory at duration end.",
        tags=("azure-chaos-studio", "vm", "memory"),
    ),
    Entry(
        slug="agent-network-latency",
        fault_name="urn:csci:microsoft:agent:networkLatency/1.0",
        description="Add outbound network latency on a VM via the Chaos "
        "Studio agent-based fault; downstream services see gateway latency.",
        category="network",
        target_type="vm",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={
            "fault_name": "urn:csci:microsoft:agent:networkLatency/1.0",
            "latency_ms": "250",
        },
        rollback_note="Agent removes the tc netem rule at duration end.",
        tags=("azure-chaos-studio", "vm", "network"),
    ),
    Entry(
        slug="agent-network-disconnect",
        fault_name="urn:csci:microsoft:agent:networkDisconnect/1.0",
        description="Block outbound traffic to a set of destinations on a "
        "VM via Chaos Studio; emulates dependency partition.",
        category="network",
        target_type="vm",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={
            "fault_name": "urn:csci:microsoft:agent:networkDisconnect/1.0",
            "destinations": "upstream-service",
        },
        rollback_note="Firewall rule removed at duration end.",
        tags=("azure-chaos-studio", "vm", "network"),
    ),
    Entry(
        slug="agent-network-packet-loss",
        fault_name="urn:csci:microsoft:agent:networkPacketLoss/1.0",
        description="Drop a fraction of outbound packets on a VM via Chaos "
        "Studio; downstream calls see failures / retries.",
        category="network",
        target_type="vm",
        fault_family="drop",
        intensity="high",
        expected_signal="request_failure",
        params={
            "fault_name": "urn:csci:microsoft:agent:networkPacketLoss/1.0",
            "loss_percent": "20",
        },
        rollback_note="Agent removes the drop rule at duration end.",
        tags=("azure-chaos-studio", "vm", "network"),
    ),
    Entry(
        slug="agent-stop-service",
        fault_name="urn:csci:microsoft:agent:stopService/1.0",
        description="Stop a system service (systemd unit) on a VM via Chaos "
        "Studio; captures dependency-crash blast radius.",
        category="compute",
        target_type="vm",
        fault_family="stop",
        intensity="extreme",
        expected_signal="pod_restart",
        params={
            "fault_name": "urn:csci:microsoft:agent:stopService/1.0",
            "service": "myservice",
        },
        rollback_note="Agent restarts the service at duration end or on stop.",
        tags=("azure-chaos-studio", "vm", "service"),
    ),
    # -- AKS -------------------------------------------------------------
    Entry(
        slug="aks-chaos-mesh-pod-chaos",
        fault_name="urn:csci:microsoft:azureKubernetesServiceChaosMesh:podChaos/2.1",
        description="Run a Chaos Mesh PodChaos experiment on an AKS cluster "
        "via Chaos Studio; the AKS injector wraps the CRD path.",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="pod_restart",
        params={
            "fault_name": (
                "urn:csci:microsoft:azureKubernetesServiceChaosMesh:podChaos/2.1"
            ),
        },
        rollback_note="Chaos Studio removes the CRD at duration end.",
        blast_radius_cap=2,
        tags=("azure-chaos-studio", "aks"),
    ),
    Entry(
        slug="aks-chaos-mesh-network-chaos",
        fault_name="urn:csci:microsoft:azureKubernetesServiceChaosMesh:networkChaos/2.1",
        description="Run a Chaos Mesh NetworkChaos experiment on an AKS "
        "cluster via Chaos Studio.",
        category="network",
        target_type="pod",
        fault_family="delay",
        intensity="high",
        expected_signal="gateway_latency",
        params={
            "fault_name": (
                "urn:csci:microsoft:azureKubernetesServiceChaosMesh:networkChaos/2.1"
            ),
        },
        rollback_note="Chaos Studio removes the CRD at duration end.",
        blast_radius_cap=2,
        tags=("azure-chaos-studio", "aks"),
    ),
    Entry(
        slug="aks-chaos-mesh-stress-chaos",
        fault_name="urn:csci:microsoft:azureKubernetesServiceChaosMesh:stressChaos/2.1",
        description="Run a Chaos Mesh StressChaos experiment on an AKS "
        "cluster via Chaos Studio.",
        category="compute",
        target_type="pod",
        fault_family="saturate",
        intensity="high",
        expected_signal="node_cpu",
        params={
            "fault_name": (
                "urn:csci:microsoft:azureKubernetesServiceChaosMesh:stressChaos/2.1"
            ),
        },
        rollback_note="Chaos Studio removes the CRD at duration end.",
        blast_radius_cap=3,
        tags=("azure-chaos-studio", "aks"),
    ),
    # -- Cosmos DB -------------------------------------------------------
    Entry(
        slug="cosmos-db-failover",
        fault_name="urn:csci:microsoft:cosmosDB:failover/1.0",
        description="Force a Cosmos DB region failover via Chaos Studio; "
        "applications observe transient read/write errors and latency.",
        category="dependency",
        target_type="db",
        fault_family="stop",
        intensity="extreme",
        expected_signal="request_failure",
        params={"fault_name": "urn:csci:microsoft:cosmosDB:failover/1.0"},
        rollback_note="Failback to the original region after the window.",
        tags=("azure-chaos-studio", "cosmos"),
    ),
    # -- Key Vault -------------------------------------------------------
    Entry(
        slug="keyvault-deny-access",
        fault_name="urn:csci:microsoft:keyVault:denyAccess/1.0",
        description="Temporarily deny access to a Key Vault via a network "
        "rule flip in Chaos Studio; clients see 403 on secret retrieval.",
        category="dependency",
        target_type="secret_store",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={"fault_name": "urn:csci:microsoft:keyVault:denyAccess/1.0"},
        rollback_note="Chaos Studio restores the network rule at duration end.",
        tags=("azure-chaos-studio", "keyvault"),
    ),
    # -- Cache for Redis -------------------------------------------------
    Entry(
        slug="redis-reboot",
        fault_name="urn:csci:microsoft:cache:reboot/1.0",
        description="Reboot Azure Cache for Redis node(s) via Chaos Studio.",
        category="dependency",
        target_type="cache",
        fault_family="stop",
        intensity="extreme",
        expected_signal="request_failure",
        params={"fault_name": "urn:csci:microsoft:cache:reboot/1.0"},
        rollback_note="Reboot is one-way; monitor cache back to healthy.",
        tags=("azure-chaos-studio", "redis"),
    ),
    # -- Network Security Group -----------------------------------------
    Entry(
        slug="nsg-security-rule",
        fault_name="urn:csci:microsoft:networkSecurityGroup:securityRule/1.0",
        description="Add a deny NSG rule via Chaos Studio; emulates an "
        "operator-mistake blackhole to a service.",
        category="network",
        target_type="ingress",
        fault_family="deny",
        intensity="extreme",
        expected_signal="backend_health",
        params={"fault_name": "urn:csci:microsoft:networkSecurityGroup:securityRule/1.0"},
        rollback_note="Chaos Studio removes the rule at duration end.",
        tags=("azure-chaos-studio", "nsg"),
    ),
    # -- Load Balancer --------------------------------------------------
    Entry(
        slug="load-balancer-backend-remove",
        fault_name="urn:csci:microsoft:loadBalancer:backendRemove/1.0",
        description="Remove a backend from an Azure Load Balancer pool via "
        "Chaos Studio; healthy-host count drops.",
        category="traffic",
        target_type="lb",
        fault_family="deny",
        intensity="high",
        expected_signal="backend_health",
        params={"fault_name": "urn:csci:microsoft:loadBalancer:backendRemove/1.0"},
        rollback_note="Chaos Studio re-adds the backend at duration end.",
        blast_radius_cap=2,
        tags=("azure-chaos-studio", "lb"),
    ),
    # -- Service Bus ----------------------------------------------------
    Entry(
        slug="service-bus-firewall-block",
        fault_name="urn:csci:microsoft:serviceBus:firewallBlock/1.0",
        description="Block a Service Bus namespace behind its firewall via "
        "Chaos Studio; publishers / subscribers see connection refused.",
        category="dependency",
        target_type="ingress",
        fault_family="deny",
        intensity="extreme",
        expected_signal="request_failure",
        params={"fault_name": "urn:csci:microsoft:serviceBus:firewallBlock/1.0"},
        rollback_note="Chaos Studio restores the firewall at duration end.",
        tags=("azure-chaos-studio", "servicebus"),
    ),
)


def _to_body(e: Entry) -> dict:
    return {
        "id": f"chaos.azure-chaos-studio.{e.slug}",
        "version": 1,
        "provenance": {
            "source": "azure-chaos-studio",
            "source_url": "https://learn.microsoft.com/azure/chaos-studio/chaos-studio-fault-library",
            "source_ref": e.fault_name,
            "synthesis_method": "collected",
        },
        "category": e.category,
        "target_type": e.target_type,
        "fault_family": e.fault_family,
        "intensity": e.intensity,
        "duration_seconds": _ALERT_WINDOW_S if e.intensity != "extreme" else _ALERT_WINDOW_S * 2,
        "expected_signal": e.expected_signal,
        # No delivery adapter yet; loader keeps needs-injector out of promoted/.
        "injector": "needs-injector",
        "blast_radius_cap": e.blast_radius_cap,
        "rollback_note": e.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": e.description,
        "params": dict(e.params),
        "tags": list(e.tags),
    }


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for e in _ENTRIES:
        path = _OUT_DIR / f"{e.slug}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(_to_body(e), f, sort_keys=False, default_flow_style=False)
        written += 1
    print(f"wrote {written} Azure Chaos Studio scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
