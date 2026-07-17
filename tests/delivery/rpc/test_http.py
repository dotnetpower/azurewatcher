"""Typed RPC HTTP route and client boundary tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.rpc import RpcMethod, RpcRegistry, RpcRequest, RpcScope
from fdai.delivery.rpc import RpcHttpClient, RpcHttpClientError, make_rpc_route


async def _handler(params: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"echo": params.get("value")}


async def _authorize(_: object) -> frozenset[RpcScope]:
    return frozenset({RpcScope.READ})


class _Auth:
    async def headers(self) -> Mapping[str, str]:
        return {"Authorization": "Bearer test-token"}


def _registry() -> RpcRegistry:
    return RpcRegistry().register(
        RpcMethod(
            name="inventory.query",
            description="Query inventory.",
            required_scope=RpcScope.READ,
            handler=_handler,
        )
    )


def test_route_rejects_invalid_or_oversized_body() -> None:
    route = make_rpc_route(
        registry=_registry(),
        authorize=_authorize,
        max_body_bytes=20,
    )
    app = Starlette(routes=[route])
    client = TestClient(app)

    assert client.post("/rpc", content=b"not-json").status_code == 400
    assert client.post("/rpc", content=b"x" * 21).status_code == 413


def test_route_invokes_registry_with_authorized_scope() -> None:
    app = Starlette(routes=[make_rpc_route(registry=_registry(), authorize=_authorize)])
    client = TestClient(app)

    response = client.post(
        "/rpc",
        json={
            "schema_version": "1.0.0",
            "request_id": "r1",
            "method": "inventory.query",
            "params": {"value": 7},
            "idempotency_key": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["result"] == {"echo": 7}


async def test_client_sends_auth_and_validates_correlation() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "schema_version": "1.0.0",
                "request_id": body["request_id"],
                "ok": True,
                "result": {"echo": body["params"]["value"]},
                "error": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await RpcHttpClient(
            endpoint="https://api.example.com/rpc",
            http_client=http_client,
            auth=_Auth(),
        ).invoke(
            RpcRequest(
                request_id="r1",
                method="inventory.query",
                params={"value": 9},
            )
        )

    assert captured["authorization"] == "Bearer test-token"
    assert response.result == {"echo": 9}


async def test_client_rejects_mismatched_response_id() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "schema_version": "1.0.0",
                "request_id": "wrong",
                "ok": True,
                "result": {},
                "error": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = RpcHttpClient(
            endpoint="https://api.example.com/rpc",
            http_client=http_client,
            auth=_Auth(),
        )
        with pytest.raises(RpcHttpClientError, match="protocol"):
            await client.invoke(RpcRequest(request_id="r1", method="inventory.query"))


@pytest.mark.parametrize(
    "endpoint",
    ("http://api.example.com/rpc", "https://user:pass@api.example.com/rpc"),
)
def test_client_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="RPC endpoint"):
        RpcHttpClient(endpoint=endpoint, http_client=httpx.AsyncClient(), auth=_Auth())
