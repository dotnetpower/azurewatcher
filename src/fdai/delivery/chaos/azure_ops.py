"""Additional Azure delivery-layer chaos injectors.

Extends the base :mod:`fdai.delivery.chaos.live_injectors` (which ships VM
CPU + memory stressors) with the injectors the Azure Chaos Studio scenario
family maps to. Chaos Studio the service is NOT required - every fault
under `rule-catalog/chaos-scenarios/collected/azure-chaos-studio/` is a
thin wrapper over `az` CLI operations FDAI can invoke directly:

Guest-OS agent-based (all via `az vm run-command invoke`):
- :class:`AzVmNetworkLatencyInjector` - `tc qdisc add netem delay`.
- :class:`AzVmPacketLossInjector` - `tc qdisc add netem loss`.
- :class:`AzVmNetworkDisconnectInjector` - `iptables -A OUTPUT ... DROP`.
- :class:`AzVmStopServiceInjector` - `systemctl stop / start`.

Resource-level ARM operations (single `az ... action` + reverse):
- :class:`AzVmLifecycleInjector` - shutdown / start, redeploy, VMSS.
- :class:`AzRedisRebootInjector` - `az redis force-reboot` (one-way).
- :class:`AzCosmosFailoverInjector` - `az cosmosdb failover-priority-change`
  (reverses to the original priority on stop).
- :class:`AzKeyVaultDenyAccessInjector` - toggle `publicNetworkAccess`
  or add/remove a network rule.
- :class:`AzNsgRuleInjector` - add/remove a deny rule.
- :class:`AzLbBackendRemoveInjector` - detach/reattach a backend address.
- :class:`AzServiceBusFirewallInjector` - flip the Service Bus namespace
  firewall to `Deny`, restore.

Design invariants shared with :mod:`live_injectors`:
- Subprocess over `az` only. No Azure SDK import, no HTTP client.
- Every ``stop`` is idempotent (safe to call twice) and reverses the
  perturbation, so the harness ``finally`` rollback holds.
- `target` is an opaque label the caller pre-scoped to the blast-radius
  cap; the injector reads its wiring from the injected identifiers
  (resource_group, vm_name, etc.), never from `target` verbatim.

`core/` never imports this module - only the composition-root factory in
:mod:`fdai.delivery.chaos.factories` wires the builders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from fdai.delivery.chaos.live_injectors import _run

_RC_TIMEOUT: Final[float] = 180.0
_ARM_TIMEOUT: Final[float] = 120.0


# ---------------------------------------------------------------------------
# Guest-OS agent-based (az vm run-command)
# ---------------------------------------------------------------------------


async def _vm_run_command(
    az: str,
    resource_group: str,
    vm_name: str,
    script: str,
    *,
    timeout: float = _RC_TIMEOUT,
) -> tuple[int, str, str]:
    """One-shot `az vm run-command invoke` returning (rc, stdout, stderr)."""
    return await _run(
        [
            az,
            "vm",
            "run-command",
            "invoke",
            "-g",
            resource_group,
            "-n",
            vm_name,
            "--command-id",
            "RunShellScript",
            "--scripts",
            script,
            "--query",
            "value[0].message",
            "-o",
            "tsv",
        ],
        timeout=timeout,
        drop_azure_config_dir=True,
    )


class AzVmNetworkLatencyInjector:
    """Sustain outbound network latency on a VM via `tc netem delay`."""

    fault_type = "network_delay"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        latency_ms: int = 250,
        interface: str = "eth0",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._latency = int(latency_ms)
        self._iface = interface
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        latency = int(params.get("latency_ms", self._latency))
        iface = str(params.get("interface", self._iface))
        # tc netem is idempotent-ish; delete first so we do not double-add.
        script = (
            f"tc qdisc del dev {iface} root 2>/dev/null; "
            f"tc qdisc add dev {iface} root netem delay {latency}ms && echo added"
        )
        rc, _out, err = await _vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"az vm run-command tc netem delay failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"tc qdisc del dev {self._iface} root 2>/dev/null; echo cleared"
        await _vm_run_command(self._az, self._rg, self._vm, script)


class AzVmPacketLossInjector:
    """Drop a fraction of outbound packets via `tc netem loss`."""

    fault_type = "network_loss"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        loss_percent: int = 20,
        interface: str = "eth0",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vm = vm_name
        self._loss = int(loss_percent)
        self._iface = interface
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        loss = int(params.get("loss_percent", self._loss))
        iface = str(params.get("interface", self._iface))
        script = (
            f"tc qdisc del dev {iface} root 2>/dev/null; "
            f"tc qdisc add dev {iface} root netem loss {loss}% && echo added"
        )
        rc, _out, err = await _vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"az vm run-command tc netem loss failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"tc qdisc del dev {self._iface} root 2>/dev/null; echo cleared"
        await _vm_run_command(self._az, self._rg, self._vm, script)


class AzVmNetworkDisconnectInjector:
    """Fully block outbound traffic to a destination via iptables DROP."""

    fault_type = "network_disconnect"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        destination: str,
        az: str = "az",
    ) -> None:
        if not destination:
            raise ValueError("destination MUST be non-empty (host or CIDR)")
        self._rg = resource_group
        self._vm = vm_name
        self._dest = destination
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        dest = str(params.get("destination", self._dest))
        # -I so it wins over any existing ACCEPT; harmless if already present.
        script = f"iptables -I OUTPUT -d {dest} -j DROP && echo blocked"
        rc, _out, err = await _vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"iptables DROP add failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"iptables -D OUTPUT -d {self._dest} -j DROP 2>/dev/null; echo cleared"
        await _vm_run_command(self._az, self._rg, self._vm, script)


class AzVmStopServiceInjector:
    """Stop a systemd unit on a VM; start it back on rollback."""

    fault_type = "stop_service"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        service: str,
        az: str = "az",
    ) -> None:
        if not service:
            raise ValueError("service MUST be non-empty")
        self._rg = resource_group
        self._vm = vm_name
        self._svc = service
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        svc = str(params.get("service", self._svc))
        script = f"systemctl stop {svc} && echo stopped"
        rc, _out, err = await _vm_run_command(self._az, self._rg, self._vm, script)
        if rc != 0:
            raise RuntimeError(f"systemctl stop {svc} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        script = f"systemctl start {self._svc}; echo started"
        await _vm_run_command(self._az, self._rg, self._vm, script)


# ---------------------------------------------------------------------------
# ARM operations (az <service> <verb>)
# ---------------------------------------------------------------------------


async def _az(cmd: Sequence[str], *, timeout: float = _ARM_TIMEOUT) -> tuple[int, str, str]:
    return await _run(cmd, timeout=timeout, drop_azure_config_dir=True)


class AzVmLifecycleInjector:
    """Deallocate a VM; start it back on rollback.

    Distinct from :class:`~fdai.delivery.chaos.live_injectors.AzVmCpuStressInjector`
    - this one perturbs the whole VM lifecycle, not the guest OS.
    """

    fault_type = "vm_lifecycle"

    def __init__(
        self,
        *,
        resource_group: str,
        vm_name: str,
        action: str = "deallocate",
        az: str = "az",
    ) -> None:
        if action not in {"deallocate", "restart", "redeploy"}:
            raise ValueError(f"unknown VM lifecycle action {action!r}")
        self._rg = resource_group
        self._vm = vm_name
        self._action = action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        action = str(params.get("action", self._action))
        rc, _out, err = await _az([self._az, "vm", action, "-g", self._rg, "-n", self._vm])
        if rc != 0:
            raise RuntimeError(f"az vm {action} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        # For deallocate and redeploy the reverse is `start`; for `restart`
        # nothing is needed (systemd is already running post-restart).
        if self._action == "restart":
            return
        await _az([self._az, "vm", "start", "-g", self._rg, "-n", self._vm])


class AzVmssLifecycleInjector:
    """Deallocate a VMSS (all instances); start it back on rollback."""

    fault_type = "vmss_lifecycle"

    def __init__(
        self,
        *,
        resource_group: str,
        vmss_name: str,
        action: str = "deallocate",
        az: str = "az",
    ) -> None:
        if action not in {"deallocate", "restart"}:
            raise ValueError(f"unknown VMSS lifecycle action {action!r}")
        self._rg = resource_group
        self._vmss = vmss_name
        self._action = action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        action = str(params.get("action", self._action))
        rc, _out, err = await _az([self._az, "vmss", action, "-g", self._rg, "-n", self._vmss])
        if rc != 0:
            raise RuntimeError(f"az vmss {action} failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        if self._action == "restart":
            return
        await _az([self._az, "vmss", "start", "-g", self._rg, "-n", self._vmss])


class AzRedisRebootInjector:
    """Force-reboot Azure Cache for Redis node(s); no reverse (one-way)."""

    fault_type = "redis_reboot"

    def __init__(
        self,
        *,
        resource_group: str,
        cache_name: str,
        reboot_type: str = "AllNodes",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._cache = cache_name
        self._reboot_type = reboot_type
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rt = str(params.get("reboot_type", self._reboot_type))
        rc, _out, err = await _az(
            [
                self._az,
                "redis",
                "force-reboot",
                "-g",
                self._rg,
                "-n",
                self._cache,
                "--reboot-type",
                rt,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az redis force-reboot failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        # Reboot is a one-shot; nothing to undo. Monitor cache back to healthy.
        return None


class AzCosmosFailoverInjector:
    """Force a Cosmos DB region failover; reverse to the prior priority on stop."""

    fault_type = "cosmosdb_failover"

    def __init__(
        self,
        *,
        resource_group: str,
        account_name: str,
        original_priorities: str,
        failover_priorities: str,
        az: str = "az",
    ) -> None:
        if not original_priorities or not failover_priorities:
            raise ValueError("original_priorities and failover_priorities MUST be non-empty")
        self._rg = resource_group
        self._account = account_name
        self._original = original_priorities
        self._failover = failover_priorities
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        prios = str(params.get("failover_priorities", self._failover))
        rc, _out, err = await _az(
            [
                self._az,
                "cosmosdb",
                "failover-priority-change",
                "-g",
                self._rg,
                "-n",
                self._account,
                "--failover-policies",
                prios,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az cosmosdb failover-priority-change failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await _az(
            [
                self._az,
                "cosmosdb",
                "failover-priority-change",
                "-g",
                self._rg,
                "-n",
                self._account,
                "--failover-policies",
                self._original,
            ]
        )


class AzKeyVaultDenyAccessInjector:
    """Toggle a Key Vault's default network action to `Deny`; restore on stop."""

    fault_type = "keyvault_deny_access"

    def __init__(
        self,
        *,
        resource_group: str,
        vault_name: str,
        original_default_action: str = "Allow",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._vault = vault_name
        self._original = original_default_action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _az(
            [
                self._az,
                "keyvault",
                "network-rule",
                "add",
                "--name",
                self._vault,
                "-g",
                self._rg,
                "--default-action",
                "Deny",
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az keyvault network-rule set Deny failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await _az(
            [
                self._az,
                "keyvault",
                "update",
                "--name",
                self._vault,
                "-g",
                self._rg,
                "--default-action",
                self._original,
            ]
        )


class AzNsgRuleInjector:
    """Add a deny NSG rule; remove it on stop."""

    fault_type = "nsg_rule"

    def __init__(
        self,
        *,
        resource_group: str,
        nsg_name: str,
        rule_name: str = "fdai-chaos-deny",
        priority: int = 100,
        destination: str = "*",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._nsg = nsg_name
        self._rule = rule_name
        self._priority = int(priority)
        self._dest = destination
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        dest = str(params.get("destination", self._dest))
        rc, _out, err = await _az(
            [
                self._az,
                "network",
                "nsg",
                "rule",
                "create",
                "-g",
                self._rg,
                "--nsg-name",
                self._nsg,
                "-n",
                self._rule,
                "--priority",
                str(self._priority),
                "--access",
                "Deny",
                "--direction",
                "Outbound",
                "--protocol",
                "*",
                "--destination-address-prefixes",
                dest,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az network nsg rule create failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await _az(
            [
                self._az,
                "network",
                "nsg",
                "rule",
                "delete",
                "-g",
                self._rg,
                "--nsg-name",
                self._nsg,
                "-n",
                self._rule,
            ]
        )


class AzLbBackendRemoveInjector:
    """Remove a backend address from a Load Balancer pool; re-add on stop."""

    fault_type = "lb_backend_remove"

    def __init__(
        self,
        *,
        resource_group: str,
        lb_name: str,
        pool_name: str,
        address_name: str,
        address_ip: str | None = None,
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._lb = lb_name
        self._pool = pool_name
        self._addr = address_name
        self._addr_ip = address_ip
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _az(
            [
                self._az,
                "network",
                "lb",
                "address-pool",
                "address",
                "remove",
                "-g",
                self._rg,
                "--lb-name",
                self._lb,
                "--pool-name",
                self._pool,
                "-n",
                self._addr,
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az network lb address remove failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        if not self._addr_ip:
            return
        await _az(
            [
                self._az,
                "network",
                "lb",
                "address-pool",
                "address",
                "add",
                "-g",
                self._rg,
                "--lb-name",
                self._lb,
                "--pool-name",
                self._pool,
                "-n",
                self._addr,
                "--ip-address",
                self._addr_ip,
            ]
        )


class AzServiceBusFirewallInjector:
    """Flip a Service Bus namespace default network action to `Deny`; restore on stop."""

    fault_type = "servicebus_firewall"

    def __init__(
        self,
        *,
        resource_group: str,
        namespace_name: str,
        original_default_action: str = "Allow",
        az: str = "az",
    ) -> None:
        self._rg = resource_group
        self._ns = namespace_name
        self._original = original_default_action
        self._az = az

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        rc, _out, err = await _az(
            [
                self._az,
                "servicebus",
                "namespace",
                "network-rule-set",
                "update",
                "-g",
                self._rg,
                "--namespace-name",
                self._ns,
                "--default-action",
                "Deny",
            ]
        )
        if rc != 0:
            raise RuntimeError(f"az servicebus network-rule-set Deny failed: {err.strip()}")

    async def stop(self, *, target: str) -> None:
        await _az(
            [
                self._az,
                "servicebus",
                "namespace",
                "network-rule-set",
                "update",
                "-g",
                self._rg,
                "--namespace-name",
                self._ns,
                "--default-action",
                self._original,
            ]
        )


class AzCliStateProbe:
    """Observe an injected Azure/guest state through one read-only az command."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        expected_substrings: Sequence[str] = (),
        absent_substrings: Sequence[str] = (),
    ) -> None:
        if not command:
            raise ValueError("command MUST be non-empty")
        if not expected_substrings and not absent_substrings:
            raise ValueError("at least one expected or absent substring is required")
        self._command = tuple(command)
        self._expected = tuple(expected_substrings)
        self._absent = tuple(absent_substrings)

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        rc, out, _err = await _az(self._command)
        if rc != 0:
            return False
        return all(value in out for value in self._expected) and all(
            value not in out for value in self._absent
        )


__all__ = [
    "AzCliStateProbe",
    "AzCosmosFailoverInjector",
    "AzKeyVaultDenyAccessInjector",
    "AzLbBackendRemoveInjector",
    "AzNsgRuleInjector",
    "AzRedisRebootInjector",
    "AzServiceBusFirewallInjector",
    "AzVmLifecycleInjector",
    "AzVmNetworkDisconnectInjector",
    "AzVmNetworkLatencyInjector",
    "AzVmPacketLossInjector",
    "AzVmStopServiceInjector",
    "AzVmssLifecycleInjector",
]
