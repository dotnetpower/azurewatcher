"""Vendor-neutral rich channel response contract tests."""

from __future__ import annotations

import pytest

from fdai.shared.providers.conversation_channel import (
    MAX_MENTION_COUNT,
    MAX_STREAM_CHUNKS,
    ChannelDeliveryOperation,
    ChannelMention,
    ConversationChannelKind,
    OutboundResponse,
)


def _response(**changes: object) -> OutboundResponse:
    values: dict[str, object] = {
        "channel_kind": ConversationChannelKind.SLACK,
        "channel_id": "channel-1",
        "in_reply_to": "message-1",
        "thread_id": "thread-1",
        "status": "ok",
        "text": "fallback reply",
    }
    values.update(changes)
    return OutboundResponse(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "operation"),
    (
        ({}, ChannelDeliveryOperation.POST),
        ({"stream_chunks": ("one", " two")}, ChannelDeliveryOperation.STREAM),
        ({"edit_message_id": "message-2"}, ChannelDeliveryOperation.EDIT),
        ({"reaction": "thumbsup"}, ChannelDeliveryOperation.REACTION),
    ),
)
def test_outbound_response_selects_one_delivery_operation(
    changes: dict[str, object],
    operation: ChannelDeliveryOperation,
) -> None:
    assert _response(**changes).operation is operation


def test_mentions_keep_opaque_target_separate_from_fallback_text() -> None:
    response = _response(
        mentions=(ChannelMention(target_id="vendor-user-1", display_text="Operator"),)
    )

    assert response.mentions[0].target_id == "vendor-user-1"
    assert response.mentions[0].display_text == "Operator"


@pytest.mark.parametrize(
    "changes",
    (
        {"stream_chunks": ("chunk",), "edit_message_id": "message-2"},
        {"stream_chunks": ("chunk",), "reaction": "thumbsup"},
        {"edit_message_id": "message-2", "reaction": "thumbsup"},
        {
            "reaction": "thumbsup",
            "mentions": (ChannelMention(target_id="user-1", display_text="User"),),
        },
        {"stream_chunks": ("chunk",) * (MAX_STREAM_CHUNKS + 1)},
        {
            "mentions": tuple(
                ChannelMention(target_id=f"user-{index}", display_text=f"User {index}")
                for index in range(MAX_MENTION_COUNT + 1)
            )
        },
    ),
)
def test_outbound_response_rejects_ambiguous_or_unbounded_rich_intent(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _response(**changes)
