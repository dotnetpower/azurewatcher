"""httpx-mocked tests for the MCP tool executor."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from fdai.delivery.mcp.executor import (
    InMemoryMcpLedger,
    McpToolExecutor,
    McpToolExecutorConfig,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallRequest,
    ToolError,
    ToolPromotionError,
)

_ACTION_TYPE = "tool.jira-open-ticket"
_MCP_TOOL = "jira_create_issue"


def _config(**overrides: object) -> McpToolExecutorConfig:
    base = dict(server_url="https://mcp.local/rpc", tool_map={_ACTION_TYPE: _MCP_TOOL})
    base.update(overrides)
    return McpToolExecutorConfig(**base)  # type: ignore[arg-type]


def _request(
    *,
    mode: Mode = Mode.SHADOW,
    labels: tuple[str, ...] = ("shadow",),
    key: str = "k1",
) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=uuid4(),
        idempotency_key=key,
        action_type_name=_ACTION_TYPE,
        rule_ids=("rule-1",),
        tool_ref="ticket-queue",
        arguments={"summary": "disk full"},
        labels=labels,
        mode=mode,
    )


def _executor(handler, cfg: McpToolExecutorConfig | None = None, ledger=None) -> tuple[
    McpToolExecutor, httpx.AsyncClient
]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ex = McpToolExecutor(config=cfg or _config(), http_client=client, ledger=ledger)
    return ex, client


@pytest.mark.asyncio
async def test_shadow_is_a_real_no_op() -> None:
    called = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        called["n"] += 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    ledger = InMemoryMcpLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(_request(mode=Mode.SHADOW))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("shadow:")
    assert called["n"] == 0  # no network call in shadow
    assert await ledger.seen("k1") is None  # shadow never records the ledger


@pytest.mark.asyncio
async def test_enforce_without_label_raises_promotion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolPromotionError):
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow",)))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_enforce_invokes_mcp_and_records_ledger() -> None:
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"content": []}})

    ledger = InMemoryMcpLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert captured[0]["method"] == "tools/call"
    assert captured[0]["params"]["name"] == _MCP_TOOL
    assert captured[0]["params"]["arguments"] == {"summary": "disk full"}
    assert await ledger.seen("k1") == receipt.receipt_ref


@pytest.mark.asyncio
async def test_idempotency_short_circuits_second_enforce() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    ledger = InMemoryMcpLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        first = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
        second = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert first.outcome is ToolCallOutcome.SUCCEEDED
    assert second.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert second.already_existed is True
    assert calls["n"] == 1  # tool invoked only once


@pytest.mark.asyncio
async def test_jsonrpc_error_maps_to_failed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}},
        )

    ex, client = _executor(handler)
    try:
        receipt = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert "boom" in (receipt.detail or "")


@pytest.mark.asyncio
async def test_tool_is_error_maps_to_failed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"isError": True}})

    ex, client = _executor(handler)
    try:
        receipt = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.FAILED


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
        assert exc.value.kind == "http"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unmapped_action_type_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    ex, client = _executor(handler, _config(tool_map={}))
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
        assert exc.value.kind == "config"
    finally:
        await client.aclose()


def test_config_requires_identity_when_audience_set() -> None:
    with pytest.raises(ValueError, match="no WorkloadIdentity"):
        McpToolExecutor(
            config=_config(audience="api://mcp"),
            http_client=httpx.AsyncClient(),
        )
