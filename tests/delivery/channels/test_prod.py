"""Production channel runtime composition and lifecycle tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx
import pytest
from starlette.testclient import TestClient

from fdai.delivery.channels.prod import (
    ProductionChannelConfig,
    ProductionChannelRuntime,
    build_channel_app,
)
from fdai.delivery.channels.teams_auth import BotServiceIdentity
from fdai.shared.providers.conversation_channel import ConversationChannelAdapter
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


@dataclass
class _Secrets:
    values: dict[str, str]
    requested: list[str] = field(default_factory=list)

    async def get(self, name: str) -> str:
        self.requested.append(name)
        return self.values[name]


@dataclass
class _Gateway:
    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)

    async def run(self, adapter: ConversationChannelAdapter) -> None:
        self.started.append(adapter.channel_kind.value)
        try:
            async for _turn in adapter.receive():
                pass
        finally:
            self.stopped.append(adapter.channel_kind.value)


def _slack_body() -> bytes:
    return json.dumps(
        {
            "type": "event_callback",
            "event_id": "event-1",
            "event": {
                "type": "message",
                "channel": "channel-1",
                "user": "user-1",
                "text": "query_audit",
                "ts": "1.0",
            },
        }
    ).encode()


def test_slack_runtime_fetches_secrets_starts_route_and_stops() -> None:
    timestamp = str(int(time.time()))
    secrets = _Secrets(values={"slack-signing-secret": "signing", "slack-bot-token": "token"})
    gateway = _Gateway()
    runtime = ProductionChannelRuntime(
        config=ProductionChannelConfig(slack_enabled=True, teams_enabled=False),
        gateway=gateway,
        secrets=secrets,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )
    body = _slack_body()
    signature = (
        "v0="
        + hmac.new(
            b"signing",
            b"v0:" + timestamp.encode() + b":" + body,
            hashlib.sha256,
        ).hexdigest()
    )

    with TestClient(build_channel_app(runtime)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        response = client.post(
            "/channels/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
        )
        assert response.status_code == 202
        assert gateway.started == ["slack"]

    assert secrets.requested == ["slack-signing-secret", "slack-bot-token"]
    assert gateway.stopped == ["slack"]


def test_teams_runtime_wires_auth_principal_and_workload_publisher() -> None:
    gateway = _Gateway()

    async def authenticate(_token: str) -> BotServiceIdentity:
        return BotServiceIdentity(service_url="https://bot.example.com")

    async def resolve(_activity: Mapping[str, object]) -> str | None:
        return "operator-1"

    runtime = ProductionChannelRuntime(
        config=ProductionChannelConfig(slack_enabled=False, teams_enabled=True),
        gateway=gateway,
        secrets=_Secrets(values={}),
        teams_identity=StaticWorkloadIdentity(
            audience="https://api.botframework.com",
            token="workload-token",
        ),
        teams_endpoint_resolver=lambda _: "https://bot.example.com/replies",
        teams_authenticate=authenticate,
        teams_principal_resolver=resolve,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(201))),
    )
    activity = {
        "type": "message",
        "id": "activity-1",
        "channelId": "msteams",
        "serviceUrl": "https://bot.example.com",
        "text": "query_audit",
        "from": {"aadObjectId": "oid-1"},
        "conversation": {"id": "conversation-1", "tenantId": "tenant-1"},
    }

    with TestClient(build_channel_app(runtime)) as client:
        response = client.post(
            "/channels/teams/activities",
            json=activity,
            headers={"Authorization": "Bearer service-token"},
        )
        assert response.status_code == 202
        assert gateway.started == ["teams"]

    assert gateway.stopped == ["teams"]


def test_runtime_fails_startup_when_slack_secret_is_missing() -> None:
    runtime = ProductionChannelRuntime(
        config=ProductionChannelConfig(slack_enabled=True, teams_enabled=False),
        gateway=_Gateway(),
        secrets=_Secrets(values={}),
    )

    with pytest.raises(KeyError):
        with TestClient(build_channel_app(runtime)):
            pass


def test_config_requires_enabled_channel_and_bounded_capacity() -> None:
    with pytest.raises(ValueError):
        ProductionChannelConfig(slack_enabled=False, teams_enabled=False)
    with pytest.raises(ValueError):
        ProductionChannelConfig(
            slack_enabled=True,
            teams_enabled=False,
            queue_capacity=5000,
        )
