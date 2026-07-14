"""Event-bus transport for durable HIL decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.hil_registry import HilDecisionReceipt

DEFAULT_HIL_DECISION_TOPIC: Final[str] = "aw.hil.decisions"


@dataclass(frozen=True, slots=True)
class EventBusHilDecisionPublisher:
    bus: EventBus
    topic: str = DEFAULT_HIL_DECISION_TOPIC

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("HIL decision topic MUST be non-empty")

    async def __call__(self, receipt: HilDecisionReceipt) -> None:
        await self.bus.publish(
            self.topic,
            receipt.approval_id,
            {
                "approval_id": receipt.approval_id,
                "idempotency_key": receipt.idempotency_key,
                "decision": receipt.decision.value,
                "approver_oid": receipt.approver_oid,
                "justification": receipt.justification,
                "decided_at": receipt.decided_at.isoformat(),
                "receipt_ref": receipt.receipt_ref,
            },
        )

    async def close(self) -> None:
        close = getattr(self.bus, "close", None)
        if callable(close):
            await close()


__all__ = ["DEFAULT_HIL_DECISION_TOPIC", "EventBusHilDecisionPublisher"]
