"""Durable principal-scoped transcript writes for Command Deck chat routes."""

from __future__ import annotations

from datetime import datetime

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)


async def append_operator_turn(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    request_id: str,
    content: str,
    recorded_at: datetime,
    ontology_projector: UserContextOntologyProjector | None = None,
) -> ConversationTurnRecord:
    conversation = await store.get_conversation(
        principal_id=principal_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        conversation = await store.create_conversation(
            ConversationRecord(
                conversation_id=conversation_id,
                principal_id=principal_id,
                channel_id="web",
                started_at=recorded_at,
                last_active=recorded_at,
            )
        )
    idempotency_key = f"{request_id}:operator"
    turn = ConversationTurnRecord(
        turn_id=f"turn:{request_id}:operator",
        conversation_id=conversation_id,
        principal_id=principal_id,
        turn_index=0,
        role=ConversationTurnRole.OPERATOR,
        content=content,
        recorded_at=recorded_at,
        idempotency_key=idempotency_key,
    )
    stored = await store.append_turn(turn, allocate_index=True)
    if ontology_projector is not None:
        await ontology_projector.project_conversation(conversation)
    return stored


async def append_assistant_turn(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    request_id: str,
    content: str,
    recorded_at: datetime,
    metadata: dict[str, str] | None = None,
    ontology_projector: UserContextOntologyProjector | None = None,
) -> ConversationTurnRecord:
    idempotency_key = f"{request_id}:assistant"
    turn = ConversationTurnRecord(
        turn_id=f"turn:{request_id}:assistant",
        conversation_id=conversation_id,
        principal_id=principal_id,
        turn_index=0,
        role=ConversationTurnRole.ASSISTANT,
        content=content,
        recorded_at=recorded_at,
        idempotency_key=idempotency_key,
        metadata=dict(metadata or {}),
    )
    stored = await store.append_turn(turn, allocate_index=True)
    if ontology_projector is not None:
        prior = await store.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=2,
        )
        conversation = await store.get_conversation(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        operator = next(
            (item for item in prior if item.idempotency_key == f"{request_id}:operator"),
            None,
        )
        if conversation is not None and operator is not None:
            await ontology_projector.project_turn_exchange(
                conversation=conversation,
                operator=operator,
                assistant=stored,
            )
    return stored


__all__ = ["append_assistant_turn", "append_operator_turn"]
