"""httpx-mocked tests for the Azure OpenAI adapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aiopspilot.core.quality_gate.gate import QualityCandidate
from aiopspilot.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from aiopspilot.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from aiopspilot.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake in-memory token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def _mock_embed_transport(dim: int, *, captured: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1] * dim, "index": 0}]},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_embeddings_success_returns_vector_of_configured_dim() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_embed_transport(dim=1536, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        vector = await adapter.embed("hello world")
    assert len(vector) == 1536
    assert vector[0] == pytest.approx(0.1)
    # URL shape
    req = captured[0]
    assert req.url.path == "/openai/deployments/t1-embedding/embeddings"
    assert req.url.params.get("api-version") == "2024-06-01"
    assert req.headers["Authorization"] == "Bearer test-token"
    assert json.loads(req.content.decode()) == {"input": "hello world"}


@pytest.mark.asyncio
async def test_embeddings_rejects_dim_mismatch() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_embed_transport(dim=8, captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        with pytest.raises(RuntimeError, match="embedding length"):
            await adapter.embed("hi")


@pytest.mark.asyncio
async def test_embeddings_rejects_malformed_body() -> None:
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        with pytest.raises(RuntimeError, match="data\\[0\\].embedding"):
            await adapter.embed("hi")


@pytest.mark.asyncio
async def test_embeddings_propagates_http_error() -> None:
    async def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "quota"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t1-embedding",
                dim=1536,
            ),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.embed("hi")


def test_embeddings_config_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError, match="https"):
        AzureOpenAIEmbeddingModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAIEmbeddingModelConfig(
                endpoint="ftp://oai-test.openai.azure.com",
                deployment="t1-embedding",
            ),
        )


# ---------------------------------------------------------------------------
# Cross-check
# ---------------------------------------------------------------------------


def _mock_cross_check_transport(
    content: str, *, captured: list[httpx.Request]
) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    return httpx.MockTransport(handler)


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("object-storage.owner-tag.required",),
    )


@pytest.mark.asyncio
async def test_cross_check_parses_structured_json_response() -> None:
    captured: list[httpx.Request] = []
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "remediate.tag-add", "params": {"foo": "bar"}}),
        captured=captured,
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
            ),
        )
        action_type, params = await adapter.propose(_candidate())
    assert action_type == "remediate.tag-add"
    assert params == {"foo": "bar"}
    req = captured[0]
    body = json.loads(req.content.decode())
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 512


@pytest.mark.asyncio
async def test_cross_check_rejects_non_json_content() -> None:
    transport = _mock_cross_check_transport("not-json", captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
            ),
        )
        with pytest.raises(RuntimeError, match="non-JSON"):
            await adapter.propose(_candidate())


@pytest.mark.asyncio
async def test_cross_check_rejects_response_without_action_type() -> None:
    transport = _mock_cross_check_transport(json.dumps({"params": {}}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
            ),
        )
        with pytest.raises(RuntimeError, match="action_type"):
            await adapter.propose(_candidate())


@pytest.mark.asyncio
async def test_cross_check_rejects_non_object_params() -> None:
    transport = _mock_cross_check_transport(
        json.dumps({"action_type": "x", "params": "not-an-object"}), captured=[]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=http,
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
            ),
        )
        with pytest.raises(RuntimeError, match="'params'"):
            await adapter.propose(_candidate())


def test_cross_check_config_rejects_bad_temperature() -> None:
    with pytest.raises(ValueError, match="temperature"):
        AzureOpenAICrossCheckModel(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=AzureOpenAICrossCheckModelConfig(
                endpoint="https://oai-test.openai.azure.com",
                deployment="t2-primary",
                temperature=3.0,
            ),
        )
