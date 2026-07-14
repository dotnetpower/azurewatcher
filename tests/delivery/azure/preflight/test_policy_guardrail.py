"""httpx-mocked tests for the live Azure Policy guardrail probe (issue #13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from fdai.delivery.azure.preflight import (
    ArmClientConfig,
    AzureArmClient,
    AzurePolicyGuardrailProbe,
    AzurePolicyProbeConfig,
    AzurePreflightError,
)
from fdai.shared.providers.feasibility_probe import (
    PreflightTarget,
    ProbeCategory,
    ResolutionKind,
)
from fdai.shared.providers.local.feasibility import ToggleResolution
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_SUB = "00000000-0000-0000-0000-000000000001"
_DISK = "Microsoft.Compute/disks"
_PUBLIC_IP = "Microsoft.Network/publicIPAddresses"


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - fake token, not a secret
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _assignments(*definition_ids_and_params: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "value": [
            {
                "id": f"/assign/{i}",
                "name": f"assign-{i}",
                "properties": {"policyDefinitionId": def_id, "parameters": params},
            }
            for i, (def_id, params) in enumerate(definition_ids_and_params)
        ]
    }


_NOT_ALLOWED_DEF_ID = "/providers/Microsoft.Authorization/policyDefinitions/not-allowed-types"
_ALLOWED_DEF_ID = "/providers/Microsoft.Authorization/policyDefinitions/allowed-types"

_NOT_ALLOWED_DEF = {
    "name": "not-allowed-types",
    "properties": {
        "parameters": {"listOfResourceTypesNotAllowed": {"defaultValue": []}},
        "policyRule": {
            "if": {
                "field": "type",
                "in": "[parameters('listOfResourceTypesNotAllowed')]",
            },
            "then": {"effect": "deny"},
        },
    },
}

_ALLOWED_DEF = {
    "name": "allowed-types",
    "properties": {
        "parameters": {"listOfResourceTypesAllowed": {"defaultValue": []}},
        "policyRule": {
            "if": {
                "not": {
                    "field": "type",
                    "in": "[parameters('listOfResourceTypesAllowed')]",
                }
            },
            "then": {"effect": "Deny"},
        },
    },
}


def _handler(routes: dict[str, dict[str, Any]]):
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for needle, payload in routes.items():
            if needle in path:
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "not found"})

    return handle


def _probe(handler, config: AzurePolicyProbeConfig) -> AzurePolicyGuardrailProbe:
    client = AzureArmClient(
        identity=_StaticIdentity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=ArmClientConfig(),
    )
    return AzurePolicyGuardrailProbe(client=client, config=config)


def _config(**overrides: Any) -> AzurePolicyProbeConfig:
    base: dict[str, Any] = {"subscription_id": _SUB, "resource_group": "rg-app"}
    base.update(overrides)
    return AzurePolicyProbeConfig(**base)


async def test_not_allowed_resource_type_denied_maps_to_toggle() -> None:
    handler = _handler(
        {
            "policyAssignments": _assignments(
                (_NOT_ALLOWED_DEF_ID, {"listOfResourceTypesNotAllowed": {"value": [_DISK]}}),
            ),
            "policyDefinitions/not-allowed-types": _NOT_ALLOWED_DEF,
        }
    )
    probe = _probe(
        handler,
        _config(
            resolutions={
                _DISK: ToggleResolution(
                    module="compute",
                    set_vars={"disk_provisioning": "attach_existing"},
                    autofix=True,
                )
            }
        ),
    )
    findings = await probe.evaluate(PreflightTarget(scope="rg:app", resource_types=(_DISK,)))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.category is ProbeCategory.POLICY_GUARDRAIL
    assert finding.evidence.source == "policy:not-allowed-types"
    assert finding.resolution.kind is ResolutionKind.TERRAFORM_TOGGLE
    assert finding.resolution.set_vars == {"disk_provisioning": "attach_existing"}
    assert finding.resolution.autofix is True


async def test_not_allowed_without_resolution_is_manual() -> None:
    handler = _handler(
        {
            "policyAssignments": _assignments(
                (_NOT_ALLOWED_DEF_ID, {"listOfResourceTypesNotAllowed": {"value": [_DISK]}}),
            ),
            "policyDefinitions/not-allowed-types": _NOT_ALLOWED_DEF,
        }
    )
    probe = _probe(handler, _config())
    findings = await probe.evaluate(PreflightTarget(scope="rg:app", resource_types=(_DISK,)))
    assert len(findings) == 1
    assert findings[0].resolution.kind is ResolutionKind.MANUAL


async def test_allowed_list_denies_type_outside_it() -> None:
    handler = _handler(
        {
            "policyAssignments": _assignments(
                (_ALLOWED_DEF_ID, {"listOfResourceTypesAllowed": {"value": [_DISK]}}),
            ),
            "policyDefinitions/allowed-types": _ALLOWED_DEF,
        }
    )
    probe = _probe(handler, _config())
    # public IP is NOT in the allow-list -> denied; disk IS allowed -> clear.
    findings = await probe.evaluate(
        PreflightTarget(scope="rg:app", resource_types=(_DISK, _PUBLIC_IP))
    )
    assert [f.title for f in findings] == [f"{_PUBLIC_IP} denied by policy allowed-types"]


async def test_type_not_denied_yields_no_finding() -> None:
    handler = _handler(
        {
            "policyAssignments": _assignments(
                (_NOT_ALLOWED_DEF_ID, {"listOfResourceTypesNotAllowed": {"value": [_PUBLIC_IP]}}),
            ),
            "policyDefinitions/not-allowed-types": _NOT_ALLOWED_DEF,
        }
    )
    probe = _probe(handler, _config())
    findings = await probe.evaluate(PreflightTarget(scope="rg:app", resource_types=(_DISK,)))
    assert findings == ()


async def test_non_deny_effect_is_ignored() -> None:
    audit_def = {
        "name": "audit-types",
        "properties": {
            "policyRule": {
                "if": {"field": "type", "in": [_DISK]},
                "then": {"effect": "audit"},
            }
        },
    }
    handler = _handler(
        {
            "policyAssignments": _assignments(
                ("/providers/Microsoft.Authorization/policyDefinitions/audit-types", {}),
            ),
            "policyDefinitions/audit-types": audit_def,
        }
    )
    probe = _probe(handler, _config())
    findings = await probe.evaluate(PreflightTarget(scope="rg:app", resource_types=(_DISK,)))
    assert findings == ()


async def test_empty_target_types_skips_all_calls() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no ARM call expected for an empty target")

    probe = _probe(handle, _config())
    assert await probe.evaluate(PreflightTarget(scope="rg:app")) == ()


async def test_arm_error_propagates_fail_closed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if "policyAssignments" in request.url.path:
            return httpx.Response(500, text="boom")
        return httpx.Response(404)

    probe = _probe(handle, _config())
    with pytest.raises(AzurePreflightError):
        await probe.evaluate(PreflightTarget(scope="rg:app", resource_types=(_DISK,)))
