"""Signed Slack and authenticated Teams channel adapter tests."""

from __future__ import annotations

import hashlib
import hmac
import json

from fdai.delivery.channels import SlackBotChannel, TeamsBotChannel
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryOperation,
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    OutboundResponse,
)


class _Publisher:
    def __init__(self) -> None:
        self.responses: list[OutboundResponse] = []

    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        self.responses.append(response)
        return ChannelDeliveryReceipt(
            channel_kind=response.channel_kind,
            channel_id=response.channel_id,
            operation=response.operation,
            message_id="ack-1",
        )


def _slack_headers(secret: str, timestamp: int, body: bytes) -> dict[str, str]:
    base = b"v0:" + str(timestamp).encode() + b":" + body
    digest = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": str(timestamp),
        "X-Slack-Signature": f"v0={digest}",
    }


async def test_slack_verifies_and_normalizes_message_event() -> None:
    secret = "test-signing-secret"
    timestamp = 1_700_000_000
    body = json.dumps(
        {
            "type": "event_callback",
            "event_id": "event-1",
            "event": {
                "type": "message",
                "channel": "channel-1",
                "user": "user-1",
                "text": "query_inventory compute.vm",
                "ts": "1.2",
                "thread_ts": "1.1",
                "files": [
                    {
                        "id": "file-1",
                        "name": "evidence.png",
                        "size": 120,
                        "mimetype": "image/png",
                        "url_private": "https://untrusted.example.com/file-1",
                    }
                ],
            },
        }
    ).encode()
    channel = SlackBotChannel(
        signing_secret=secret,
        publisher=_Publisher(),
        clock=lambda: float(timestamp),
    )

    result = await channel.accept(
        headers=_slack_headers(secret, timestamp, body),
        body=body,
    )
    channel.close()
    turns = [turn async for turn in channel.receive()]

    assert result.accepted is True
    assert len(turns) == 1
    assert turns[0].message_id == "event-1"
    assert turns[0].thread_id == "1.1"
    assert turns[0].attachments[0].source_ref == "file-1"
    assert "untrusted.example.com" not in repr(turns[0])


async def test_slack_rejects_stale_or_invalid_signature() -> None:
    secret = "test-signing-secret"
    body = b"{}"
    channel = SlackBotChannel(
        signing_secret=secret,
        publisher=_Publisher(),
        clock=lambda: 2_000.0,
    )

    stale = await channel.accept(headers=_slack_headers(secret, 1_000, body), body=body)
    invalid = await channel.accept(
        headers={"X-Slack-Request-Timestamp": "2000", "X-Slack-Signature": "v0=bad"},
        body=body,
    )

    assert stale.reason == "invalid signature"
    assert invalid.reason == "invalid signature"


async def test_slack_ignores_bot_messages() -> None:
    secret = "test-signing-secret"
    timestamp = 1_700_000_000
    body = json.dumps(
        {
            "type": "event_callback",
            "event_id": "event-1",
            "event": {
                "type": "message",
                "channel": "channel-1",
                "user": "user-1",
                "text": "loop",
                "ts": "1.2",
                "bot_id": "bot-1",
            },
        }
    ).encode()
    channel = SlackBotChannel(
        signing_secret=secret,
        publisher=_Publisher(),
        clock=lambda: float(timestamp),
    )

    result = await channel.accept(
        headers=_slack_headers(secret, timestamp, body),
        body=body,
    )

    assert result.reason == "ignored event"


async def test_teams_normalizes_authenticated_activity_without_service_url() -> None:
    publisher = _Publisher()
    channel = TeamsBotChannel(publisher=publisher)

    result = await channel.accept_authenticated_activity(
        activity={
            "type": "message",
            "id": "activity-1",
            "text": "query_audit decision=hil",
            "serviceUrl": "https://untrusted.example.com",
            "from": {"aadObjectId": "sender-1"},
            "conversation": {"id": "conversation-1"},
            "attachments": [
                {
                    "id": "attachment-1",
                    "name": "evidence.pdf",
                    "size": 240,
                    "contentType": "application/pdf",
                    "contentUrl": "https://untrusted.example.com/attachment-1",
                }
            ],
        }
    )
    channel.close()
    turns = [turn async for turn in channel.receive()]

    assert result.accepted is True
    assert turns[0].sender_id == "sender-1"
    assert "serviceUrl" not in turns[0].metadata
    assert turns[0].attachments[0].source_ref == "attachment-1"
    assert "untrusted.example.com" not in repr(turns[0])


async def test_teams_queue_capacity_fails_closed() -> None:
    channel = TeamsBotChannel(publisher=_Publisher(), queue_capacity=1)
    activity = {
        "type": "message",
        "id": "activity-1",
        "text": "query_audit",
        "from": {"id": "sender-1"},
        "conversation": {"id": "conversation-1"},
    }

    first = await channel.accept_authenticated_activity(activity=activity)
    second = await channel.accept_authenticated_activity(activity=activity)

    assert first.accepted is True
    assert second.reason == "channel queue full"
    channel.close()
    turns = [turn async for turn in channel.receive()]
    assert len(turns) == 1


async def test_channel_adapters_forward_delivery_acknowledgements() -> None:
    slack = SlackBotChannel(signing_secret="signing", publisher=_Publisher())
    teams = TeamsBotChannel(publisher=_Publisher())

    slack_receipt = await slack.send(
        OutboundResponse(
            channel_kind=ConversationChannelKind.SLACK,
            channel_id="channel-1",
            in_reply_to="message-1",
            thread_id="thread-1",
            status="ok",
            text="reply",
        )
    )
    teams_receipt = await teams.send(
        OutboundResponse(
            channel_kind=ConversationChannelKind.TEAMS,
            channel_id="channel-1",
            in_reply_to="message-1",
            thread_id="thread-1",
            status="ok",
            text="reply",
        )
    )

    assert slack_receipt.operation is ChannelDeliveryOperation.POST
    assert teams_receipt.message_id == "ack-1"
