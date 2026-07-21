"""Audit-derived autonomy measurements with explicit unavailable values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any, TypeGuard

from fdai.delivery.read_api.read_model import AuditItem, AuditQueryFilters, ConsoleReadModel
from fdai.delivery.read_api.routes.measurement_summary import _vertical_of

_AUTO_RESOLVED = frozenset(
    {
        "auto",
        "executed",
        "remediated",
        "resolved",
        "rollback_completed",
        "rollback_succeeded",
        "succeeded",
        "success",
        "verified",
    }
)
_HUMAN_TOUCH = frozenset({"awaiting_approval", "escalated_hil", "hil", "hil.await", "hil_pending"})
_VERTICAL_KEYS = ("resilience", "change_safety", "cost")


class AuditAutonomyMeasurementPanel:
    """Project only measurements present in the durable audit window."""

    def __init__(
        self,
        read_model: ConsoleReadModel,
        *,
        active_rule_count: int = 0,
        window_days: int = 30,
    ) -> None:
        self._read_model = read_model
        self._active_rule_count = active_rule_count
        self._window_days = window_days

    @property
    def path(self) -> str:
        return "/kpi/autonomy"

    @property
    def name(self) -> str:
        return "autonomy"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        page = await self._read_model.list_audit(
            limit=500,
            filters=AuditQueryFilters(window_days=self._window_days),
        )
        return _audit_payload(
            tuple(page.items),
            window_days=self._window_days,
            active_rule_count=self._active_rule_count,
        )


def _audit_payload(
    items: Sequence[AuditItem],
    *,
    window_days: int,
    active_rule_count: int,
) -> Mapping[str, Any]:
    outcomes = [str(item.entry.get("outcome", "")).strip().lower() for item in items]
    decided = [outcome for outcome in outcomes if outcome]
    auto_count = sum(outcome in _AUTO_RESOLVED for outcome in decided)
    human_count = sum(outcome in _HUMAN_TOUCH for outcome in decided)
    auto_rate = auto_count / len(decided) if decided else None
    touchpoints = human_count * 100.0 / len(decided) if decided else None

    verticals: dict[str, dict[str, float]] = {
        key: {"events": 0, "auto_resolved": 0, "open_risks": 0, "monthly_savings": 0.0}
        for key in _VERTICAL_KEYS
    }
    by_tier: dict[str, int] = {}
    for item, outcome in zip(items, outcomes, strict=True):
        bucket = verticals[_vertical_of(item.action_kind)]
        bucket["events"] += 1
        if outcome in _AUTO_RESOLVED:
            bucket["auto_resolved"] += 1
        if outcome in _HUMAN_TOUCH:
            bucket["open_risks"] += 1
        savings = item.entry.get("estimated_savings")
        if _is_number(savings):
            bucket["monthly_savings"] += float(savings)
        tier = item.entry.get("tier")
        if isinstance(tier, str) and tier in {"t0", "t1", "t2"}:
            by_tier[tier] = by_tier.get(tier, 0) + 1

    tier_total = sum(by_tier.values())
    tier_mix = {
        key: by_tier.get(key, 0) / tier_total if tier_total else 0.0 for key in ("t0", "t1", "t2")
    }
    return {
        "synthetic": False,
        "window_days": window_days,
        "sample_size": len(items),
        "confidence": None,
        "source": {
            "name": "postgres-audit",
            "kind": "audit",
            "as_of": items[0].recorded_at if items else None,
        },
        "rules": {
            "active": active_rule_count,
            "candidates_30d": sum(item.entry.get("kind") == "rule.candidate" for item in items),
            "promoted_30d": sum(item.entry.get("kind") == "rule.promoted" for item in items),
        },
        "success": {
            "auto_resolution_rate": _metric(items, "auto_resolution_rate", "higher", auto_rate),
            "human_touchpoints_per_100": _metric(
                items, "human_touchpoints_per_100", "lower", touchpoints
            ),
            "mttr_seconds": _metric(items, "mttr_seconds", "lower"),
            "change_lead_time_seconds": _metric(items, "change_lead_time_seconds", "lower"),
            "cost_per_resolved_event_usd": _metric(items, "cost_per_resolved_event_usd", "lower"),
        },
        "leading": {
            "mixed_model_disagreement_rate": _metric(
                items, "mixed_model_disagreement_rate", "lower"
            ),
            "verifier_failure_rate": _metric(items, "verifier_failure_rate", "lower"),
            "shadow_divergence_rate": _metric(items, "shadow_divergence_rate", "lower"),
        },
        "guards": _guards(items),
        "verticals": [
            {
                "key": key,
                "events": int(bucket["events"]),
                "auto_resolved": int(bucket["auto_resolved"]),
                "open_risks": int(bucket["open_risks"]),
                "monthly_savings": round(bucket["monthly_savings"], 2),
            }
            for key, bucket in verticals.items()
        ],
        "tier": {
            "mix": tier_mix,
            "bands": {"t0": [0.7, 0.8], "t1": [0.15, 0.2], "t2": [0.05, 0.1]},
        },
        "trend": {},
    }


def _metric(
    items: Sequence[AuditItem],
    key: str,
    direction: str,
    derived_value: float | None = None,
) -> Mapping[str, Any]:
    measured = _values(items, key)
    baselines = _values(items, key, baseline=True)
    return {
        "value": fmean(measured) if measured else derived_value,
        "baseline": fmean(baselines) if baselines else None,
        "direction": direction,
    }


def _values(items: Sequence[AuditItem], key: str, *, baseline: bool = False) -> list[float]:
    values: list[float] = []
    for item in items:
        container = item.entry.get("baseline" if baseline else "measurement")
        raw = container.get(key) if isinstance(container, Mapping) else None
        if raw is None:
            raw = item.entry.get(f"baseline_{key}" if baseline else key)
        if _is_number(raw):
            values.append(float(raw))
    return values


def _guards(items: Sequence[AuditItem]) -> list[Mapping[str, Any]]:
    for item in items:
        raw = item.entry.get("guards")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        guards = [guard for guard in raw if _valid_guard(guard)]
        if guards:
            return [dict(guard) for guard in guards]
    return []


def _valid_guard(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("key"), str)
        and all(_is_number(value.get(key)) for key in ("value", "baseline", "threshold"))
        and isinstance(value.get("ok"), bool)
    )


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = ["AuditAutonomyMeasurementPanel"]
