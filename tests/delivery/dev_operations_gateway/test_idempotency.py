from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from delivery.dev_operations_gateway.idempotency import (
    AzureBlobIdempotencyConfig,
    AzureBlobIdempotencyLedger,
    IdempotencyError,
)


class _Tokens:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> str:
        self.audiences.append(audience)
        return "storage-token"


def _config() -> AzureBlobIdempotencyConfig:
    return AzureBlobIdempotencyConfig(
        container_url="https://storage.example.com/operation-idempotency"
    )


def test_config_rejects_unsafe_container_urls() -> None:
    for url in (
        "http://storage.example.com/operation-idempotency",
        "https://user@storage.example.com/operation-idempotency",
        "https://storage.example.com/",
        "https://storage.example.com/one/two",
        "https://storage.example.com/operation-idempotency?sig=secret",
    ):
        with pytest.raises(ValueError, match="one HTTPS container"):
            AzureBlobIdempotencyConfig(container_url=url)


async def test_claim_and_complete_use_conditional_blob_writes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201, headers={"ETag": '"claim-etag"'})
        return httpx.Response(201, headers={"ETag": '"completed-etag"'})

    tokens = _Tokens()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(),
            token_provider=tokens,
            http_client=client,
        )
        replay = await ledger.begin("operation:secret", "request-digest")
        await ledger.complete(
            "operation:secret",
            "request-digest",
            {"status": "succeeded", "result": {"accepted": True}},
        )

    assert replay is None
    assert len(requests) == 2
    expected_name = hashlib.sha256(b"operation:secret").hexdigest()
    assert requests[0].url.path.endswith(f"/{expected_name}.json")
    assert "operation:secret" not in str(requests[0].url)
    assert requests[0].headers["If-None-Match"] == "*"
    assert requests[1].headers["If-Match"] == '"claim-etag"'
    assert requests[0].headers["Authorization"] == "Bearer storage-token"
    assert tokens.audiences == ["https://storage.azure.com/"] * 2
    completed = json.loads(requests[1].content)
    assert completed["state"] == "completed"
    assert completed["request_digest"] == "request-digest"


async def test_completed_duplicate_replays_recorded_response() -> None:
    expected = {"operation_id": "azure.compute.vm.start", "status": "succeeded"}
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(409)
        return httpx.Response(
            200,
            headers={"ETag": '"completed-etag"'},
            json={
                "state": "completed",
                "request_digest": "request-digest",
                "response": expected,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        replay = await AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        ).begin("operation:one", "request-digest")

    assert replay == expected
    assert calls == 2


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (
            {"state": "pending", "request_digest": "request-digest"},
            "idempotency_in_progress",
        ),
        (
            {"state": "completed", "request_digest": "different", "response": {}},
            "idempotency_conflict",
        ),
    ],
)
async def test_existing_claims_fail_closed(record: dict[str, object], code: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(412)
        return httpx.Response(200, headers={"ETag": '"etag"'}, json=record)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        with pytest.raises(IdempotencyError) as error:
            await ledger.begin("operation:one", "request-digest")

    assert error.value.status_code == 409
    assert error.value.code == code


async def test_abort_releases_the_exact_claim() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(201, headers={"ETag": '"claim-etag"'})
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        await ledger.begin("operation:one", "request-digest")
        await ledger.abort("operation:one", "request-digest")

    assert [request.method for request in requests] == ["PUT", "DELETE"]
    assert requests[1].headers["If-Match"] == '"claim-etag"'


async def test_storage_failure_blocks_the_mutation_path() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        ledger = AzureBlobIdempotencyLedger(
            config=_config(), token_provider=_Tokens(), http_client=client
        )
        with pytest.raises(IdempotencyError) as error:
            await ledger.begin("operation:one", "request-digest")

    assert error.value.status_code == 503
    assert error.value.code == "idempotency_unavailable"
