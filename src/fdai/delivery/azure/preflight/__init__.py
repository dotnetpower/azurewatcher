"""Live Azure preflight probe adapters (shadow-first).

Realizes the :class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
seam against real Azure control-plane state, replacing the config-driven
upstream defaults (:mod:`fdai.shared.providers.local.feasibility`) at the
composition root. ``core/`` never imports this package; each probe is bound via
the ``Container.feasibility_probes`` seam.

This is delivery increment 1 from
``docs/roadmap/deployment/deployment-preflight.md`` (Live Azure adapters):

- :class:`AzurePolicyGuardrailProbe` - reads real Azure Policy ``deny``
  guardrails (``Not allowed`` / ``Allowed resource types``).
- :class:`AzureQuotaProbe` - reads real Compute usages for a subscription +
  location.

Both are read-only, fail-closed, and shadow-first (they report; the
``blocks_deploy`` flag gates). The Firewall/NSG egress and Resource-Graph
identity adapters are staged as later increments.
"""

from __future__ import annotations

from fdai.delivery.azure.preflight._client import (
    ArmClientConfig,
    AzureArmClient,
    AzurePreflightError,
)
from fdai.delivery.azure.preflight.identity_rbac import AzureIdentityRbacProbe
from fdai.delivery.azure.preflight.policy_guardrail import (
    AzurePolicyGuardrailProbe,
    AzurePolicyProbeConfig,
)
from fdai.delivery.azure.preflight.quota_capacity import (
    AzureQuotaProbe,
    AzureQuotaProbeConfig,
    QuotaCheck,
)
from fdai.delivery.azure.preflight.secret_config import (
    AzureSecretConfigProbe,
    AzureSecretProbeConfig,
    AzureSecretProbeError,
)

__all__ = [
    "ArmClientConfig",
    "AzureArmClient",
    "AzureIdentityRbacProbe",
    "AzurePolicyGuardrailProbe",
    "AzurePolicyProbeConfig",
    "AzurePreflightError",
    "AzureQuotaProbe",
    "AzureQuotaProbeConfig",
    "AzureSecretConfigProbe",
    "AzureSecretProbeConfig",
    "AzureSecretProbeError",
    "QuotaCheck",
]
