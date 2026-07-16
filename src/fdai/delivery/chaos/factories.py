"""Delivery-layer factory functions binding catalog entries to concrete injectors.

Registers builders on a :class:`~fdai.core.chaos.factory.ScenarioFactory`:

- ``chaos-mesh:*`` (prefix): builds a Chaos Mesh CRD body from
  ``entry.spec["params"]`` per kind, wraps
  :class:`ChaosMeshInjector` + :class:`ChaosMeshInjectedProbe`.
- ``kubectl:pod-kill``, ``kubectl:scale``, ``kubectl:set-image``:
  wraps the shipped kubectl injectors.
- ``az:vm-run-command``: dispatches to `AzVm{Cpu,Mem}StressInjector`
  by ``fault_family`` and pairs with the corresponding probe.

Every builder reads its cloud-neutral wiring (kubectl context,
namespace, resource-group, vm name, VM resource id, etc.) from the
``context`` dict the caller supplies. Secrets never appear in `context`;
they stay behind provider adapters.

Coverage today (against the shipped 132-entry catalog):

    ScenarioFactory.executable_entries(load_all()) yields the subset
    the harness can run end-to-end without a new delivery adapter -
    92 entries: Chaos Mesh, Litmus ChaosEngine, kubectl, MySQL, Azure
    OpenAI, and supported direct Azure operations. Direct Azure faults
    use provider-state probes rather than unrelated Kubernetes CRD status.
    The 17 AWS FIS references, 22 GPU-hardware entries, and retired legacy
    Redis reboot entry remain correctly non-executable.

This module never imports from `core/` beyond the factory contract and
the delivery-layer injector classes it wraps.
"""

from __future__ import annotations

from typing import Any

import yaml

from fdai.core.chaos.factory import ScenarioFactory
from fdai.core.chaos.injector import FaultInjector, SignalProbe
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.delivery.chaos.aoai_ratelimit import (
    AoaiRateLimitInjector,
    AoaiRateLimitProbe,
)
from fdai.delivery.chaos.azure_ops import (
    AzCliStateProbe,
    AzCosmosFailoverInjector,
    AzKeyVaultDenyAccessInjector,
    AzLbBackendRemoveInjector,
    AzNsgRuleInjector,
    AzRedisRebootInjector,
    AzServiceBusFirewallInjector,
    AzVmLifecycleInjector,
    AzVmNetworkDisconnectInjector,
    AzVmNetworkLatencyInjector,
    AzVmPacketLossInjector,
    AzVmssLifecycleInjector,
    AzVmStopServiceInjector,
)
from fdai.delivery.chaos.chaos_mesh import (
    ChaosMeshInjectedProbe,
    ChaosMeshInjector,
)
from fdai.delivery.chaos.litmus import LitmusChaosInjector, LitmusChaosResultProbe
from fdai.delivery.chaos.live_injectors import (
    AzureMonitorCpuProbe,
    AzVmCpuStressInjector,
    AzVmMemProbe,
    AzVmMemStressInjector,
    KubeBackendHealthProbe,
    KubectlBackendDownInjector,
    KubectlBadDeployInjector,
    KubectlPodKillInjector,
    KubeEventPodRestartProbe,
    KubeRolloutStallProbe,
)
from fdai.delivery.chaos.mysql_load import (
    AzMysqlQueryLoadInjector,
    AzureMonitorDbCpuProbe,
)

# ---------------------------------------------------------------------------
# Chaos Mesh: CRD body builders per kind
# ---------------------------------------------------------------------------


def _cm_pod_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    """Return (kind, yaml_body) for a Chaos Mesh PodChaos scenario."""
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "pod-kill"))
    mode = str(p.get("mode", "one"))
    name = _crd_name(entry)
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  action: {action}
  mode: {mode}
  selector:
    namespaces: [{ctx["workload_namespace"]}]
    labelSelectors:
      app: {ctx["workload_label"]}
"""
    return "PodChaos", body


def _cm_network_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "delay"))
    name = _crd_name(entry)
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: NetworkChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        f"  action: {action}",
        "  mode: one",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
    ]
    if action == "delay":
        lines.extend(
            [
                "  delay:",
                f'    latency: "{p.get("latency_ms", "250")}ms"',
                f'    jitter: "{p.get("jitter_ms", "20")}ms"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "loss":
        lines.extend(
            [
                "  loss:",
                f'    loss: "{p.get("loss_percent", "20")}"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "corrupt":
        lines.extend(
            [
                "  corrupt:",
                f'    corrupt: "{p.get("corrupt_percent", "20")}"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "duplicate":
        lines.extend(
            [
                "  duplicate:",
                f'    duplicate: "{p.get("duplicate_percent", "10")}"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "partition":
        # Full-partition; direction defaults to `both`.
        lines.append(f"  direction: {p.get('direction', 'both')}")
    elif action == "bandwidth":
        lines.extend(
            [
                "  bandwidth:",
                f'    rate: "{p.get("rate", "1mbps")}"',
                f"    buffer: {p.get('buffer', 10000)}",
                f"    limit: {p.get('limit', 20000)}",
            ]
        )
    return "NetworkChaos", "\n".join(lines) + "\n"


def _cm_http_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    target = str(p.get("target", "Request"))
    port = str(p.get("port", "80"))
    name = _crd_name(entry)
    action = str(p.get("action", "abort"))
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: HTTPChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        "  mode: one",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
        f"  target: {target}",
        f"  port: {port}",
    ]
    if action == "abort":
        lines.append("  abort: true")
    elif action == "delay":
        lines.append(f'  delay: "{p.get("delay", "2s")}"')
    elif action == "replace":
        lines.append("  replace:")
        code = p.get("replace_code")
        if code is not None:
            lines.append(f"    code: {code}")
    return "HTTPChaos", "\n".join(lines) + "\n"


def _cm_stress_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    name = _crd_name(entry)
    stressor = str(p.get("stressor", "cpu"))
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: StressChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        "  mode: one",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
        "  stressors:",
    ]
    if stressor == "cpu":
        lines.extend(
            [
                "    cpu:",
                f"      workers: {p.get('workers', '2')}",
                f"      load: {p.get('load_percent', '90')}",
            ]
        )
    elif stressor == "memory":
        lines.extend(
            [
                "    memory:",
                f"      workers: {p.get('workers', '1')}",
                f'      size: "{p.get("size", "256M")}"',
            ]
        )
    return "StressChaos", "\n".join(lines) + "\n"


def _cm_dns_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "random"))
    scope = str(p.get("scope", "all"))
    patterns = str(p.get("patterns", "*"))
    name = _crd_name(entry)
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: DNSChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  action: {action}
  mode: one
  scope: {scope}
  patterns: ["{patterns}"]
  selector:
    namespaces: [{ctx["workload_namespace"]}]
    labelSelectors:
      app: {ctx["workload_label"]}
"""
    return "DNSChaos", body


def _cm_io_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "latency"))
    percent = str(p.get("percent", "50"))
    name = _crd_name(entry)
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: IOChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        f"  action: {action}",
        "  mode: one",
        f"  percent: {percent}",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
    ]
    if action == "latency":
        lines.append(f'  delay: "{p.get("delay_ms", "300")}ms"')
    elif action == "fault":
        errno = p.get("errno", "5")
        lines.append(f"  errno: {errno}")
    return "IOChaos", "\n".join(lines) + "\n"


def _cm_block_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "delay"))
    delay = str(p.get("delay", "300ms"))
    volume = str(p.get("volume", "data"))
    name = _crd_name(entry)
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: BlockChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  action: {action}
  mode: one
  delay:
    latency: "{delay}"
  volumeName: {volume}
"""
    return "BlockChaos", body


def _cm_kernel_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "fail-syscall"))
    name = _crd_name(entry)
    syscall = str(p.get("syscall", "write"))
    errno = str(p.get("errno", "5"))
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: KernelChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  mode: one
  selector:
    namespaces: [{ctx["workload_namespace"]}]
    labelSelectors:
      app: {ctx["workload_label"]}
  failKernRequest:
    callchain:
      - funcname: "{syscall}"
    failtype: 0
    headers: []
    probability: 100
    times: 1
    action: {action}
    errno: {errno}
"""
    return "KernelChaos", body


_CHAOS_MESH_KINDS: dict[str, Any] = {
    "PodChaos": _cm_pod_chaos_body,
    "NetworkChaos": _cm_network_chaos_body,
    "HTTPChaos": _cm_http_chaos_body,
    "StressChaos": _cm_stress_chaos_body,
    "DNSChaos": _cm_dns_chaos_body,
    "IOChaos": _cm_io_chaos_body,
    "BlockChaos": _cm_block_chaos_body,
    "KernelChaos": _cm_kernel_chaos_body,
}


def _crd_name(entry: CatalogEntry) -> str:
    """Kebab-safe CRD name; caps at 40 chars (Chaos Mesh limit is 63)."""
    slug = entry.id.replace(".", "-").replace("_", "-").lower()
    return f"fdai-{slug}"[:40].rstrip("-")


def _litmus_engine_name(entry: CatalogEntry) -> str:
    slug = entry.id.replace(".", "-").replace("_", "-").lower()
    return f"fdai-{slug}"[:50].rstrip("-")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _build_chaos_mesh(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    """Prefix builder for every `chaos-mesh:<Kind>` scenario.

    Dispatches by kind (the string after the ``:``) to a per-kind CRD
    body builder. Fails closed if the kind is not one of the eight
    Chaos Mesh types the delivery layer supports today.
    """
    injector_ref = str(entry.spec["injector"])
    kind = injector_ref.split(":", 1)[1] if ":" in injector_ref else ""
    body_fn = _CHAOS_MESH_KINDS.get(kind)
    if body_fn is None:
        raise ValueError(
            f"{entry.id}: unknown chaos-mesh CRD kind {kind!r}; "
            f"supported: {sorted(_CHAOS_MESH_KINDS)}"
        )
    _kind, crd_yaml = body_fn(entry, ctx)
    return ChaosMeshInjector(
        fault_type=str(entry.spec.get("fault_family", "chaos_mesh")),
        context=str(ctx["kubectl_context"]),
        kind=_kind,
        name=_crd_name(entry),
        namespace=str(ctx["chaos_namespace"]),
        crd_yaml=crd_yaml,
    )


def _build_chaos_mesh_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    """Probe backing every chaos-mesh scenario: the CRD's AllInjected status."""
    injector_ref = str(entry.spec["injector"])
    kind = injector_ref.split(":", 1)[1] if ":" in injector_ref else "PodChaos"
    return ChaosMeshInjectedProbe(
        context=str(ctx["kubectl_context"]),
        kind=kind,
        name=_crd_name(entry),
        namespace=str(ctx["chaos_namespace"]),
    )


def _build_litmus(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    experiment_name = str(entry.spec["provenance"]["source_ref"])
    params = {str(key): str(value) for key, value in (entry.spec.get("params") or {}).items()}
    params["TOTAL_CHAOS_DURATION"] = str(
        min(
            int(float(entry.spec["duration_seconds"])),
            int(ctx.get("litmus_max_duration_seconds", 180)),
        )
    )
    if entry.spec["target_type"] == "node":
        params.pop("NODE_LABEL", None)
        params["TARGET_NODE"] = str(ctx["litmus_target_node"])
    if experiment_name == "container-kill":
        params["TARGET_CONTAINER"] = str(ctx["backend_container"])
    engine_name = _litmus_engine_name(entry)
    body = {
        "apiVersion": "litmuschaos.io/v1alpha1",
        "kind": "ChaosEngine",
        "metadata": {"name": engine_name, "namespace": str(ctx["litmus_namespace"])},
        "spec": {
            "appinfo": {
                "appns": str(ctx["workload_namespace"]),
                "applabel": f"app={ctx['workload_label']}",
                "appkind": "deployment",
            },
            "engineState": "active",
            "annotationCheck": "false",
            "chaosServiceAccount": str(ctx["litmus_service_account"]),
            "experiments": [
                {
                    "name": experiment_name,
                    "spec": {
                        "components": {
                            "env": [
                                {"name": key, "value": value}
                                for key, value in sorted(params.items())
                            ]
                        }
                    },
                }
            ],
        },
    }
    return LitmusChaosInjector(
        fault_type=str(entry.spec["fault_family"]),
        context=str(ctx["kubectl_context"]),
        engine_name=engine_name,
        namespace=str(ctx["litmus_namespace"]),
        engine_yaml=yaml.safe_dump(body, sort_keys=False),
    )


def _build_litmus_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    return LitmusChaosResultProbe(
        context=str(ctx["kubectl_context"]),
        engine_name=_litmus_engine_name(entry),
        experiment_name=str(entry.spec["provenance"]["source_ref"]),
        namespace=str(ctx["litmus_namespace"]),
    )


def _build_kubectl_pod_kill(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    return KubectlPodKillInjector(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
    )


def _build_kubectl_scale(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    return KubectlBackendDownInjector(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        deployment=str(ctx.get("backend_deployment", "api-backend")),
        restore_replicas=int(ctx.get("backend_restore_replicas", 3)),
    )


def _build_kubectl_set_image(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    bad_tag = str(p.get("bad_image_tag", "does-not-exist"))
    base = str(ctx.get("backend_image", "nginx"))
    return KubectlBadDeployInjector(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        deployment=str(ctx.get("backend_deployment", "api-backend")),
        container=str(ctx.get("backend_container", "web")),
        bad_image=f"{base}:{bad_tag}",
    )


def _build_az_vm_run_command(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    """Dispatch VM stressors by fault_family / expected_signal."""
    signal = entry.expected_signal
    duration = int(entry.spec.get("duration_seconds", 600))
    if signal == "host_cpu":
        return AzVmCpuStressInjector(
            resource_group=str(ctx["resource_group"]),
            vm_name=str(ctx["vm_name"]),
            duration_seconds=duration,
        )
    if signal == "host_memory":
        p = entry.spec.get("params") or {}
        return AzVmMemStressInjector(
            resource_group=str(ctx["resource_group"]),
            vm_name=str(ctx["vm_name"]),
            vm_bytes=str(p.get("vm_bytes", "250M")),
            duration_seconds=duration,
        )
    raise ValueError(
        f"{entry.id}: az:vm-run-command builder has no dispatch for expected_signal={signal!r}"
    )


def _build_mysql_query_load(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    params = entry.spec.get("params") or {}
    return AzMysqlQueryLoadInjector(
        connect_factory=ctx["mysql_connect_factory"],
        concurrent_queries=int(params.get("concurrent_queries", 4)),
    )


def _build_aoai_rate_limit(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    params = entry.spec.get("params") or {}
    return AoaiRateLimitInjector(
        request_fn=ctx["aoai_load_request_fn"],
        concurrency=int(params.get("concurrency", 8)),
    )


# ---- probes (signal -> probe builder) ------------------------------------


def _build_pod_restart_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("az:"):
        return _build_azure_state_probe(entry, ctx)
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return KubeEventPodRestartProbe(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
    )


def _build_backend_health_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("az:"):
        return _build_azure_state_probe(entry, ctx)
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return KubeBackendHealthProbe(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        service=str(ctx.get("backend_service", "api-backend")),
    )


def _build_rollout_stall_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    if str(entry.spec.get("injector", "")).startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    return KubeRolloutStallProbe(
        context=str(ctx["kubectl_context"]),
        namespace=str(ctx["workload_namespace"]),
        selector=f"app={ctx.get('workload_label', 'api-backend')}",
    )


def _build_host_cpu_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return AzureMonitorCpuProbe(
        vm_resource_id=str(ctx["vm_resource_id"]),
        threshold_pct=float(ctx.get("vm_cpu_threshold_pct", 40.0)),
    )


def _build_host_memory_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    if ref.startswith("chaos-mesh:"):
        return _build_chaos_mesh_probe(entry, ctx)
    return AzVmMemProbe(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        min_available_mb=int(ctx.get("vm_mem_min_available_mb", 350)),
    )


def _build_db_cpu_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    return AzureMonitorDbCpuProbe(
        server_resource_id=str(ctx["mysql_server_resource_id"]),
        threshold_pct=float(ctx.get("mysql_cpu_threshold_pct", 25.0)),
    )


def _build_rate_limit_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    return AoaiRateLimitProbe(
        request_fn=ctx["aoai_probe_request_fn"],
        samples=int(ctx.get("aoai_probe_samples", 5)),
    )


def _build_cm_status_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec.get("injector", ""))
    if ref.startswith("az:"):
        return _build_azure_state_probe(entry, ctx)
    if ref.startswith("litmus:"):
        return _build_litmus_probe(entry, ctx)
    return _build_chaos_mesh_probe(entry, ctx)


# ---------------------------------------------------------------------------
# Azure Chaos Studio equivalents (no Chaos Studio service required)
# ---------------------------------------------------------------------------
#
# Chaos Studio is a managed orchestrator; each fault it exposes is a thin
# wrapper over one or more `az` CLI operations FDAI can invoke directly.
# The 15 Azure Chaos Studio scenarios under
# `rule-catalog/chaos-scenarios/collected/azure-chaos-studio/` map to these
# builders via `az:*` injector strings (see azure_ops.py for the classes).


def _vm_run_command_probe(ctx: dict[str, Any], script: str, expected: str) -> AzCliStateProbe:
    return AzCliStateProbe(
        command=(
            "az",
            "vm",
            "run-command",
            "invoke",
            "-g",
            str(ctx["resource_group"]),
            "-n",
            str(ctx["vm_name"]),
            "--command-id",
            "RunShellScript",
            "--scripts",
            script,
            "--query",
            "value[0].message",
            "-o",
            "tsv",
        ),
        expected_substrings=(expected,),
    )


def _build_azure_state_probe(entry: CatalogEntry, ctx: dict[str, Any]) -> SignalProbe:
    ref = str(entry.spec["injector"])
    params = entry.spec.get("params") or {}
    resource_group = str(ctx["resource_group"])
    if ref == "az:vm-network-latency":
        interface = str(ctx.get("vm_interface", "eth0"))
        return _vm_run_command_probe(ctx, f"tc qdisc show dev {interface}", "delay")
    if ref == "az:vm-packet-loss":
        interface = str(ctx.get("vm_interface", "eth0"))
        return _vm_run_command_probe(ctx, f"tc qdisc show dev {interface}", "loss")
    if ref == "az:vm-network-disconnect":
        destination = str(
            params.get("destination", ctx.get("network_disconnect_destination", "10.0.0.0/8"))
        )
        return _vm_run_command_probe(
            ctx,
            f"iptables -C OUTPUT -d {destination} -j DROP && echo blocked",
            "blocked",
        )
    if ref == "az:vm-stop-service":
        service = str(params.get("service", ctx.get("stop_service_name", "myservice")))
        return _vm_run_command_probe(
            ctx,
            f"systemctl is-active {service} 2>/dev/null || true",
            "inactive",
        )
    if ref == "az:vm-lifecycle":
        action = str(params.get("action", "deallocate"))
        if action == "deallocate":
            return AzCliStateProbe(
                command=(
                    "az",
                    "vm",
                    "get-instance-view",
                    "-g",
                    resource_group,
                    "-n",
                    str(ctx["vm_name"]),
                    "--query",
                    "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]",
                    "-o",
                    "tsv",
                ),
                expected_substrings=("PowerState/deallocated",),
            )
        return AzCliStateProbe(
            command=(
                "az",
                "vm",
                "show",
                "-g",
                resource_group,
                "-n",
                str(ctx["vm_name"]),
                "--query",
                "provisioningState",
                "-o",
                "tsv",
            ),
            expected_substrings=("Succeeded",),
        )
    if ref == "az:vmss-lifecycle":
        return AzCliStateProbe(
            command=(
                "az",
                "vmss",
                "list-instances",
                "-g",
                resource_group,
                "-n",
                str(ctx["vmss_name"]),
                "--expand",
                "instanceView",
                "--query",
                "[].instanceView.statuses[?starts_with(code, 'PowerState/')].code",
                "-o",
                "tsv",
            ),
            expected_substrings=("PowerState/deallocated",),
        )
    if ref == "az:cosmosdb-failover":
        priority_zero = next(
            (
                item.split("=", 1)[0]
                for item in str(params["failover_priorities"]).split()
                if item.endswith("=0")
            ),
            "",
        )
        return AzCliStateProbe(
            command=(
                "az",
                "cosmosdb",
                "show",
                "-g",
                resource_group,
                "-n",
                str(ctx["cosmos_account_name"]),
                "--query",
                "writeLocations[?failoverPriority==`0`].locationName | [0]",
                "-o",
                "tsv",
            ),
            expected_substrings=(priority_zero,),
        )
    if ref == "az:keyvault-deny":
        return AzCliStateProbe(
            command=(
                "az",
                "keyvault",
                "show",
                "-g",
                resource_group,
                "-n",
                str(ctx["keyvault_name"]),
                "--query",
                "properties.networkAcls.defaultAction",
                "-o",
                "tsv",
            ),
            expected_substrings=("Deny",),
        )
    if ref == "az:nsg-rule":
        return AzCliStateProbe(
            command=(
                "az",
                "network",
                "nsg",
                "rule",
                "show",
                "-g",
                resource_group,
                "--nsg-name",
                str(ctx["nsg_name"]),
                "-n",
                str(ctx.get("nsg_rule_name", "fdai-chaos-deny")),
                "--query",
                "access",
                "-o",
                "tsv",
            ),
            expected_substrings=("Deny",),
        )
    if ref == "az:lb-backend-remove":
        return AzCliStateProbe(
            command=(
                "az",
                "network",
                "lb",
                "address-pool",
                "show",
                "-g",
                resource_group,
                "--lb-name",
                str(ctx["lb_name"]),
                "-n",
                str(ctx["lb_pool_name"]),
                "--query",
                "loadBalancerBackendAddresses[].name",
                "-o",
                "tsv",
            ),
            absent_substrings=(str(ctx["lb_address_name"]),),
        )
    if ref == "az:servicebus-firewall":
        return AzCliStateProbe(
            command=(
                "az",
                "servicebus",
                "namespace",
                "network-rule-set",
                "show",
                "-g",
                resource_group,
                "--namespace-name",
                str(ctx["servicebus_namespace"]),
                "--query",
                "defaultAction",
                "-o",
                "tsv",
            ),
            expected_substrings=("Deny",),
        )
    raise ValueError(f"{entry.id}: no Azure state probe for {ref!r}")


def _build_az_vm_network_latency(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzVmNetworkLatencyInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        latency_ms=int(p.get("latency_ms", 250)),
        interface=str(ctx.get("vm_interface", "eth0")),
    )


def _build_az_vm_packet_loss(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzVmPacketLossInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        loss_percent=int(p.get("loss_percent", 20)),
        interface=str(ctx.get("vm_interface", "eth0")),
    )


def _build_az_vm_network_disconnect(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    dest = str(p.get("destination", ctx.get("network_disconnect_destination", "10.0.0.0/8")))
    return AzVmNetworkDisconnectInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        destination=dest,
    )


def _build_az_vm_stop_service(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    svc = str(p.get("service", ctx.get("stop_service_name", "myservice")))
    return AzVmStopServiceInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        service=svc,
    )


def _build_az_vm_lifecycle(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "deallocate"))
    return AzVmLifecycleInjector(
        resource_group=str(ctx["resource_group"]),
        vm_name=str(ctx["vm_name"]),
        action=action,
    )


def _build_az_vmss_lifecycle(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "deallocate"))
    return AzVmssLifecycleInjector(
        resource_group=str(ctx["resource_group"]),
        vmss_name=str(ctx["vmss_name"]),
        action=action,
    )


def _build_az_redis_reboot(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzRedisRebootInjector(
        resource_group=str(ctx["resource_group"]),
        cache_name=str(ctx["redis_cache_name"]),
        reboot_type=str(p.get("reboot_type", "AllNodes")),
    )


def _build_az_cosmosdb_failover(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzCosmosFailoverInjector(
        resource_group=str(ctx["resource_group"]),
        account_name=str(ctx["cosmos_account_name"]),
        original_priorities=str(p.get("original_priorities", "")),
        failover_priorities=str(p.get("failover_priorities", "")),
    )


def _build_az_keyvault_deny(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzKeyVaultDenyAccessInjector(
        resource_group=str(ctx["resource_group"]),
        vault_name=str(ctx["keyvault_name"]),
        original_default_action=str(p.get("original_default_action", "Allow")),
    )


def _build_az_nsg_rule(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzNsgRuleInjector(
        resource_group=str(ctx["resource_group"]),
        nsg_name=str(ctx["nsg_name"]),
        rule_name=str(ctx.get("nsg_rule_name", "fdai-chaos-deny")),
        priority=int(ctx.get("nsg_rule_priority", 100)),
        destination=str(p.get("destination", "*")),
    )


def _build_az_lb_backend_remove(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    return AzLbBackendRemoveInjector(
        resource_group=str(ctx["resource_group"]),
        lb_name=str(ctx["lb_name"]),
        pool_name=str(ctx["lb_pool_name"]),
        address_name=str(ctx["lb_address_name"]),
        address_ip=ctx.get("lb_address_ip"),
    )


def _build_az_servicebus_firewall(entry: CatalogEntry, ctx: dict[str, Any]) -> FaultInjector:
    p = entry.spec.get("params") or {}
    return AzServiceBusFirewallInjector(
        resource_group=str(ctx["resource_group"]),
        namespace_name=str(ctx["servicebus_namespace"]),
        original_default_action=str(p.get("original_default_action", "Allow")),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_default_builders(factory: ScenarioFactory) -> ScenarioFactory:
    """Register every builder the delivery layer ships today.

    Idempotent - calling twice re-registers the same builders.
    """
    # Injectors: one prefix registration covers all chaos-mesh:<Kind> scenarios.
    factory.register_injector("chaos-mesh", _build_chaos_mesh)
    factory.register_injector("litmus", _build_litmus)
    factory.register_injector("kubectl:pod-kill", _build_kubectl_pod_kill)
    factory.register_injector("kubectl:scale", _build_kubectl_scale)
    factory.register_injector("kubectl:set-image", _build_kubectl_set_image)
    factory.register_injector("az:vm-run-command", _build_az_vm_run_command)
    factory.register_injector("mysql:query-load", _build_mysql_query_load)
    factory.register_injector("aoai:rate-limit", _build_aoai_rate_limit)
    # Azure Chaos Studio equivalents (direct az CLI, no Chaos Studio service).
    factory.register_injector("az:vm-network-latency", _build_az_vm_network_latency)
    factory.register_injector("az:vm-packet-loss", _build_az_vm_packet_loss)
    factory.register_injector("az:vm-network-disconnect", _build_az_vm_network_disconnect)
    factory.register_injector("az:vm-stop-service", _build_az_vm_stop_service)
    factory.register_injector("az:vm-lifecycle", _build_az_vm_lifecycle)
    factory.register_injector("az:vmss-lifecycle", _build_az_vmss_lifecycle)
    factory.register_injector("az:redis-reboot", _build_az_redis_reboot)
    factory.register_injector("az:cosmosdb-failover", _build_az_cosmosdb_failover)
    factory.register_injector("az:keyvault-deny", _build_az_keyvault_deny)
    factory.register_injector("az:nsg-rule", _build_az_nsg_rule)
    factory.register_injector("az:lb-backend-remove", _build_az_lb_backend_remove)
    factory.register_injector("az:servicebus-firewall", _build_az_servicebus_firewall)

    # Probes: one per expected_signal. Chaos-mesh entries default to the
    # CRD status probe; the shipped Kube probes take over for kubectl-*
    # / az-* scenarios via the per-signal dispatch inside the probe
    # builder.
    factory.register_probe("pod_restart", _build_pod_restart_probe)
    factory.register_probe("backend_health", _build_backend_health_probe)
    factory.register_probe("rollout_stall", _build_rollout_stall_probe)
    factory.register_probe("host_cpu", _build_host_cpu_probe)
    factory.register_probe("host_memory", _build_host_memory_probe)
    factory.register_probe("db_cpu", _build_db_cpu_probe)
    factory.register_probe("rate_limit", _build_rate_limit_probe)
    # Every remaining chaos-mesh-backed signal reads through the CRD
    # status probe (Chaos Mesh's AllInjected). Wiring a metric-backed
    # probe per signal (gateway_latency Kusto, request_failure SLO burn,
    # node_cpu Prometheus, etc.) is per-fork composition-root work.
    for cm_signal in (
        "gateway_latency",
        "request_failure",
        "node_cpu",
    ):
        factory.register_probe(cm_signal, _build_cm_status_probe)
    return factory


def default_factory() -> ScenarioFactory:
    """Return a ready-to-use factory with every default builder registered."""
    return register_default_builders(ScenarioFactory())


__all__ = ["default_factory", "register_default_builders"]
