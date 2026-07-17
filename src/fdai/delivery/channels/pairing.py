"""Channel-native delivery for sender pairing challenges."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.conversation.channel_access import ChannelAccessError, ChannelAccessService
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)


class PairingResponseSender(Protocol):
    channel_kind: ConversationChannelKind

    async def send(self, response: OutboundResponse) -> None: ...


class PairingChallengeDeliveryError(RuntimeError):
    """Native challenge delivery failed and no code is exposed in the error."""


@dataclass(frozen=True, slots=True)
class PairingDeliveryReceipt:
    channel_kind: ConversationChannelKind
    expires_at: datetime


class NativePairingChallengeFlow:
    """Create and deliver a pairing code through the originating channel."""

    def __init__(
        self,
        *,
        access: ChannelAccessService,
        senders: Mapping[ConversationChannelKind, PairingResponseSender],
    ) -> None:
        for channel_kind, sender in senders.items():
            if sender.channel_kind is not channel_kind:
                raise ValueError("pairing response sender channel kind mismatch")
        self._access = access
        self._senders = dict(senders)

    async def request(self, turn: InboundTurn, *, at: datetime) -> PairingDeliveryReceipt:
        sender = self._senders.get(turn.channel_kind)
        if sender is None:
            raise ChannelAccessError("channel has no native pairing challenge delivery")
        challenge = await self._access.request_pairing(turn, at=at)
        response = OutboundResponse(
            channel_kind=turn.channel_kind,
            channel_id=turn.channel_id,
            in_reply_to=turn.message_id,
            thread_id=turn.thread_id,
            status="pairing_required",
            text=(
                f"Pairing code: {challenge.code}\nExpires at: {challenge.expires_at.isoformat()}"
            ),
            data={"expires_at": challenge.expires_at.isoformat()},
        )
        try:
            await sender.send(response)
        except Exception as exc:
            cancelled = await self._access.cancel_pairing(turn, code=challenge.code)
            if not cancelled:
                raise PairingChallengeDeliveryError(
                    "channel pairing challenge delivery and cancellation failed"
                ) from exc
            raise PairingChallengeDeliveryError(
                "channel pairing challenge delivery failed"
            ) from exc
        return PairingDeliveryReceipt(
            channel_kind=turn.channel_kind,
            expires_at=challenge.expires_at,
        )


__all__ = [
    "NativePairingChallengeFlow",
    "PairingChallengeDeliveryError",
    "PairingDeliveryReceipt",
    "PairingResponseSender",
]
