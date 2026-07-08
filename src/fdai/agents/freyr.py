"""Freyr - Capacity (Wave 5 behavior).

Freyr samples utilization, projects forward via a light exponential
smoothing forecast, and exposes a sizing advisory hook.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.agents.base import Agent
from fdai.agents.bus import PantheonBus
from fdai.agents.pantheon import _FREYR


@dataclass(frozen=True, slots=True)
class SizingRecommendation:
    resource_id: str
    current_util: float
    forecast_util: float
    action: str  # scale_up | scale_down | hold


class Freyr(Agent):
    """Wave-5 Freyr: utilization forecast + sizing advisor."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        smoothing_alpha: float = 0.3,
        scale_up_threshold: float = 0.75,
        scale_down_threshold: float = 0.25,
    ) -> None:
        super().__init__(spec=_FREYR)
        self.bus = bus
        self._alpha = smoothing_alpha
        self._up = scale_up_threshold
        self._down = scale_down_threshold
        self._smoothed: dict[str, float] = {}
        self._samples: dict[str, list[float]] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def ingest_utilization(
        self,
        *,
        resource_id: str,
        utilization: float,
        correlation_id: str = "",
    ) -> None:
        prev = self._smoothed.get(resource_id, utilization)
        smoothed = self._alpha * utilization + (1 - self._alpha) * prev
        self._smoothed[resource_id] = smoothed
        self._samples.setdefault(resource_id, []).append(utilization)
        if self.bus is not None:
            await self.bus.publish(
                "Freyr",
                "object.capacity-forecast",
                {
                    "producer_principal": "Freyr",
                    "correlation_id": correlation_id or resource_id,
                    "resource_id": resource_id,
                    "forecast_util": smoothed,
                    "recent_samples": len(self._samples[resource_id]),
                    # Sizing action doubles as the arbitration recommendation
                    # (scale_up under high utilization can conflict with a
                    # cost-driven scale_down).
                    "recommendation": self.sizing_advice(resource_id).action,
                },
            )

    def sizing_advice(self, resource_id: str) -> SizingRecommendation:
        samples = self._samples.get(resource_id)
        current = samples[-1] if samples else 0.0
        forecast = self._smoothed.get(resource_id, current)
        if forecast >= self._up:
            action = "scale_up"
        elif forecast <= self._down and len(self._samples.get(resource_id, [])) >= 3:
            action = "scale_down"
        else:
            action = "hold"
        return SizingRecommendation(
            resource_id=resource_id,
            current_util=current,
            forecast_util=forecast,
            action=action,
        )


__all__ = ["Freyr", "SizingRecommendation"]
