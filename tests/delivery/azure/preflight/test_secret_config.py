"""Value-blind Key Vault secret preflight checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.preflight.secret_config import (
    AzureSecretConfigProbe,
    AzureSecretProbeConfig,
    AzureSecretProbeError,
)
from fdai.shared.providers.feasibility_probe import PreflightTarget, ProbeCategory
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _Identity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - deterministic fake
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _probe(handler: httpx.MockTransport) -> AzureSecretConfigProbe:
    return AzureSecretConfigProbe(
        config=AzureSecretProbeConfig(
            vault_endpoint="https://example.vault.azure.net",
            required_secret_names=("database-dsn",),
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=handler),
    )


async def test_existing_secret_is_clear_without_reading_body() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/secrets/database-dsn"
        return httpx.Response(200, content=b'{"value":"must-not-be-read"}')

    probe = _probe(httpx.MockTransport(handle))

    assert await probe.evaluate(PreflightTarget(scope="example")) == ()


async def test_missing_secret_uses_hashed_reference_only() -> None:
    probe = _probe(httpx.MockTransport(lambda _request: httpx.Response(404)))

    findings = await probe.evaluate(PreflightTarget(scope="example"))

    assert len(findings) == 1
    assert findings[0].category is ProbeCategory.SECRET_CONFIG
    serialized = str(findings[0].to_dict())
    assert "database-dsn" not in serialized
    assert "example.vault.azure.net" not in serialized


async def test_permission_failure_propagates_fail_closed() -> None:
    probe = _probe(httpx.MockTransport(lambda _request: httpx.Response(403)))

    with pytest.raises(AzureSecretProbeError, match="HTTP 403"):
        await probe.evaluate(PreflightTarget(scope="example"))


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://example.vault.azure.net",
        "https://example.com",
        "https://example.vault.azure.net/path",
    ),
)
def test_endpoint_validation_blocks_non_key_vault_origins(endpoint: str) -> None:
    with pytest.raises(ValueError, match="Key Vault HTTPS origin"):
        AzureSecretProbeConfig(
            vault_endpoint=endpoint,
            required_secret_names=("database-dsn",),
        )
