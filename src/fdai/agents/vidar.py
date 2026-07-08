"""Vidar - Recovery (Wave 3 behavior).

Vidar performs rollback per an ActionType's `rollback_contract` and
DR failover. Wave 3 stubs the rollback into a bookkeeping call that
publishes a `Rollback` payload; real integration lives behind the
provider protocols in later waves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fdai.agents.base import Agent
from fdai.agents.bus import PantheonBus
from fdai.agents.pantheon import _VIDAR


@dataclass
class RollbackRecord:
    correlation_id: str
    action_type: str
    resource_id: str | None
    contract: str
    state: str  # succeeded | failed
    notes: str = ""


class Vidar(Agent):
    """Wave-3 Vidar: rollback executor. Hard dependency for Thor."""

    def __init__(self, *, bus: PantheonBus | None = None) -> None:
        super().__init__(spec=_VIDAR)
        self.bus = bus
        self.records: list[RollbackRecord] = field(default_factory=list) if False else []

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        # Vidar only reacts on failed ActionRuns.
        if topic != "object.action-run":
            return
        if payload.get("state") != "failed":
            return
        await self.rollback(payload)

    async def rollback(self, action_run: dict[str, Any]) -> RollbackRecord:
        rec = RollbackRecord(
            correlation_id=str(action_run.get("correlation_id", "")),
            action_type=str(action_run.get("action_type", "")),
            resource_id=action_run.get("resource_id"),
            contract=str(action_run.get("rollback_contract", "state_forward_only")),
            state="succeeded",  # in-memory rollback always succeeds
            notes="in-memory rollback (Wave 3)",
        )
        self.records.append(rec)
        if self.bus is not None:
            await self.bus.publish(
                "Vidar",
                "object.rollback",
                {
                    "producer_principal": "Vidar",
                    "correlation_id": rec.correlation_id,
                    "action_type": rec.action_type,
                    "resource_id": rec.resource_id,
                    "contract": rec.contract,
                    "state": rec.state,
                },
            )
        return rec


__all__ = ["Vidar", "RollbackRecord"]
