"""Route authenticated channel turns through the conversation coordinator."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from fdai.core.conversation.coordinator import ConversationCoordinator
from fdai.core.conversation.session import ConversationSession, Principal
from fdai.core.conversation.tools import AbstainResult, ToolResult
from fdai.shared.providers.conversation_channel import (
    ConversationChannelAdapter,
    InboundTurn,
    OutboundResponse,
)
from fdai.shared.telemetry.transitions import (
    RoutingTransition,
    RoutingTransitionSink,
    default_transition_emitter,
    emit_transition_safely,
)


class ChannelPrincipalResolver(Protocol):
    """Resolve one channel sender to an FDAI principal or deny access."""

    async def resolve(self, turn: InboundTurn) -> Principal | None: ...


class ChannelMessageLedger(Protocol):
    """Atomically claim inbound messages so redelivery is a no-op."""

    async def claim(self, idempotency_key: str) -> bool: ...

    async def release(self, idempotency_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AttachmentIngestionResult:
    status: Literal["ready", "rejected"]
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status == "ready" and (
            self.reason
            or not self.evidence_refs
            or any(not reference.startswith("doc:") for reference in self.evidence_refs)
        ):
            raise ValueError("ready attachment ingestion MUST carry only doc citations")
        if self.status == "rejected" and (not self.reason or self.evidence_refs):
            raise ValueError("rejected attachment ingestion MUST carry only a reason")


class ChannelAttachmentIngestor(Protocol):
    async def ingest(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
    ) -> AttachmentIngestionResult: ...


SessionLoader = Callable[[str, Principal, str], Awaitable[ConversationSession]]


class ConversationChannelGateway:
    """Authenticate, deduplicate, route, and reply to channel messages."""

    def __init__(
        self,
        *,
        coordinator: ConversationCoordinator,
        principal_resolver: ChannelPrincipalResolver,
        ledger: ChannelMessageLedger,
        load_session: SessionLoader,
        attachment_ingestor: ChannelAttachmentIngestor | None = None,
        transition_sink: RoutingTransitionSink | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._principal_resolver = principal_resolver
        self._ledger = ledger
        self._load_session = load_session
        self._attachment_ingestor = attachment_ingestor
        self._transition_sink = transition_sink or default_transition_emitter()

    async def run(self, adapter: ConversationChannelAdapter) -> None:
        """Consume one adapter until its receive stream ends."""
        async for turn in adapter.receive():
            response = await self.handle(adapter=adapter, turn=turn)
            if response is not None:
                await adapter.send(response)

    async def handle(
        self,
        *,
        adapter: ConversationChannelAdapter,
        turn: InboundTurn,
    ) -> OutboundResponse | None:
        """Handle one normalized turn; return ``None`` for denied or duplicate input."""
        if adapter.channel_kind is not turn.channel_kind:
            raise ValueError("channel adapter kind does not match inbound turn")
        principal = await self._principal_resolver.resolve(turn)
        if principal is None:
            self._emit(turn, "principal.resolve", "rejected", {"reason_code": "unresolved"})
            return None
        idempotency_key = _message_key(turn)
        if not await self._ledger.claim(idempotency_key):
            self._emit(turn, "message.claim", "rejected", {"reason_code": "duplicate"})
            return None
        try:
            attachment_evidence: tuple[str, ...] = ()
            if turn.attachments:
                if self._attachment_ingestor is None:
                    return _attachment_error(turn, "channel attachment ingestion is unavailable")
                ingestion = await self._attachment_ingestor.ingest(
                    turn=turn,
                    principal=principal,
                )
                if ingestion.status == "rejected":
                    return _attachment_error(turn, ingestion.reason)
                attachment_evidence = ingestion.evidence_refs
            session_id = _session_id(turn, principal)
            session = await self._load_session(session_id, principal, turn.channel_id)
            result = self._coordinator.handle_turn(session=session, message=turn.text)
            result_status = result.status if isinstance(result, ToolResult) else "abstain"
            self._emit(turn, "message.handled", "accepted", {"status": result_status})
            return _to_response(turn, result, attachment_evidence=attachment_evidence)
        except Exception:
            await self._ledger.release(idempotency_key)
            raise

    def _emit(
        self,
        turn: InboundTurn,
        name: str,
        outcome: str,
        attributes: dict[str, str],
    ) -> None:
        emit_transition_safely(
            self._transition_sink,
            RoutingTransition(
                domain="channel",
                name=name,
                outcome=outcome,
                attributes={"channel_kind": turn.channel_kind.value, **attributes},
            ),
        )


def _message_key(turn: InboundTurn) -> str:
    raw = f"{turn.channel_kind.value}\0{turn.channel_id}\0{turn.message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _session_id(turn: InboundTurn, principal: Principal) -> str:
    thread = turn.thread_id or turn.sender_id
    raw = f"{turn.channel_kind.value}\0{turn.channel_id}\0{thread}\0{principal.id}"
    return "channel:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def _to_response(
    turn: InboundTurn,
    result: ToolResult | AbstainResult,
    *,
    attachment_evidence: tuple[str, ...] = (),
) -> OutboundResponse:
    if isinstance(result, ToolResult):
        return OutboundResponse(
            channel_kind=turn.channel_kind,
            channel_id=turn.channel_id,
            in_reply_to=turn.message_id,
            thread_id=turn.thread_id,
            status=result.status,
            text=result.preview,
            data=result.data,
            evidence_refs=tuple(dict.fromkeys((*result.evidence_refs, *attachment_evidence))),
        )
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="abstain",
        text=result.reason,
        data={"tool_inventory": list(result.tool_inventory)},
    )


def _attachment_error(turn: InboundTurn, reason: str) -> OutboundResponse:
    return OutboundResponse(
        channel_kind=turn.channel_kind,
        channel_id=turn.channel_id,
        in_reply_to=turn.message_id,
        thread_id=turn.thread_id,
        status="error",
        text=reason,
    )


__all__ = [
    "AttachmentIngestionResult",
    "ChannelAttachmentIngestor",
    "ChannelMessageLedger",
    "ChannelPrincipalResolver",
    "ConversationChannelGateway",
    "SessionLoader",
]
