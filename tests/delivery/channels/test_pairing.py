"""Channel-native sender pairing challenge delivery tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.conversation import (
    ChannelAccessError,
    ChannelAccessMode,
    ChannelAccessService,
    InMemoryChannelPairingStore,
)
from fdai.core.conversation.session import Principal, Role
from fdai.delivery.channels import (
    NativePairingChallengeFlow,
    PairingChallengeDeliveryError,
)
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)

_NOW = datetime(2026, 7, 17, 5, 0, tzinfo=UTC)


class _Identities:
    async def principal_for_id(self, principal_id: str) -> Principal | None:
        return Principal(id=principal_id, role=Role.READER)


class _Authorizer:
    def can_approve_pairing(self, actor_id: str) -> bool:
        return actor_id == "owner-example"


class _Sender:
    channel_kind = ConversationChannelKind.SLACK

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.responses: list[OutboundResponse] = []

    async def send(self, response: OutboundResponse) -> None:
        if self.fail:
            raise RuntimeError("synthetic delivery failure")
        self.responses.append(response)


def _access() -> ChannelAccessService:
    return ChannelAccessService(
        modes={ConversationChannelKind.SLACK: ChannelAccessMode.PAIRING},
        store=InMemoryChannelPairingStore(),
        identities=_Identities(),
        authorizer=_Authorizer(),
        code_factory=lambda: "ABC123",
        max_pending_per_channel=1,
    )


def _turn(sender_id: str = "sender-example") -> InboundTurn:
    return InboundTurn(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-example",
        message_id="message-example",
        sender_id=sender_id,
        text="pair",
        thread_id="thread-example",
    )


async def test_challenge_is_delivered_to_originating_thread() -> None:
    sender = _Sender()
    flow = NativePairingChallengeFlow(
        access=_access(),
        senders={ConversationChannelKind.SLACK: sender},
    )

    receipt = await flow.request(_turn(), at=_NOW)

    response = sender.responses[0]
    assert response.thread_id == "thread-example"
    assert response.status == "pairing_required"
    assert "ABC123" in response.text
    assert "ABC123" not in str(response.data)
    assert receipt.channel_kind is ConversationChannelKind.SLACK


async def test_failed_delivery_cancels_pending_request_without_leaking_code() -> None:
    access = _access()
    failing = NativePairingChallengeFlow(
        access=access,
        senders={ConversationChannelKind.SLACK: _Sender(fail=True)},
    )
    with pytest.raises(PairingChallengeDeliveryError) as captured:
        await failing.request(_turn(), at=_NOW)
    assert "ABC123" not in str(captured.value)

    working_sender = _Sender()
    working = NativePairingChallengeFlow(
        access=access,
        senders={ConversationChannelKind.SLACK: working_sender},
    )
    await working.request(_turn("sender-two"), at=_NOW)
    assert len(working_sender.responses) == 1


async def test_missing_native_sender_fails_before_pairing_is_created() -> None:
    access = _access()
    flow = NativePairingChallengeFlow(access=access, senders={})
    with pytest.raises(ChannelAccessError, match="no native"):
        await flow.request(_turn(), at=_NOW)

    assert (await access.request_pairing(_turn(), at=_NOW)).code == "ABC123"
