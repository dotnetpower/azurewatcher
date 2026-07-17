"""Normalize trusted Azure, APIM, and self-hosted model observations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.delivery.trust.ed25519 import Ed25519ModelEndpointRegistrationVerifier
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointBinding,
    ModelEndpointCapacity,
    ModelEndpointDiscovery,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
)


@dataclass(frozen=True, slots=True)
class ModelEndpointObservation:
    """Management-plane or signed-registration endpoint evidence."""

    binding_id: str
    capability: str
    provider_kind: ModelProviderKind
    route_kind: ModelRouteKind
    api_style: ModelApiStyle
    endpoint_ref: str
    deployment: str
    api_version: str | None
    auth_kind: ModelAuthKind
    auth_audience: str | None
    publisher: str
    family: str
    version: str | None
    capacity_unit: ModelCapacityUnit
    capacity_value: int
    features: ModelEndpointFeatures
    source: ModelDiscoverySource
    provider_resource_ref: str
    observed_at: datetime
    trust_verified: bool = True

    def __post_init__(self) -> None:
        if not self.provider_resource_ref.strip():
            raise ValueError("model endpoint observation resource reference MUST be non-empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("model endpoint observation timestamp MUST be timezone-aware")
        if self.source is ModelDiscoverySource.SIGNED_REGISTRATION and not self.trust_verified:
            raise ValueError("self-hosted model registration signature is not verified")
        if self.source is not ModelDiscoverySource.SIGNED_REGISTRATION and not self.trust_verified:
            raise ValueError("management-plane model observation is not trusted")
        if self.source is ModelDiscoverySource.APIM_MANAGEMENT and (
            self.route_kind is not ModelRouteKind.APIM_GATEWAY
        ):
            raise ValueError("APIM management observations require an APIM gateway route")
        if self.source is ModelDiscoverySource.AZURE_MANAGEMENT and (
            self.provider_kind is not ModelProviderKind.AZURE_OPENAI
        ):
            raise ValueError("Azure management observations require Azure OpenAI provider")
        if self.source is ModelDiscoverySource.SIGNED_REGISTRATION and (
            self.provider_kind is not ModelProviderKind.SELF_HOSTED
        ):
            raise ValueError("signed registrations require a self-hosted provider")


@runtime_checkable
class ModelEndpointObservationSource(Protocol):
    """Read-only source backed by ARM, APIM management, or a signed catalog."""

    async def list_observations(self) -> tuple[ModelEndpointObservation, ...]: ...


class ModelEndpointDiscoveryError(RuntimeError):
    """Endpoint observations cannot form one unambiguous resolved inventory."""


@dataclass(frozen=True, slots=True)
class SignedModelEndpointRegistration:
    source: str
    document: bytes
    signature: bytes

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.document:
            raise ValueError("signed model endpoint registration fields MUST be non-empty")


@dataclass(frozen=True, slots=True)
class Ed25519SignedRegistrationSource:
    """Emit self-hosted observations only after publisher signature verification."""

    registrations: tuple[SignedModelEndpointRegistration, ...]
    verifier: Ed25519ModelEndpointRegistrationVerifier
    parser: Callable[[bytes], ModelEndpointObservation]

    async def list_observations(self) -> tuple[ModelEndpointObservation, ...]:
        observations: list[ModelEndpointObservation] = []
        for registration in self.registrations:
            if not self.verifier.verify(
                source=registration.source,
                document=registration.document,
                signature=registration.signature,
            ):
                raise ModelEndpointDiscoveryError(
                    f"model endpoint registration from {registration.source!r} is untrusted"
                )
            observation = self.parser(registration.document)
            if observation.source is not ModelDiscoverySource.SIGNED_REGISTRATION:
                raise ModelEndpointDiscoveryError(
                    "signed model endpoint parser returned a non-registration source"
                )
            observations.append(observation)
        return tuple(observations)


async def discover_model_endpoints(
    sources: tuple[ModelEndpointObservationSource, ...],
) -> tuple[ModelEndpointBinding, ...]:
    """Collect verified observations and return deterministic capability bindings."""
    observations: list[ModelEndpointObservation] = []
    for source in sources:
        observations.extend(await source.list_observations())
    observations.sort(key=lambda item: (item.capability, item.binding_id))
    capabilities: set[str] = set()
    binding_ids: set[str] = set()
    bindings: list[ModelEndpointBinding] = []
    for observation in observations:
        if observation.capability in capabilities:
            raise ModelEndpointDiscoveryError(
                f"multiple endpoint observations resolved capability {observation.capability!r}"
            )
        if observation.binding_id in binding_ids:
            raise ModelEndpointDiscoveryError(
                f"duplicate endpoint binding id {observation.binding_id!r}"
            )
        capabilities.add(observation.capability)
        binding_ids.add(observation.binding_id)
        bindings.append(_binding(observation))
    return tuple(bindings)


def _binding(observation: ModelEndpointObservation) -> ModelEndpointBinding:
    resource_digest = hashlib.sha256(observation.provider_resource_ref.encode()).hexdigest()
    return ModelEndpointBinding(
        binding_id=observation.binding_id,
        capability=observation.capability,
        provider_kind=observation.provider_kind,
        route_kind=observation.route_kind,
        api_style=observation.api_style,
        endpoint_ref=observation.endpoint_ref,
        deployment=observation.deployment,
        api_version=observation.api_version,
        auth_kind=observation.auth_kind,
        auth_audience=observation.auth_audience,
        publisher=observation.publisher,
        family=observation.family,
        version=observation.version,
        capacity=ModelEndpointCapacity(
            unit=observation.capacity_unit,
            value=observation.capacity_value,
        ),
        features=observation.features,
        discovery=ModelEndpointDiscovery(
            source=observation.source,
            resource_ref_digest=resource_digest,
            verified_at=observation.observed_at,
        ),
    )


__all__ = [
    "Ed25519SignedRegistrationSource",
    "ModelEndpointDiscoveryError",
    "ModelEndpointObservation",
    "ModelEndpointObservationSource",
    "SignedModelEndpointRegistration",
    "discover_model_endpoints",
]
