"""Production typed RPC app composition tests."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation import RuntimeToolDiscovery, ToolSchema
from fdai.core.rpc import (
    InMemoryRpcIdempotencyStore,
    RpcMethod,
    RpcScope,
)
from fdai.delivery.rpc.prod import ProductionRpcConfig, build_production_rpc_app


def _discovery() -> RuntimeToolDiscovery:
    schema = ToolSchema(
        verb="query_inventory",
        tool_name="inventory.query",
        argument_hint="<resource-type>",
        summary="Read inventory.",
        rbac_floor="reader",
        side_effect_class="read",
    )
    return RuntimeToolDiscovery(
        schemas=(schema,),
        installed_tool_names=frozenset({schema.tool_name}),
    )


async def _authorize(_request: Request) -> frozenset[RpcScope]:
    return frozenset({RpcScope.READ, RpcScope.WRITE})


def test_production_app_exposes_health_and_builtin_tool_discovery() -> None:
    app = build_production_rpc_app(
        config=ProductionRpcConfig(dsn="postgresql://example"),
        discovery=_discovery(),
        authorize=_authorize,
        idempotency_store=InMemoryRpcIdempotencyStore(),
    )
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.post(
        "/rpc",
        json={
            "schema_version": "1.0.0",
            "request_id": "request-1",
            "method": "tools.search",
            "params": {"query": "inventory"},
            "idempotency_key": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["tools"][0]["name"] == "inventory.query"


async def _request_workflow(params: Mapping[str, object]) -> Mapping[str, object]:
    return {"status": "submitted", "name": params.get("name", "")}


def test_explicit_side_effect_method_uses_injected_claim_store() -> None:
    app = build_production_rpc_app(
        config=ProductionRpcConfig(dsn="postgresql://example"),
        discovery=_discovery(),
        authorize=_authorize,
        additional_methods=(
            RpcMethod(
                name="workflow.request",
                description="Submit a typed workflow proposal.",
                required_scope=RpcScope.WRITE,
                handler=_request_workflow,
                side_effect=True,
            ),
        ),
        idempotency_store=InMemoryRpcIdempotencyStore(),
    )
    client = TestClient(app)
    payload = {
        "schema_version": "1.0.0",
        "request_id": "request-1",
        "method": "workflow.request",
        "params": {"name": "example"},
        "idempotency_key": "same-key",
    }

    first = client.post("/rpc", json=payload).json()
    payload["request_id"] = "request-2"
    second = client.post("/rpc", json=payload).json()

    assert first["result"] == second["result"]
    assert second["request_id"] == "request-2"
