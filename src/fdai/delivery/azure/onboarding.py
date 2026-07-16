"""Azure Resource Graph probe for post-provision onboarding verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.core.onboarding import (
    ObservedResource,
    ObservedRoleAssignment,
    OnboardingProbeError,
    OnboardingResourceKind,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_ENDPOINT: Final[str] = "https://management.azure.com"
_DEFAULT_API_VERSION: Final[str] = "2022-10-01"
_DEFAULT_AUDIENCE: Final[str] = "https://management.azure.com/.default"

_TYPE_TO_KIND: Final[dict[str, OnboardingResourceKind]] = {
    "microsoft.managedidentity/userassignedidentities": OnboardingResourceKind.EXECUTOR_IDENTITY,
    "microsoft.app/containerapps": OnboardingResourceKind.RUNTIME,
    "microsoft.containerregistry/registries": OnboardingResourceKind.CONTAINER_REGISTRY,
    "microsoft.dbforpostgresql/flexibleservers": OnboardingResourceKind.STATE_STORE,
    "microsoft.eventhub/namespaces": OnboardingResourceKind.EVENT_BUS,
    "microsoft.keyvault/vaults": OnboardingResourceKind.SECRET_STORE,
    "microsoft.operationalinsights/workspaces": OnboardingResourceKind.OBSERVABILITY_LOGS,
    "microsoft.insights/components": OnboardingResourceKind.OBSERVABILITY_APM,
}


@dataclass(frozen=True, slots=True)
class AzureOnboardingProbeConfig:
    subscription_id: str
    resource_group: str
    executor_principal_id: str
    event_role_definition_id: str
    secret_role_definition_id: str
    endpoint: str = _DEFAULT_ENDPOINT
    api_version: str = _DEFAULT_API_VERSION
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        for name in (
            "subscription_id",
            "resource_group",
            "executor_principal_id",
            "event_role_definition_id",
            "secret_role_definition_id",
        ):
            value = getattr(self, name)
            if not value or "'" in value or len(value) > 256:
                raise ValueError(f"{name} MUST be a bounded non-empty identifier")
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("endpoint MUST be an absolute HTTPS URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")


class AzureResourceProbe:
    """Observe the FDAI resource set and executor role assignments via ARG."""

    def __init__(
        self,
        *,
        config: AzureOnboardingProbeConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    async def observed_resources(self) -> tuple[ObservedResource, ...]:
        query = (
            "Resources "
            f"| where subscriptionId =~ '{self._config.subscription_id}' "
            f"| where resourceGroup =~ '{self._config.resource_group}' "
            "| project type"
        )
        rows = await self._query(query)
        kinds = {
            kind
            for row in rows
            if isinstance(row.get("type"), str)
            if (kind := _TYPE_TO_KIND.get(str(row["type"]).lower())) is not None
        }
        return tuple(ObservedResource(kind=kind) for kind in sorted(kinds, key=str))

    async def observed_role_assignments(self) -> tuple[ObservedRoleAssignment, ...]:
        query = (
            "AuthorizationResources "
            "| where type =~ 'microsoft.authorization/roleassignments' "
            f"| where tostring(properties.principalId) =~ '{self._config.executor_principal_id}' "
            "| project roleDefinitionId=tostring(properties.roleDefinitionId), "
            "scope=tostring(properties.scope)"
        )
        rows = await self._query(query)
        observed: set[tuple[str, OnboardingResourceKind]] = set()
        for row in rows:
            role_definition_id = str(row.get("roleDefinitionId") or "").lower()
            scope = str(row.get("scope") or "").lower()
            if role_definition_id.endswith(self._config.event_role_definition_id.lower()):
                observed.add(("event_bus_data_owner", OnboardingResourceKind.EVENT_BUS))
            if role_definition_id.endswith(self._config.secret_role_definition_id.lower()) and (
                "/providers/microsoft.keyvault/vaults/" in scope
            ):
                observed.add(("secret_reader", OnboardingResourceKind.SECRET_STORE))
        return tuple(
            ObservedRoleAssignment(principal_ref="executor", role=role, scope_kind=scope_kind)
            for role, scope_kind in sorted(observed, key=lambda item: item[0])
        )

    async def _query(self, query: str) -> tuple[dict[str, Any], ...]:
        try:
            token = await self._identity.get_token(self._config.audience)
        except Exception as exc:  # noqa: BLE001 - identity boundary fails closed
            raise OnboardingProbeError(
                f"Azure identity token request failed: {type(exc).__name__}"
            ) from exc
        url = (
            f"{self._config.endpoint.rstrip('/')}/providers/Microsoft.ResourceGraph/resources"
            f"?api-version={self._config.api_version}"
        )
        try:
            response = await self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=json.dumps(
                    {"subscriptions": [self._config.subscription_id], "query": query}
                ),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise OnboardingProbeError(
                f"Azure Resource Graph request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise OnboardingProbeError(f"Azure Resource Graph returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OnboardingProbeError("Azure Resource Graph returned non-JSON") from exc
        data = payload.get("data")
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise OnboardingProbeError("Azure Resource Graph response data MUST be an array")
        return tuple(data)


__all__ = ["AzureOnboardingProbeConfig", "AzureResourceProbe"]
