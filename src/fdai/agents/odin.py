"""Odin - Master Planner (Wave 4 behavior).

Odin arbitrates cross-vertical priority conflicts. When Forseti emits
an ArbitrationRequest (verdict with ``domain_conflict: true``), Odin
resolves it with a deterministic **multi-objective** arbiter loaded at
boot (default weights derived from ``resilience > security >
change_safety > cost > capacity``). Fork adapters override the priority
order or the weights via config.

The arbiter is a strict superset of the legacy priority table: with equal
impacts it reproduces the priority-order winner, but when a conflict
carries measured impact magnitudes it scores ``weight * impact`` per
domain and escalates near-ties to HIL instead of silently picking (see
:mod:`fdai.agents.arbitration`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fdai.agents.arbitration import _DEFAULT_PRIORITY, MultiObjectiveArbiter
from fdai.agents.base import Agent
from fdai.agents.bus import PantheonBus
from fdai.agents.introspection import IntrospectionResult, capability_facts
from fdai.agents.pantheon import _ODIN


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    correlation_id: str
    winning_domain: str
    losing_domains: tuple[str, ...]
    reason: str
    # Multi-objective grounding (defaults keep legacy construction valid).
    objective_scores: dict[str, float] = field(default_factory=dict)
    margin: float = 0.0
    escalate_hil: bool = False


class Odin(Agent):
    """Wave-4 Odin: arbitration + portfolio outcome monitor."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        priority: tuple[str, ...] = _DEFAULT_PRIORITY,
        weights: dict[str, float] | None = None,
        hil_margin: float = 0.10,
    ) -> None:
        super().__init__(spec=_ODIN)
        self.bus = bus
        self._priority = priority
        self._arbiter = MultiObjectiveArbiter(
            priority=priority,
            weights=weights,
            hil_margin=hil_margin,
        )

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.arbitration-request":
            return
        await self.arbitrate(payload)

    async def arbitrate(self, request: dict[str, Any]) -> ArbitrationDecision:
        domains = tuple(str(d) for d in request.get("domains_in_conflict", ()))
        impacts = _coerce_impacts(request.get("impacts"))
        outcome = self._arbiter.resolve(domains, impacts)
        decision = ArbitrationDecision(
            correlation_id=str(request.get("correlation_id", "")),
            winning_domain=outcome.winner,
            losing_domains=outcome.losers,
            reason=outcome.reason,
            objective_scores=outcome.objective_scores,
            margin=outcome.margin,
            escalate_hil=outcome.escalate_hil,
        )
        if self.bus is not None:
            await self.bus.publish(
                "Odin",
                "object.arbitration-decision",
                {
                    "producer_principal": "Odin",
                    "correlation_id": decision.correlation_id,
                    "winning_domain": decision.winning_domain,
                    "losing_domains": list(decision.losing_domains),
                    "reason": decision.reason,
                    "objective_scores": decision.objective_scores,
                    "margin": decision.margin,
                    "escalate_hil": decision.escalate_hil,
                },
            )
        return decision

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "priority_order": list(self._priority),
        }
        answer = (
            "I arbitrate cross-vertical conflicts by priority "
            f"({' > '.join(self._priority)}), escalating near-ties to HIL."
        )
        return IntrospectionResult(answer=answer, facts=facts)


def _coerce_impacts(raw: Any) -> dict[str, float] | None:
    """Coerce an untrusted ``impacts`` payload into ``{domain: float}``.

    Non-numeric or missing values are dropped so a malformed signal
    degrades to the priority-order fallback rather than raising.
    """
    if not isinstance(raw, dict):
        return None
    coerced: dict[str, float] = {}
    for key, value in raw.items():
        try:
            coerced[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return coerced or None


__all__ = ["Odin", "ArbitrationDecision"]
