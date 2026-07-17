"""Slack signed HTTP ingress for bidirectional operator conversations."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fdai.shared.providers.conversation_channel import (
    MAX_ATTACHMENT_COUNT,
    ChannelAttachment,
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)

_MAX_BODY_BYTES: Final = 256 * 1024
_MAX_CLOCK_SKEW_SECONDS: Final = 300


class SlackReplyPublisher(Protocol):
    """Publish a response through a configured Slack app credential."""

    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt: ...


@dataclass(frozen=True, slots=True)
class SlackIngressResult:
    accepted: bool
    reason: str
    challenge: str | None = None


class SlackBotChannel:
    """Verify Slack requests, normalize message events, and publish replies."""

    channel_kind = ConversationChannelKind.SLACK

    def __init__(
        self,
        *,
        signing_secret: str,
        publisher: SlackReplyPublisher,
        clock: Callable[[], float] = time.time,
        max_body_bytes: int = _MAX_BODY_BYTES,
        queue_capacity: int = 256,
    ) -> None:
        if not signing_secret:
            raise ValueError("SlackBotChannel.signing_secret MUST be non-empty")
        if max_body_bytes <= 0 or queue_capacity <= 0:
            raise ValueError("SlackBotChannel limits MUST be positive")
        self._secret: Final = signing_secret
        self._publisher = publisher
        self._clock = clock
        self._max_body_bytes = max_body_bytes
        self._queue: asyncio.Queue[InboundTurn | None] = asyncio.Queue(queue_capacity)
        self._closed = False

    @property
    def max_body_bytes(self) -> int:
        return self._max_body_bytes

    async def accept(self, *, headers: Mapping[str, str], body: bytes) -> SlackIngressResult:
        """Authenticate and enqueue one Slack Events API request."""
        if self._closed:
            return SlackIngressResult(False, "channel closed")
        if len(body) > self._max_body_bytes:
            return SlackIngressResult(False, "body too large")
        lowered = {key.lower(): value for key, value in headers.items()}
        timestamp = lowered.get("x-slack-request-timestamp")
        signature = lowered.get("x-slack-signature")
        if not _verify_signature(
            secret=self._secret,
            timestamp=timestamp,
            body=body,
            signature=signature,
            now=self._clock(),
        ):
            return SlackIngressResult(False, "invalid signature")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return SlackIngressResult(False, "unparseable JSON body")
        if not isinstance(payload, Mapping):
            return SlackIngressResult(False, "body is not a JSON object")
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge")
            if isinstance(challenge, str) and challenge:
                return SlackIngressResult(True, "challenge", challenge)
            return SlackIngressResult(False, "missing challenge")
        turn = _normalize_event(payload)
        if turn is None:
            return SlackIngressResult(False, "ignored event")
        try:
            self._queue.put_nowait(turn)
        except asyncio.QueueFull:
            return SlackIngressResult(False, "channel queue full")
        return SlackIngressResult(True, "accepted")

    async def send(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.channel_kind is not self.channel_kind:
            raise ValueError("Slack response channel kind mismatch")
        return await self._publisher.publish(response)

    async def receive(self) -> AsyncIterator[InboundTurn]:
        while True:
            if self._closed and self._queue.empty():
                return
            turn = await self._queue.get()
            if turn is None:
                return
            yield turn

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._queue.full():
            self._queue.put_nowait(None)


def _verify_signature(
    *,
    secret: str,
    timestamp: str | None,
    body: bytes,
    signature: str | None,
    now: float,
) -> bool:
    if timestamp is None or signature is None:
        return False
    try:
        request_time = int(timestamp)
    except ValueError:
        return False
    if abs(now - request_time) > _MAX_CLOCK_SKEW_SECONDS:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _normalize_event(payload: Mapping[str, Any]) -> InboundTurn | None:
    if payload.get("type") != "event_callback":
        return None
    event = payload.get("event")
    if not isinstance(event, Mapping) or event.get("type") != "message":
        return None
    if event.get("bot_id") is not None or event.get("subtype") is not None:
        return None
    channel = event.get("channel")
    sender = event.get("user")
    text = event.get("text")
    message_id = payload.get("event_id") or event.get("client_msg_id") or event.get("ts")
    if not isinstance(channel, str) or not channel:
        return None
    if not isinstance(sender, str) or not sender:
        return None
    if not isinstance(text, str) or not text:
        return None
    if not isinstance(message_id, str) or not message_id:
        return None
    attachments = _normalize_files(event.get("files"))
    if attachments is None:
        return None
    thread = event.get("thread_ts")
    return InboundTurn(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id=channel,
        message_id=message_id,
        sender_id=sender,
        text=text,
        thread_id=thread if isinstance(thread, str) and thread else None,
        attachments=attachments,
    )


def _normalize_files(raw: Any) -> tuple[ChannelAttachment, ...] | None:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENT_COUNT:
        return None
    attachments: list[ChannelAttachment] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return None
        source_ref = item.get("id")
        name = item.get("name")
        size = item.get("size")
        media_type = item.get("mimetype")
        if (
            not isinstance(source_ref, str)
            or not isinstance(name, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(media_type, str)
        ):
            return None
        try:
            attachments.append(
                ChannelAttachment(
                    source_ref=source_ref,
                    name=name,
                    size_bytes=size,
                    media_type_hint=media_type,
                )
            )
        except ValueError:
            return None
    return tuple(attachments)


__all__ = ["SlackBotChannel", "SlackIngressResult", "SlackReplyPublisher"]
