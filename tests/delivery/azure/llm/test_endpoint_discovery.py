"""Trusted heterogeneous model endpoint discovery tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.delivery.azure.llm.endpoint_discovery import (
    Ed25519SignedRegistrationSource,
    ModelEndpointDiscoveryError,
    ModelEndpointObservation,
    SignedModelEndpointRegistration,
    discover_model_endpoints,
)
from fdai.delivery.trust.ed25519 import (
    Ed25519ModelEndpointRegistrationVerifier,
    model_endpoint_registration_signature_payload,
)
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
)


class _Source:
    def __init__(self, *observations: ModelEndpointObservation) -> None:
        self._observations = observations

    async def list_observations(self) -> tuple[ModelEndpointObservation, ...]:
        return self._observations


def _observation(**changes: object) -> ModelEndpointObservation:
    values: dict[str, object] = {
        "binding_id": "t2-primary-prod",
        "capability": "t2.reasoner.primary",
        "provider_kind": ModelProviderKind.AZURE_OPENAI,
        "route_kind": ModelRouteKind.APIM_GATEWAY,
        "api_style": ModelApiStyle.AZURE_OPENAI,
        "endpoint_ref": "model-gateway-primary",
        "deployment": "t2-primary",
        "api_version": "2024-10-21",
        "auth_kind": ModelAuthKind.ENTRA,
        "auth_audience": "api://fdai-model-gateway",
        "publisher": "OpenAI",
        "family": "gpt-4o",
        "version": "2024-08-06",
        "capacity_unit": ModelCapacityUnit.PTU,
        "capacity_value": 30,
        "features": ModelEndpointFeatures(streaming=True, structured_output=True),
        "source": ModelDiscoverySource.APIM_MANAGEMENT,
        "provider_resource_ref": "/subscriptions/example/apim/model-gateway-primary",
        "observed_at": datetime(2026, 7, 17, tzinfo=UTC),
    }
    values.update(changes)
    return ModelEndpointObservation(**values)  # type: ignore[arg-type]


async def test_discovers_apim_and_signed_gpu_bindings_deterministically() -> None:
    gpu = _observation(
        binding_id="t2-secondary-gpu",
        capability="t2.reasoner.secondary",
        provider_kind=ModelProviderKind.SELF_HOSTED,
        api_style=ModelApiStyle.OPENAI_V1,
        endpoint_ref="model-gateway-secondary",
        deployment="qwen-instruct",
        publisher="Qwen",
        family="Qwen2.5-Instruct",
        version=None,
        capacity_unit=ModelCapacityUnit.GPU,
        capacity_value=2,
        source=ModelDiscoverySource.SIGNED_REGISTRATION,
        provider_resource_ref="registration:self-hosted:qwen-secondary",
    )

    bindings = await discover_model_endpoints((_Source(gpu), _Source(_observation())))

    assert [binding.capability for binding in bindings] == [
        "t2.reasoner.primary",
        "t2.reasoner.secondary",
    ]
    assert bindings[0].capacity.unit is ModelCapacityUnit.PTU
    assert bindings[1].capacity.unit is ModelCapacityUnit.GPU
    assert bindings[0].discovery.resource_ref_digest != bindings[1].discovery.resource_ref_digest


def test_rejects_unverified_self_hosted_registration() -> None:
    with pytest.raises(ValueError, match="signature"):
        _observation(
            provider_kind=ModelProviderKind.SELF_HOSTED,
            api_style=ModelApiStyle.OPENAI_V1,
            capacity_unit=ModelCapacityUnit.GPU,
            capacity_value=1,
            source=ModelDiscoverySource.SIGNED_REGISTRATION,
            trust_verified=False,
        )


def test_rejects_apim_observation_with_direct_route() -> None:
    with pytest.raises(ValueError, match="APIM gateway"):
        _observation(route_kind=ModelRouteKind.DIRECT)


async def test_rejects_multiple_routes_for_one_capability() -> None:
    with pytest.raises(ModelEndpointDiscoveryError, match="multiple endpoint observations"):
        await discover_model_endpoints(
            (_Source(_observation(binding_id="one"), _observation(binding_id="two")),)
        )


async def test_signed_registration_source_verifies_publisher_before_parsing() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    document = b'{"binding_id":"gpu-secondary"}'
    signature = private_key.sign(
        model_endpoint_registration_signature_payload("example-publisher", document)
    )
    parsed = False

    def parser(raw: bytes) -> ModelEndpointObservation:
        nonlocal parsed
        parsed = True
        assert raw == document
        return _observation(
            binding_id="gpu-secondary",
            capability="t2.reasoner.secondary",
            provider_kind=ModelProviderKind.SELF_HOSTED,
            api_style=ModelApiStyle.OPENAI_V1,
            capacity_unit=ModelCapacityUnit.GPU,
            capacity_value=2,
            source=ModelDiscoverySource.SIGNED_REGISTRATION,
        )

    source = Ed25519SignedRegistrationSource(
        registrations=(
            SignedModelEndpointRegistration(
                source="example-publisher",
                document=document,
                signature=signature,
            ),
        ),
        verifier=Ed25519ModelEndpointRegistrationVerifier(
            trusted_publishers={"example-publisher": public_key}
        ),
        parser=parser,
    )

    observations = await source.list_observations()

    assert parsed is True
    assert observations[0].provider_kind is ModelProviderKind.SELF_HOSTED


async def test_signed_registration_rejects_invalid_signature_before_parser() -> None:
    parsed = False

    def parser(_raw: bytes) -> ModelEndpointObservation:  # pragma: no cover - must not run
        nonlocal parsed
        parsed = True
        return _observation()

    source = Ed25519SignedRegistrationSource(
        registrations=(
            SignedModelEndpointRegistration(
                source="example-publisher",
                document=b"registration",
                signature=b"0" * 64,
            ),
        ),
        verifier=Ed25519ModelEndpointRegistrationVerifier(trusted_publishers={}),
        parser=parser,
    )

    with pytest.raises(ModelEndpointDiscoveryError, match="untrusted"):
        await source.list_observations()

    assert parsed is False
