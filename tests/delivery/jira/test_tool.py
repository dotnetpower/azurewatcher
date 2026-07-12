"""httpx-mocked tests for the Jira ticketing tool executor."""

from __future__ import annotations

import base64
import json
from uuid import uuid4

import httpx
import pytest

from fdai.delivery.jira.tool import (
    InMemoryJiraLedger,
    JiraToolExecutor,
    JiraToolExecutorConfig,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallRequest,
    ToolError,
    ToolExecutor,
    ToolPromotionError,
)

_ACTION_TYPE = "tool.open-incident-ticket"
_PROJECT = "OPS"


class _StaticSecrets(SecretProvider):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.reads: list[str] = []

    async def get(self, name: str) -> str:
        self.reads.append(name)
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc


def _config(**overrides: object) -> JiraToolExecutorConfig:
    base: dict[str, object] = dict(
        base_url="https://acme.atlassian.net",
        account_email="bot@example.com",
        api_token_secret="jira/token",
        tool_map={_ACTION_TYPE: _PROJECT},
    )
    base.update(overrides)
    return JiraToolExecutorConfig(**base)  # type: ignore[arg-type]


def _request(
    *,
    mode: Mode = Mode.SHADOW,
    labels: tuple[str, ...] = ("shadow",),
    key: str = "k1",
    arguments: dict | None = None,
) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=uuid4(),
        idempotency_key=key,
        action_type_name=_ACTION_TYPE,
        rule_ids=("rule-1",),
        tool_ref="ticket-queue",
        arguments=arguments if arguments is not None else {"summary": "disk full"},
        labels=labels,
        mode=mode,
    )


def _executor(
    handler,
    cfg: JiraToolExecutorConfig | None = None,
    ledger=None,
    secrets: SecretProvider | None = None,
) -> tuple[JiraToolExecutor, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ex = JiraToolExecutor(
        config=cfg or _config(),
        http_client=client,
        secrets=secrets or _StaticSecrets({"jira/token": "TKN"}),
        ledger=ledger,
    )
    return ex, client


def test_jira_executor_satisfies_protocol() -> None:
    ex, _ = _executor(lambda r: httpx.Response(200))
    assert isinstance(ex, ToolExecutor)


@pytest.mark.asyncio
async def test_shadow_is_a_real_no_op() -> None:
    called = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        called["n"] += 1
        return httpx.Response(201, json={"key": "OPS-1"})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(_request(mode=Mode.SHADOW))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("shadow:")
    assert called["n"] == 0
    assert await ledger.seen("k1") is None


@pytest.mark.asyncio
async def test_enforce_without_label_raises_promotion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={"key": "OPS-1"})

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolPromotionError):
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow",)))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_enforce_creates_issue_and_records_ledger() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json={"id": "10001", "key": "OPS-42"})

    ledger = InMemoryJiraLedger()
    secrets = _StaticSecrets({"jira/token": "TKN"})
    ex, client = _executor(handler, ledger=ledger, secrets=secrets)
    try:
        receipt = await ex.execute(
            _request(
                mode=Mode.ENFORCE,
                labels=("shadow", "enforce"),
                arguments={
                    "summary": "disk 95% on web-a",
                    "description": "auto-opened by FDAI",
                    "labels": ["fdai", "with space"],
                },
            )
        )
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert receipt.receipt_ref == "OPS-42"
    assert await ledger.seen("k1") == "OPS-42"

    req = captured[0]
    assert str(req.url).endswith("/rest/api/3/issue")
    expected_basic = base64.b64encode(b"bot@example.com:TKN").decode("ascii")
    assert req.headers["Authorization"] == f"Basic {expected_basic}"
    body = json.loads(req.content)
    assert body["fields"]["project"]["key"] == "OPS"
    assert body["fields"]["summary"] == "disk 95% on web-a"
    assert body["fields"]["issuetype"]["name"] == "Task"
    # labels with spaces are dropped; valid ones kept
    assert body["fields"]["labels"] == ["fdai"]
    # description wrapped in Atlassian Document Format
    assert body["fields"]["description"]["type"] == "doc"
    assert secrets.reads == ["jira/token"]


@pytest.mark.asyncio
async def test_idempotency_short_circuits_no_duplicate() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(201, json={"key": "OPS-7"})

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        first = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
        second = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert first.outcome is ToolCallOutcome.SUCCEEDED
    assert second.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert second.already_existed is True
    assert calls["n"] == 1  # only one real create


@pytest.mark.asyncio
async def test_unmapped_action_type_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={"key": "OPS-1"})

    ex, client = _executor(handler, cfg=_config(tool_map={}))
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.SHADOW))
    finally:
        await client.aclose()
    assert exc.value.kind == "config"


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "http"


@pytest.mark.asyncio
async def test_missing_key_in_response_maps_to_failed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "10001"})  # no key

    ledger = InMemoryJiraLedger()
    ex, client = _executor(handler, ledger=ledger)
    try:
        receipt = await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert await ledger.seen("k1") is None  # failure never records the ledger


@pytest.mark.asyncio
async def test_non_json_response_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="<html>oops</html>")

    ex, client = _executor(handler)
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_response_over_byte_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"key": "OPS-1", "pad": "z" * 500})

    ex, client = _executor(handler, cfg=_config(max_response_bytes=64))
    try:
        with pytest.raises(ToolError) as exc:
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_missing_secret_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={"key": "OPS-1"})

    ex, client = _executor(handler, secrets=_StaticSecrets({}))
    try:
        with pytest.raises(SecretNotFoundError):
            await ex.execute(_request(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    finally:
        await client.aclose()


def test_config_rejects_plaintext_url() -> None:
    with pytest.raises(ValueError, match="https://"):
        _config(base_url="http://acme.atlassian.net")


def test_config_rejects_empty_token_secret() -> None:
    with pytest.raises(ValueError, match="api_token_secret"):
        _config(api_token_secret="")
