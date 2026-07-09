"""SlackHilAdapter - HTTP-level round-trip via httpx.MockTransport.

Mirrors the Teams adapter test: verifies the wire contract, HMAC signing,
fail-closed error handling, secret redaction, and the interactive-payload
parser. No real Slack endpoints are contacted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
import pytest

from fdai.delivery.chatops.slack_adapter import (
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannelError,
    HilDecision,
)

_WEBHOOK_URL = "https://hooks.slack.example/services/T000/B000/xxxxxxxx"
_WEBHOOK_SECRET = "s3cret-shared-hmac-key"  # noqa: S105 - deterministic test literal


def _request(
    *,
    approval_id: str = "appr-1",
    target_resource_ref: str = "resource:example/rg/vm-1",
) -> HilApprovalRequest:
    return HilApprovalRequest(
        approval_id=approval_id,
        correlation_id="corr-1",
        action_id="00000000-0000-0000-0000-000000000042",
        action_type="remediate.tag-missing-owner",
        rule_ids=("example.tag.owner-required",),
        target_resource_ref=target_resource_ref,
        blast_radius_summary="1 resource in rg-example",
        reasons=("action_type_in_shadow_mode",),
        ttl_seconds=1800,
    )


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _adapter(client: httpx.AsyncClient, *, webhook_secret: str | None = None) -> SlackHilAdapter:
    return SlackHilAdapter(
        config=SlackHilAdapterConfig(webhook_url=_WEBHOOK_URL, webhook_secret=webhook_secret),
        http_client=client,
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_empty_webhook_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="webhook_url MUST NOT be empty"):
        SlackHilAdapter(
            config=SlackHilAdapterConfig(webhook_url=""),
            http_client=httpx.AsyncClient(),
        )


def test_non_https_webhook_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="https://"):
        SlackHilAdapter(
            config=SlackHilAdapterConfig(webhook_url="http://hooks.slack.example/x"),
            http_client=httpx.AsyncClient(),
        )


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


async def test_send_posts_block_kit_and_returns_receipt() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = json.loads(req.content.decode("utf-8"))
        captured["headers"] = dict(req.headers)
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    async with client:
        receipt = await _adapter(client).send(_request())

    assert captured["url"] == _WEBHOOK_URL
    assert receipt.approval_id == "appr-1"
    assert receipt.channel_ref == "slack:appr-1"
    # The interactive buttons carry "<action>:<approval_id>".
    body = json.dumps(captured["body"])
    assert "approve:appr-1" in body
    assert "reject:appr-1" in body
    # No HMAC header when no secret is configured.
    assert "x-fdai-signature" not in {k.lower() for k in captured["headers"]}


async def test_send_attaches_hmac_when_secret_configured() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
        captured["content"] = req.content
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    async with client:
        await _adapter(client, webhook_secret=_WEBHOOK_SECRET).send(_request())

    assert "x-fdai-signature" in captured["headers"]
    ts = captured["headers"]["x-fdai-timestamp"]
    mac = hmac.new(_WEBHOOK_SECRET.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(ts.encode("utf-8"))
    mac.update(b".")
    mac.update(captured["content"])
    assert captured["headers"]["x-fdai-signature"] == f"sha256={mac.hexdigest()}"


async def test_send_non_2xx_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error " * 100)

    client = _client(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(HilChannelError, match="HTTP 500"):
            await _adapter(client).send(_request())


async def test_send_200_but_not_ok_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="invalid_payload")

    client = _client(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(HilChannelError, match="non-ok body"):
            await _adapter(client).send(_request())


async def test_send_refuses_secret_in_body() -> None:
    # A secret smuggled into a field trips the defense-in-depth scan.
    leaky = _request(target_resource_ref="AKIAABCDEFGHIJKLMNOP")

    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        return httpx.Response(200, text="ok")

    client = _client(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(HilChannelError, match="secret pattern"):
            await _adapter(client).send(leaky)


async def test_transport_error_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = _client(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(HilChannelError, match="send request failed"):
            await _adapter(client).send(_request())


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------


async def test_poll_is_pending_in_p1() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
    )
    async with client:
        receipt = HilApprovalReceipt(
            approval_id="appr-1",
            channel_ref="slack:appr-1",
            sent_at=None,  # type: ignore[arg-type]
        )
        resp = await _adapter(client).poll(receipt)
    assert resp.decision is HilDecision.PENDING


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------


def test_parse_response_approve() -> None:
    payload = {
        "actions": [{"value": "approve:appr-9"}],
        "user": {"id": "U123"},
    }
    resp = SlackHilAdapter.parse_response(payload)
    assert resp.decision is HilDecision.APPROVE
    assert resp.approval_id == "appr-9"
    assert resp.approver_id == "U123"


def test_parse_response_reject() -> None:
    payload = {"actions": [{"value": "reject:appr-9"}], "user": {"id": "U1"}}
    resp = SlackHilAdapter.parse_response(payload)
    assert resp.decision is HilDecision.REJECT


def test_parse_response_unknown_action_is_pending() -> None:
    payload = {"actions": [{"value": "snooze:appr-9"}]}
    resp = SlackHilAdapter.parse_response(payload)
    assert resp.decision is HilDecision.PENDING
    assert resp.approval_id == "appr-9"


def test_parse_response_missing_approval_id_raises() -> None:
    with pytest.raises(HilChannelError, match="missing 'approval_id'"):
        SlackHilAdapter.parse_response({"actions": [{"value": "approve:"}]})


def test_parse_response_non_dict_raises() -> None:
    with pytest.raises(HilChannelError, match="not a JSON object"):
        SlackHilAdapter.parse_response(["not", "a", "dict"])


def test_parse_response_redacts_secret_reason() -> None:
    payload = {
        "actions": [{"value": "approve:appr-9"}],
        "user": {"id": "U1"},
        "reason": "here is AKIAABCDEFGHIJKLMNOP",
    }
    resp = SlackHilAdapter.parse_response(payload)
    assert resp.reason == "[redacted]"
