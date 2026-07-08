"""Var - Approver (Wave 3 + Wave 6 behavior).

Var carries the HIL approval principal (Wave 3) and delivers admin
security notifications through the ChatOps admin channel (Wave 6).
Every card is deduped by (initiator, action_type) within a rolling
window and the last-seen counter is incremented on repeat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fdai.agents.adapters import AdminCard, InMemoryAdminChannel
from fdai.agents.base import Agent
from fdai.agents.bus import PantheonBus
from fdai.agents.pantheon import _VAR


@dataclass
class PendingHilTicket:
    correlation_id: str
    action_type: str
    resource_id: str | None
    quorum_required: int
    approvers: list[str] = field(default_factory=list)
    rejected: bool = False


class Var(Agent):
    """Wave-3 HIL approval + Wave-6 admin channel delivery."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        admin_channel: InMemoryAdminChannel | None = None,
    ) -> None:
        super().__init__(spec=_VAR)
        self.bus = bus
        self.admin_channel = admin_channel or InMemoryAdminChannel()
        self._pending: dict[str, PendingHilTicket] = {}
        # (initiator, action_type) -> AdminCard for dedup counter update
        self._last_cards: dict[tuple[str, str], AdminCard] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.action-run":
            return
        if payload.get("state") != "hil_pending":
            return
        correlation = str(payload.get("correlation_id", ""))
        if not correlation or correlation in self._pending:
            return
        self._pending[correlation] = PendingHilTicket(
            correlation_id=correlation,
            action_type=str(payload.get("action_type", "")),
            resource_id=payload.get("resource_id"),
            quorum_required=int(payload.get("quorum_required", 1)),
        )

    # ---- HIL decision --------------------------------------------------

    async def decide(
        self,
        correlation_id: str,
        *,
        approver: str,
        decision: str,
    ) -> dict[str, Any] | None:
        ticket = self._pending.get(correlation_id)
        if ticket is None:
            return None
        if decision == "reject":
            ticket.rejected = True
        elif decision == "approve":
            if approver in ticket.approvers:
                raise ValueError(
                    f"principal {approver!r} cannot self-approve twice on {correlation_id!r}"
                )
            ticket.approvers.append(approver)
        else:
            raise ValueError(f"unknown decision {decision!r}")

        if ticket.rejected or len(ticket.approvers) >= ticket.quorum_required:
            final = "rejected" if ticket.rejected else "approved"
            approval = {
                "producer_principal": "Var",
                "correlation_id": correlation_id,
                "action_type": ticket.action_type,
                "state": final,
                "approvers": list(ticket.approvers),
            }
            if self.bus is not None:
                await self.bus.publish("Var", "object.approval", approval)
            del self._pending[correlation_id]
            return approval
        return None

    def pending_tickets(self) -> tuple[PendingHilTicket, ...]:
        return tuple(self._pending.values())

    # ---- admin notification (Wave 6) ----------------------------------

    async def deliver_admin_card(self, payload: dict[str, Any]) -> AdminCard:
        """Deliver an admin ChatOps card. Dedups by (initiator, action)."""
        initiator = str(payload.get("initiator_principal", ""))
        action = str(payload.get("attempted_action", ""))
        severity = str(payload.get("severity", "high"))
        counter = int(payload.get("counter", 1))
        key = (initiator, action)
        existing = self._last_cards.get(key)
        if existing is not None:
            # Repeat: update counter in place rather than post a new card.
            new_card = AdminCard(
                severity=severity,
                initiator_principal=initiator,
                attempted_action=action,
                counter=counter,
            )
            self._last_cards[key] = new_card
            # Update the last delivered card's counter too
            self.admin_channel.cards[-1] = new_card
            return new_card
        card = AdminCard(
            severity=severity,
            initiator_principal=initiator,
            attempted_action=action,
            counter=counter,
        )
        self.admin_channel.send(card)
        self._last_cards[key] = card
        return card


__all__ = ["Var", "PendingHilTicket"]
