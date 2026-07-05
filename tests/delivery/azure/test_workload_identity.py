"""ManagedIdentityWorkloadIdentity — httpx-mocked tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aiopspilot.delivery.azure.workload_identity import (
    ManagedIdentityConfigurationError,
    ManagedIdentityWorkloadIdentity,
    ManagedIdentityWorkloadIdentityConfig,
)


def _cfg(**overrides: object) -> ManagedIdentityWorkloadIdentityConfig:
    base: dict[str, object] = {
        "endpoint": "https://containerapps-identity.local/token",
        "header": "expected-header-value",
    }
    base.update(overrides)
    return ManagedIdentityWorkloadIdentityConfig(**base)  # type: ignore[arg-type]


def _future_epoch(seconds_ahead: int) -> int:
    return int((datetime.now(tz=UTC) + timedelta(seconds=seconds_ahead)).timestamp())


@pytest.mark.asyncio
async def test_get_token_hits_endpoint_with_resource_query() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "mi-token-abc",
                "expires_on": _future_epoch(3600),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        identity = ManagedIdentityWorkloadIdentity(http_client=http, config=_cfg())
        token = await identity.get_token("https://cognitiveservices.azure.com/.default")
    assert token.token == "mi-token-abc"
    req = captured[0]
    assert req.url.params.get("api-version") == "2019-08-01"
    # `/.default` scope is normalized to `resource=` param (MI legacy shape).
    assert req.url.params.get("resource") == "https://cognitiveservices.azure.com"
    assert req.headers["X-IDENTITY-HEADER"] == "expected-header-value"


@pytest.mark.asyncio
async def test_get_token_caches_per_audience() -> None:
    hit_count = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal hit_count
        hit_count += 1
        return httpx.Response(
            200,
            json={"access_token": "abc", "expires_on": _future_epoch(3600)},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        identity = ManagedIdentityWorkloadIdentity(http_client=http, config=_cfg())
        first = await identity.get_token("aud-a")
        second = await identity.get_token("aud-a")
    assert first.token == second.token
    assert hit_count == 1


@pytest.mark.asyncio
async def test_get_token_refreshes_when_expiring_soon() -> None:
    call = 0

    async def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal call
        call += 1
        # First response expires in 10s (below the 60s minimum TTL → force
        # a refresh on the next call); second response has a full hour.
        ttl = 10 if call == 1 else 3600
        return httpx.Response(
            200,
            json={"access_token": f"tok-{call}", "expires_on": _future_epoch(ttl)},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        identity = ManagedIdentityWorkloadIdentity(http_client=http, config=_cfg())
        first = await identity.get_token("aud-a")
        second = await identity.get_token("aud-a")
    assert call == 2
    assert first.token != second.token


@pytest.mark.asyncio
async def test_get_token_includes_client_id_when_configured() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"access_token": "x", "expires_on": _future_epoch(3600)},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        identity = ManagedIdentityWorkloadIdentity(
            http_client=http,
            config=_cfg(client_id="00000000-0000-0000-0000-000000000042"),
        )
        await identity.get_token("aud")
    assert captured[0].url.params.get("client_id") == "00000000-0000-0000-0000-000000000042"


@pytest.mark.asyncio
async def test_malformed_body_raises_runtime_error() -> None:
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": "no access_token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        identity = ManagedIdentityWorkloadIdentity(http_client=http, config=_cfg())
        with pytest.raises(RuntimeError, match="unrecognized body"):
            await identity.get_token("aud")


def test_config_rejects_non_url_endpoint() -> None:
    with pytest.raises(ManagedIdentityConfigurationError, match="absolute URL"):
        ManagedIdentityWorkloadIdentity(
            http_client=httpx.AsyncClient(),
            config=_cfg(endpoint="/not-a-url"),
        )


def test_config_rejects_empty_header() -> None:
    with pytest.raises(ManagedIdentityConfigurationError, match="IDENTITY_HEADER"):
        ManagedIdentityWorkloadIdentity(
            http_client=httpx.AsyncClient(),
            config=_cfg(header=""),
        )
