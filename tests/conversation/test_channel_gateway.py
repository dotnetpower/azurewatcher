"""Bidirectional channel gateway identity, routing, and dedupe tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

import pytest

from fdai.core.conversation.channel_gateway import (
    AttachmentIngestionResult,
    ConversationChannelGateway,
)
from fdai.core.conversation.coordinator import ConversationCoordinator
from fdai.core.conversation.session import ConversationSession, Principal, Role
from fdai.core.conversation.tools import ToolResult
from fdai.shared.providers.conversation_channel import (
    ChannelAttachment,
    ConversationChannelKind,
    InboundTurn,
    OutboundResponse,
)
from fdai.shared.telemetry import InMemoryRoutingTransitionSink


class _ReadTool:
    name = "explore_catalog"
    description = "test"
    rbac_floor = Role.READER
    side_effect_class = "read"
    calls: list[Mapping[str, object]] = []

    def call(self, *, arguments: Mapping[str, object], principal: Principal) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(status="ok", preview=f"found {arguments['query']}")


class _AttachmentIngestor:
    def __init__(self, result: AttachmentIngestionResult) -> None:
        self.result = result

    async def ingest(
        self,
        *,
        turn: InboundTurn,
        principal: Principal,
    ) -> AttachmentIngestionResult:
        return self.result


class _Resolver:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal

    async def resolve(self, turn: InboundTurn) -> Principal | None:
        return self.principal


class _Ledger:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim(self, idempotency_key: str) -> bool:
        if idempotency_key in self.claimed:
            return False
        self.claimed.add(idempotency_key)
        return True

    async def release(self, idempotency_key: str) -> None:
        self.claimed.discard(idempotency_key)


class _Adapter:
    channel_kind = ConversationChannelKind.TEAMS

    def __init__(self, turns: tuple[InboundTurn, ...] = ()) -> None:
        self.turns = turns
        self.sent: list[OutboundResponse] = []

    async def receive(self) -> AsyncIterator[InboundTurn]:
        for turn in self.turns:
            yield turn

    async def send(self, response: OutboundResponse) -> None:
        self.sent.append(response)


def _turn(message_id: str = "message-1") -> InboundTurn:
    return InboundTurn(
        channel_kind=ConversationChannelKind.TEAMS,
        channel_id="channel-1",
        message_id=message_id,
        sender_id="sender-1",
        thread_id="thread-1",
        text="explore_catalog storage",
    )


def _gateway(
    principal: Principal | None = None,
    *,
    deny_sender: bool = False,
    attachment_ingestor: _AttachmentIngestor | None = None,
    transition_sink: InMemoryRoutingTransitionSink | None = None,
) -> ConversationChannelGateway:
    sessions: dict[str, ConversationSession] = {}

    async def load_session(
        session_id: str, resolved: Principal, channel_id: str
    ) -> ConversationSession:
        return sessions.setdefault(
            session_id,
            ConversationSession(
                session_id=session_id,
                principal=resolved,
                channel_id=channel_id,
            ),
        )

    return ConversationChannelGateway(
        coordinator=ConversationCoordinator(tools=[_ReadTool()]),
        principal_resolver=_Resolver(
            None if deny_sender else (principal or Principal(id="principal-1", role=Role.READER))
        ),
        ledger=_Ledger(),
        load_session=load_session,
        attachment_ingestor=attachment_ingestor,
        transition_sink=transition_sink,
    )


async def test_routes_authenticated_turn_back_to_same_thread() -> None:
    adapter = _Adapter((_turn(),))

    await _gateway().run(adapter)

    assert len(adapter.sent) == 1
    assert adapter.sent[0].thread_id == "thread-1"
    assert adapter.sent[0].in_reply_to == "message-1"
    assert adapter.sent[0].text == "found storage"


async def test_channel_gateway_emits_stable_handled_transition() -> None:
    transitions = InMemoryRoutingTransitionSink()
    await _gateway(transition_sink=transitions).handle(adapter=_Adapter(), turn=_turn())

    assert transitions.transitions[0].domain == "channel"
    assert transitions.transitions[0].name == "message.handled"


async def test_duplicate_message_is_not_executed_or_sent_twice() -> None:
    turn = _turn()
    adapter = _Adapter((turn, turn))

    await _gateway().run(adapter)

    assert len(adapter.sent) == 1


async def test_unresolved_sender_is_denied_before_coordinator() -> None:
    adapter = _Adapter((_turn(),))
    gateway = _gateway(deny_sender=True)

    await gateway.run(adapter)

    assert adapter.sent == []


async def test_adapter_kind_mismatch_fails_closed() -> None:
    adapter = _Adapter()
    slack_turn = InboundTurn(
        channel_kind=ConversationChannelKind.SLACK,
        channel_id="channel-1",
        message_id="message-1",
        sender_id="sender-1",
        text="explore_catalog storage",
    )

    with pytest.raises(ValueError, match="kind"):
        await _gateway().handle(adapter=adapter, turn=slack_turn)


def test_inbound_turn_rejects_oversized_text() -> None:
    with pytest.raises(ValueError, match="exceeds cap"):
        InboundTurn(
            channel_kind=ConversationChannelKind.WEB,
            channel_id="channel-1",
            message_id="message-1",
            sender_id="sender-1",
            text="x" * 16_001,
        )


async def test_ready_attachment_becomes_citation_never_tool_instruction() -> None:
    _ReadTool.calls.clear()
    turn = replace(
        _turn(),
        attachments=(
            ChannelAttachment(
                source_ref="file-1",
                name="evidence.txt",
                size_bytes=12,
                media_type_hint="text/plain",
            ),
        ),
    )
    response = await _gateway(
        attachment_ingestor=_AttachmentIngestor(
            AttachmentIngestionResult(
                status="ready",
                evidence_refs=("doc:document-1:version-1",),
            )
        )
    ).handle(adapter=_Adapter(), turn=turn)

    assert response is not None
    assert response.evidence_refs == ("doc:document-1:version-1",)
    assert _ReadTool.calls == [{"query": "storage"}]


async def test_rejected_attachment_never_invokes_tool() -> None:
    _ReadTool.calls.clear()
    turn = replace(
        _turn(),
        attachments=(
            ChannelAttachment(
                source_ref="file-1",
                name="evidence.txt",
                size_bytes=12,
                media_type_hint="text/plain",
            ),
        ),
    )
    response = await _gateway(
        attachment_ingestor=_AttachmentIngestor(
            AttachmentIngestionResult(status="rejected", reason="attachment held")
        )
    ).handle(adapter=_Adapter(), turn=turn)

    assert response is not None and response.status == "error"
    assert response.evidence_refs == ()
    assert _ReadTool.calls == []
