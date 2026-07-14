"""httpx-mocked tests for the shared ARM preflight client (issue #13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.preflight import ArmClientConfig, AzureArmClient, AzurePreflightError
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",  # noqa: S106 - fake token, not a secret
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _client(handler, config: ArmClientConfig | None = None) -> AzureArmClient:
    return AzureArmClient(
        identity=_StaticIdentity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        config=config,
    )


async def test_get_json_sends_bearer_and_api_version() -> None:
    captured: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        captured["query"] = request.url.query.decode()
        return httpx.Response(200, json={"ok": True})

    payload = await _client(handle).get_json("/subscriptions/s/x", api_version="2023-07-01")
    assert payload == {"ok": True}
    assert captured["auth"] == "Bearer test-token"
    assert "api-version=2023-07-01" in captured["query"]


async def test_get_values_follows_next_link() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if "page2" in request.url.query.decode() or "page2" in request.url.path:
            return httpx.Response(200, json={"value": [{"n": 2}]})
        next_link = f"https://management.azure.com{request.url.path}?page2=1"
        return httpx.Response(200, json={"value": [{"n": 1}], "nextLink": next_link})

    values = await _client(handle).get_values("/subscriptions/s/list", api_version="2022-01-01")
    assert values == [{"n": 1}, {"n": 2}]


async def test_get_values_honours_max_pages() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        # Always advertise another page -> the guard must trip.
        return httpx.Response(
            200,
            json={
                "value": [{"n": 1}],
                "nextLink": f"https://management.azure.com{request.url.path}?p=x",
            },
        )

    with pytest.raises(AzurePreflightError, match="max_pages"):
        await _client(handle, ArmClientConfig(max_pages=3)).get_values(
            "/subscriptions/s/list", api_version="2022-01-01"
        )


async def test_non_2xx_raises() -> None:
    client = _client(lambda _r: httpx.Response(403, text="denied"))
    with pytest.raises(AzurePreflightError, match="HTTP 403"):
        await client.get_json("/x", api_version="2022-01-01")


async def test_non_json_raises() -> None:
    client = _client(lambda _r: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(AzurePreflightError, match="non-JSON"):
        await client.get_json("/x", api_version="2022-01-01")


async def test_missing_value_array_raises() -> None:
    client = _client(lambda _r: httpx.Response(200, json={"notvalue": []}))
    with pytest.raises(AzurePreflightError, match="'value'"):
        await client.get_values("/x", api_version="2022-01-01")


def test_config_rejects_bad_endpoint_and_audience() -> None:
    with pytest.raises(ValueError):
        ArmClientConfig(arm_endpoint="http://insecure")
    with pytest.raises(ValueError):
        ArmClientConfig(audience="not-https")
    with pytest.raises(ValueError):
        ArmClientConfig(timeout_seconds=0)
    with pytest.raises(ValueError):
        ArmClientConfig(max_pages=0)
