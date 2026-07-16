from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fdai.delivery.persistence.postgres_user_context_projection_queue import (
    enqueue_projection_upsert,
)
from fdai.delivery.persistence.postgres_user_context_projection_recovery import (
    _turn_exchanges,
)
from fdai.shared.providers.user_context import (
    ConversationTurnRecord,
    ConversationTurnRole,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _turn(
    turn_id: str,
    role: ConversationTurnRole,
    idempotency_key: str,
    turn_index: int,
) -> ConversationTurnRecord:
    return ConversationTurnRecord(
        turn_id=turn_id,
        conversation_id="conversation-1",
        principal_id="principal-1",
        turn_index=turn_index,
        role=role,
        content=f"body-{turn_id}",
        recorded_at=NOW,
        idempotency_key=idempotency_key,
    )


async def test_enqueue_projection_upsert_uses_source_reference_only() -> None:
    connection = AsyncMock()

    await enqueue_projection_upsert(
        connection,
        projection_kind="memory",
        principal_id="principal-1",
        record_id="memory-1",
    )

    query, parameters = connection.execute.await_args.args
    assert "user_context_projection_upsert_queue" in query
    assert "body" not in query
    assert parameters == ("memory", "principal-1", "memory-1")


def test_turn_exchanges_pair_only_matching_request_keys() -> None:
    operator = _turn("operator-1", ConversationTurnRole.OPERATOR, "request-1:operator", 0)
    unrelated = _turn("assistant-2", ConversationTurnRole.ASSISTANT, "request-2:assistant", 1)
    assistant = _turn("assistant-1", ConversationTurnRole.ASSISTANT, "request-1:assistant", 2)

    assert _turn_exchanges((operator, unrelated, assistant)) == ((operator, assistant),)
