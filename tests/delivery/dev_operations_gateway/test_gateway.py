from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx
import pytest
from delivery.dev_operations_gateway.gateway import (
    GatewayConfig,
    GatewayError,
    GatewayPrincipal,
    ManagedIdentityTokenProvider,
    OperationsGateway,
)


class _Ledger:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, Mapping[str, object] | None]] = {}

    async def begin(self, idempotency_key: str, request_digest: str) -> Mapping[str, object] | None:
        existing = self.records.get(idempotency_key)
        if existing is None:
            self.records[idempotency_key] = (request_digest, None)
            return None
        assert existing[0] == request_digest
        assert existing[1] is not None
        return existing[1]

    async def complete(
        self,
        idempotency_key: str,
        request_digest: str,
        response: Mapping[str, object],
    ) -> None:
        self.records[idempotency_key] = (request_digest, response)

    async def abort(self, idempotency_key: str, request_digest: str) -> None:
        assert self.records.get(idempotency_key) == (request_digest, None)
        self.records.pop(idempotency_key)


class _Tokens:
    async def get_token(self, audience: str) -> str:
        assert audience
        return "token"


def _config() -> GatewayConfig:
    return GatewayConfig(
        subscription_id="sub-example",
        resource_groups=frozenset({"rg-example"}),
        contributor_group_id="group-contributor",
        executor_principal_id="principal-executor",
        reader_identity_client_id="client-reader",
        executor_identity_client_id="client-executor",
        idempotency_container_url="https://storage.example.com/operation-idempotency",
        private_probes={},
    )


def _safety() -> Mapping[str, object]:
    return {
        "idempotency_key": "operation:one",
        "audit_ref": "audit:one",
        "dry_run_receipt": "dry-run:one",
        "stop_condition": "provisioning_state_terminal",
        "rollback_ref": "rollback:one",
        "max_resources": 1,
    }


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "FDAI_DEV_GATEWAY_ENABLED": "1",
        "FDAI_ENV": "dev",
        "FDAI_DEV_GATEWAY_SUBSCRIPTION_ID": "sub-example",
        "FDAI_DEV_GATEWAY_RESOURCE_GROUPS": "rg-example",
        "FDAI_DEV_GATEWAY_CONTRIBUTOR_GROUP_ID": "group-contributor",
        "FDAI_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID": "principal-executor",
        "FDAI_DEV_GATEWAY_READER_MI_CLIENT_ID": "client-reader",
        "FDAI_DEV_GATEWAY_EXECUTOR_MI_CLIENT_ID": "client-executor",
        "FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL": (
            "https://storage.example.com/operation-idempotency"
        ),
        "FDAI_DEV_GATEWAY_PRIVATE_PROBES_JSON": "{}",
    }
    values.update(overrides)
    return values


def test_config_rejects_unsafe_idempotency_container_url() -> None:
    with pytest.raises(ValueError, match="one HTTPS container"):
        GatewayConfig.from_env(
            _environment(
                FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL=(
                    "https://storage.example.com/operation-idempotency?sig=secret"
                )
            )
        )


@pytest.mark.parametrize("response", [httpx.Response(200, content=b"not-json")])
async def test_managed_identity_invalid_response_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example.com/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: response)
    ) as client:
        provider = ManagedIdentityTokenProvider(client_id="client-reader", http_client=client)
        with pytest.raises(GatewayError) as error:
            await provider.get_token("https://storage.azure.com/")

    assert error.value.status_code == 503
    assert error.value.code == "identity_unavailable"


async def test_managed_identity_transport_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.example.com/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ManagedIdentityTokenProvider(client_id="client-reader", http_client=client)
        with pytest.raises(GatewayError) as error:
            await provider.get_token("https://storage.azure.com/")

    assert error.value.status_code == 503
    assert error.value.code == "identity_unavailable"


async def test_contributor_can_read_one_allowlisted_nsg() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "name": "nsg-app",
                "tags": {"secret-metadata": "must-not-pass"},
                "properties": {
                    "securityRules": [
                        {
                            "name": "allow-https",
                            "properties": {
                                "access": "Allow",
                                "direction": "Inbound",
                                "protocol": "Tcp",
                                "priority": 200,
                                "sourceAddressPrefix": "Internet",
                                "sourceAddressPrefixes": [],
                                "sourcePortRange": "*",
                                "sourcePortRanges": [],
                                "destinationAddressPrefix": "*",
                                "destinationAddressPrefixes": [],
                                "destinationPortRange": "443",
                                "destinationPortRanges": [],
                                "description": "must-not-pass",
                            },
                        }
                    ]
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        result = await gateway.invoke(
            "azure.network.nsg.read",
            {"resource_group": "rg-example", "nsg_name": "nsg-app"},
            GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
        )

    assert result["status"] == "succeeded"
    assert requests[0].method == "GET"
    assert requests[0].url.path.endswith("/networkSecurityGroups/nsg-app")
    assert "must-not-pass" not in repr(result)
    projected = cast(Mapping[str, object], result["result"])
    rules = cast(list[Mapping[str, object]], projected["rules"])
    assert rules[0]["destination_port_range"] == "443"


async def test_scope_and_unregistered_operations_fail_closed() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        principal = GatewayPrincipal("principal-user", frozenset({"group-contributor"}))
        with pytest.raises(GatewayError, match="outside dev scope") as scope_error:
            await gateway.invoke(
                "azure.network.nsg.read",
                {"resource_group": "rg-other", "nsg_name": "nsg-app"},
                principal,
            )
        assert scope_error.value.status_code == 403
        with pytest.raises(GatewayError, match="not registered") as operation_error:
            await gateway.invoke("azure.raw.request", {}, principal)
        assert operation_error.value.status_code == 404


async def test_contributor_app_role_can_read_without_group_claim() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"properties": {"securityRules": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        result = await gateway.invoke(
            "azure.network.nsg.read",
            {"resource_group": "rg-example", "nsg_name": "nsg-app"},
            GatewayPrincipal(
                "principal-user",
                frozenset(),
                frozenset({"Contributor"}),
            ),
        )
    assert result["status"] == "succeeded"


async def test_user_cannot_mutate_even_with_contributor_group() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
        )
        with pytest.raises(GatewayError, match="Thor executor") as error:
            await gateway.invoke(
                "azure.compute.vm.start",
                {"resource_group": "rg-example", "vm_name": "vm-app", "safety": _safety()},
                GatewayPrincipal("principal-user", frozenset({"group-contributor"})),
            )
        assert error.value.status_code == 403


async def test_executor_requires_complete_safety_envelope() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        return httpx.Response(202, json={"status": "accepted"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        principal = GatewayPrincipal("principal-executor", frozenset())
        with pytest.raises(GatewayError, match="safety envelope"):
            await gateway.invoke(
                "azure.compute.vm.start",
                {"resource_group": "rg-example", "vm_name": "vm-app"},
                principal,
            )
        for field in (
            "idempotency_key",
            "audit_ref",
            "dry_run_receipt",
            "stop_condition",
            "rollback_ref",
        ):
            incomplete_safety = dict(_safety())
            incomplete_safety.pop(field)
            with pytest.raises(GatewayError, match=f"safety.{field}"):
                await gateway.invoke(
                    "azure.compute.vm.start",
                    {
                        "resource_group": "rg-example",
                        "vm_name": "vm-app",
                        "safety": incomplete_safety,
                    },
                    principal,
                )
        result = await gateway.invoke(
            "azure.compute.vm.start",
            {"resource_group": "rg-example", "vm_name": "vm-app", "safety": _safety()},
            principal,
        )

    assert result["status"] == "succeeded"
    assert calls == 1


async def test_executor_mutation_is_idempotent_across_duplicate_delivery() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        return httpx.Response(202, json={"status": "accepted"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OperationsGateway(
            config=_config(),
            reader_token_provider=_Tokens(),
            executor_token_provider=_Tokens(),
            http_client=client,
            idempotency_ledger=_Ledger(),
        )
        principal = GatewayPrincipal("principal-executor", frozenset())
        payload = {
            "resource_group": "rg-example",
            "vm_name": "vm-app",
            "safety": _safety(),
        }

        first = await gateway.invoke("azure.compute.vm.start", payload, principal)
        duplicate = await gateway.invoke("azure.compute.vm.start", payload, principal)

    assert duplicate == first
    assert calls == 1
