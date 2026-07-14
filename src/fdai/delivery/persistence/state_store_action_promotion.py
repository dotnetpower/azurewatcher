"""StateStore-backed ActionPromotionRegistry with fail-closed refresh."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fdai.core.risk_gate import (
    ActionModeRecord,
    ActionPromotionRegistry,
    PromotionMetrics,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore

_PREFIX = "action_promotion:"


class StateStoreActionPromotionRegistry(ActionPromotionRegistry):
    """Keep the RiskGate sync read API over an asynchronously refreshed cache."""

    def __init__(self, *, store: StateStore) -> None:
        super().__init__()
        self._store = store

    async def refresh(self, action_type: str) -> None:
        try:
            raw = await self._store.read_state(_key(action_type))
            if raw is None:
                self._records.pop(action_type, None)
                return
            record = _deserialize(raw)
            if record.action_type != action_type:
                raise ValueError("persisted action_type does not match key")
            self._records[action_type] = record
        except Exception:
            # A stale cached ENFORCE is unsafe when the authority store is
            # unavailable or corrupt. Clear it so mode_of() returns SHADOW.
            self._records.pop(action_type, None)

    async def persist(self, action_type: str) -> None:
        record = self.record(action_type)
        if record is None:
            record = self.demote(action_type)
        await self._store.write_state(_key(action_type), _serialize(record))


def _key(action_type: str) -> str:
    return f"{_PREFIX}{action_type}"


def _serialize(record: ActionModeRecord) -> dict[str, Any]:
    metrics = record.metrics
    return {
        "schema_version": "1.0.0",
        "action_type": record.action_type,
        "mode": record.mode.value,
        "promoted_at": record.promoted_at.isoformat() if record.promoted_at else None,
        "demoted_at": record.demoted_at.isoformat() if record.demoted_at else None,
        "metrics": (
            {
                "action_type": metrics.action_type,
                "shadow_days": metrics.shadow_days,
                "samples": metrics.samples,
                "accuracy": metrics.accuracy,
                "policy_escapes": metrics.policy_escapes,
            }
            if metrics is not None
            else None
        ),
    }


def _deserialize(raw: Any) -> ActionModeRecord:
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported promotion state")
    metrics_raw = raw.get("metrics")
    metrics = None
    if isinstance(metrics_raw, dict):
        metrics = PromotionMetrics(
            action_type=str(metrics_raw["action_type"]),
            shadow_days=int(metrics_raw["shadow_days"]),
            samples=int(metrics_raw["samples"]),
            accuracy=float(metrics_raw["accuracy"]),
            policy_escapes=int(metrics_raw["policy_escapes"]),
        )
    return ActionModeRecord(
        action_type=str(raw["action_type"]),
        mode=Mode(str(raw["mode"])),
        promoted_at=_timestamp(raw.get("promoted_at")),
        demoted_at=_timestamp(raw.get("demoted_at")),
        metrics=metrics,
    )


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("promotion timestamp MUST be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


__all__ = ["StateStoreActionPromotionRegistry"]
