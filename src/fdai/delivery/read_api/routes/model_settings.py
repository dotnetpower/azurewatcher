"""Sanitized LLM capability projection and principal-scoped narrator preference."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.read_api.routes.chat import LatencyRoutedChatBackend
from fdai.shared.providers.state_store import StateStore

_PREFERENCE_PREFIX = "user-model-preference:"


@dataclass(frozen=True, slots=True)
class ModelSettingsService:
    """Combine resolved capability state, runtime metrics, and user preference."""

    resolved_models_path: Path
    store: StateStore
    backend: object | None = None
    automatic_discovery: bool = True
    automatic_provisioning: bool = True

    async def preferred_model(self, principal_id: str) -> str | None:
        record = await self.store.read_state(_preference_key(principal_id))
        requested = record.get("preferred_narrator_model") if record else None
        if not isinstance(requested, str) or requested == "auto":
            return None
        return requested if requested in self._candidate_names() else None

    async def set_preference(self, principal_id: str, requested: str) -> dict[str, Any]:
        normalized = requested.strip()
        if normalized != "auto" and normalized not in self._candidate_names():
            raise ValueError("preferred narrator model MUST be auto or an available candidate")
        record = {
            "principal_id": principal_id,
            "preferred_narrator_model": normalized,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        await self.store.write_state(_preference_key(principal_id), record)
        return record

    async def projection(self, principal_id: str) -> dict[str, Any]:
        resolved = self._load_resolved()
        capabilities = [
            _capability_view(item)
            for item in resolved.get("capabilities", [])
            if isinstance(item, dict) and str(item.get("name") or "").startswith(("t1.", "t2."))
        ]
        requested_record = await self.store.read_state(_preference_key(principal_id))
        requested = requested_record.get("preferred_narrator_model") if requested_record else "auto"
        if not isinstance(requested, str):
            requested = "auto"
        candidates = self._candidate_views(resolved)
        candidate_names = {item["deployment"] for item in candidates}
        effective = requested if requested in candidate_names else "auto"
        fallback_reason = (
            "preferred deployment is no longer available; automatic routing is active"
            if requested != "auto" and effective == "auto"
            else None
        )
        resolved_count = sum(
            item["status"] in {"resolved", "capacity-reduced"} for item in capabilities
        )
        hil_only_count = sum(item["status"] == "hil-only" for item in capabilities)
        return {
            "region": resolved.get("region"),
            "mixed_model_mode": resolved.get("mixed_model_mode"),
            "discovery": {
                "automatic": self.automatic_discovery,
                "source": "rule-catalog/llm-registry.yaml",
                "status": "enabled" if self.automatic_discovery else "disabled",
            },
            "provisioning": {
                "automatic": self.automatic_provisioning,
                "status": "degraded" if hil_only_count else "ready",
                "resolved_count": resolved_count,
                "hil_only_count": hil_only_count,
            },
            "capabilities": capabilities,
            "narrator": {
                "selection_scope": "per-user",
                "requested": requested,
                "effective": effective,
                "fallback_reason": fallback_reason,
                "current_auto_pick": (
                    self.backend.current_pick_name()
                    if isinstance(self.backend, LatencyRoutedChatBackend)
                    else None
                ),
                "candidates": candidates,
            },
            "t2_selection_scope": "system-governed",
        }

    def _candidate_names(self) -> tuple[str, ...]:
        if isinstance(self.backend, LatencyRoutedChatBackend):
            return self.backend.candidate_names()
        resolved = self._load_resolved()
        return tuple(
            str(item["deployment"])
            for item in resolved.get("narrator_candidates", [])
            if isinstance(item, dict) and isinstance(item.get("deployment"), str)
        )

    def _candidate_views(self, resolved: dict[str, Any]) -> list[dict[str, Any]]:
        router_stats = (
            self.backend.stats() if isinstance(self.backend, LatencyRoutedChatBackend) else []
        )
        stats = {item["deployment"]: item for item in router_stats}
        families = {
            item.get("name"): item.get("family")
            for item in resolved.get("capabilities", [])
            if isinstance(item, dict)
        }
        return [
            {
                "deployment": name,
                "family": families.get(name),
                "status": "available",
                "total_p50_ms": stats.get(name, {}).get("p50_ms"),
                "total_p95_ms": stats.get(name, {}).get("p95_ms"),
                "total_samples": stats.get(name, {}).get("samples", 0),
                "ttft_p50_ms": stats.get(name, {}).get("ttft_p50_ms"),
                "ttft_p95_ms": stats.get(name, {}).get("ttft_p95_ms"),
                "ttft_samples": stats.get(name, {}).get("ttft_samples", 0),
            }
            for name in self._candidate_names()
        ]

    def _load_resolved(self) -> dict[str, Any]:
        try:
            value = json.loads(self.resolved_models_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


def make_model_settings_routes(
    *,
    service: ModelSettingsService,
    authorize: Any,
) -> tuple[Route, ...]:
    async def get_settings(request: Request) -> Response:
        principal_id = await authorize(request)
        return JSONResponse(await service.projection(principal_id))

    async def put_preference(request: Request) -> Response:
        principal_id = await authorize(request)
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body MUST be an object")
        requested = body.get("preferred_narrator_model")
        if not isinstance(requested, str):
            raise HTTPException(
                status_code=400,
                detail="preferred_narrator_model MUST be a string",
            )
        try:
            await service.set_preference(principal_id, requested)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(await service.projection(principal_id))

    return (
        Route("/models/settings", get_settings, methods=["GET"]),
        Route("/me/model-preferences", put_preference, methods=["PUT"]),
    )


def _capability_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name"),
        "tier": str(item.get("name") or "").split(".", 1)[0].upper(),
        "publisher": item.get("publisher"),
        "family": item.get("family"),
        "status": item.get("status"),
        "capacity_tpm": item.get("capacity_tpm"),
        "invocation": item.get("invocation"),
        "reasons": item.get("reasons") if isinstance(item.get("reasons"), list) else [],
        "user_selectable": False,
    }


def _preference_key(principal_id: str) -> str:
    return f"{_PREFERENCE_PREFIX}{principal_id}"


__all__ = ["ModelSettingsService", "make_model_settings_routes"]
