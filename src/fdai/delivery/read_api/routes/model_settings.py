"""Sanitized LLM capability projection and principal-scoped narrator preference."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.delivery.read_api.routes.chat import LatencyRoutedChatBackend
from fdai.shared.providers.state_store import StateStore

_PREFERENCE_PREFIX = "user-model-preference:"
_WEB_SEARCH_KEY = "model-settings:web-search"
_MAX_BODY_BYTES = 16_000
_DEFAULT_WEB_SEARCH_DOMAINS = (
    "learn.microsoft.com",
    "azure.microsoft.com",
    "nvd.nist.gov",
    "cve.org",
    "datatracker.ietf.org",
    "kubernetes.io",
    "docs.python.org",
    "postgresql.org",
)


@dataclass(frozen=True, slots=True)
class ModelSettingsService:
    """Combine resolved capability state, runtime metrics, and user preference."""

    resolved_models_path: Path
    store: StateStore
    backend: object | None = None
    web_search_resolver: object | None = None
    automatic_discovery: bool = True
    automatic_provisioning: bool = True

    def __post_init__(self) -> None:
        self._load_resolved()

    async def preferred_model(self, principal_id: str) -> str | None:
        record = await self.store.read_state(_preference_key(principal_id))
        requested = record.get("preferred_narrator_model") if record else None
        if not isinstance(requested, str) or requested == "auto":
            return None
        return requested if requested in self._candidate_names() else None

    async def set_preference(
        self,
        principal_id: str,
        requested: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized = requested.strip()
        if normalized != "auto" and normalized not in self._candidate_names():
            raise ValueError("preferred narrator model MUST be auto or an available candidate")
        record = {
            "principal_id": principal_id,
            "preferred_narrator_model": normalized,
            "revision": expected_revision + 1,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        updated = await self.store.compare_and_set_state_with_audit(
            _preference_key(principal_id),
            record,
            expected_revision=expected_revision,
            audit_entry={
                "event_id": str(uuid4()),
                "correlation_id": f"model-preference:{principal_id}",
                "actor": principal_id,
                "action_kind": "model.narrator-preference-updated",
                "mode": "enforce",
                "decision": "saved",
                "idempotency_key": f"model-preference:{principal_id}:{expected_revision + 1}",
                "timestamp": record["updated_at"],
            },
        )
        if not updated:
            raise ModelSettingsConflictError("narrator preference revision mismatch")
        return record

    async def projection(
        self,
        principal_id: str,
        *,
        can_manage_web_search: bool = False,
    ) -> dict[str, Any]:
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
        preference_revision = _record_revision(requested_record)
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
        web_search = await self._web_search_projection(can_manage=can_manage_web_search)
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
                "revision": preference_revision,
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
            "web_search": web_search,
            "t2_selection_scope": "system-governed",
        }

    async def set_web_search_settings(
        self,
        *,
        actor_id: str,
        enabled: bool,
        allowed_domains: tuple[str, ...],
        expected_revision: int,
    ) -> None:
        normalized = _normalize_domains(allowed_domains)
        if enabled and not normalized:
            raise ValueError("allowed_domains MUST contain at least one host when enabled")
        record = {
            "enabled": enabled,
            "allowed_domains": list(normalized),
            "revision": expected_revision + 1,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        updated = await self.store.compare_and_set_state_with_audit(
            _WEB_SEARCH_KEY,
            record,
            expected_revision=expected_revision,
            audit_entry={
                "event_id": str(uuid4()),
                "correlation_id": _WEB_SEARCH_KEY,
                "actor": actor_id,
                "action_kind": "model.web-search-settings-updated",
                "mode": "enforce",
                "decision": "saved",
                "idempotency_key": f"{_WEB_SEARCH_KEY}:{expected_revision + 1}",
                "timestamp": record["updated_at"],
            },
        )
        if not updated:
            raise ModelSettingsConflictError("web-search revision mismatch")
        self._apply_web_search(record)

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
        except (OSError, ValueError) as exc:
            raise ModelSettingsUnavailableError("resolved model metadata is unavailable") from exc
        if not isinstance(value, dict):
            raise ModelSettingsUnavailableError("resolved model metadata is invalid")
        return value

    async def _web_search_projection(self, *, can_manage: bool) -> dict[str, Any]:
        record = await self._web_search_record()
        self._apply_web_search(record)
        descriptor_fn = getattr(self.web_search_resolver, "descriptor", None)
        descriptor = descriptor_fn() if descriptor_fn is not None else {}
        router = descriptor.get("router") if isinstance(descriptor, Mapping) else None
        return {
            "enabled": bool(record["enabled"]),
            "allowed_domains": list(record["allowed_domains"]),
            "revision": int(record["revision"]),
            "can_manage": can_manage,
            "provider": "azure-responses",
            "current_auto_pick": (router.get("chose") if isinstance(router, Mapping) else None),
            "candidates": (
                list(router.get("candidates", [])) if isinstance(router, Mapping) else []
            ),
        }

    async def _web_search_record(self) -> dict[str, Any]:
        stored = await self.store.read_state(_WEB_SEARCH_KEY)
        if stored is None:
            descriptor_fn = getattr(self.web_search_resolver, "descriptor", None)
            descriptor = descriptor_fn() if descriptor_fn is not None else {}
            raw_domains = (
                descriptor.get("allowed_domains") if isinstance(descriptor, Mapping) else None
            )
            domains = (
                _normalize_domains(tuple(str(item) for item in raw_domains))
                if isinstance(raw_domains, list) and raw_domains
                else _DEFAULT_WEB_SEARCH_DOMAINS
            )
            enabled = (
                bool(descriptor.get("enabled", True)) if isinstance(descriptor, Mapping) else True
            )
            return {"enabled": enabled, "allowed_domains": list(domains), "revision": 0}
        stored_enabled = stored.get("enabled")
        stored_domains = stored.get("allowed_domains")
        stored_revision = stored.get("revision")
        if (
            not isinstance(stored_enabled, bool)
            or not isinstance(stored_domains, list)
            or not isinstance(stored_revision, int)
            or isinstance(stored_revision, bool)
            or stored_revision < 1
        ):
            raise RuntimeError("stored web-search settings are invalid")
        normalized = _normalize_domains(tuple(str(item) for item in stored_domains))
        if stored_enabled and not normalized:
            raise RuntimeError("stored enabled web-search settings have no domains")
        return {
            "enabled": stored_enabled,
            "allowed_domains": list(normalized),
            "revision": stored_revision,
        }

    def _apply_web_search(self, record: Mapping[str, Any]) -> None:
        update = getattr(self.web_search_resolver, "update_settings", None)
        if update is None:
            return
        update(
            enabled=bool(record["enabled"]),
            allowed_domains=tuple(str(item) for item in record["allowed_domains"]),
        )


class ModelSettingsConflictError(ValueError):
    """A deployment-wide settings write used a stale revision."""


class ModelSettingsUnavailableError(RuntimeError):
    """Resolved model metadata cannot produce a valid Settings projection."""


def make_model_settings_routes(
    *,
    service: ModelSettingsService,
    authorize: Any,
    authorize_principal: Callable[[Request], Awaitable[Principal]],
) -> tuple[Route, ...]:
    async def get_settings(request: Request) -> Response:
        principal = await authorize_principal(request)
        try:
            projection = await service.projection(
                principal.oid,
                can_manage_web_search=has_capability(
                    principal.roles,
                    Capability.MANAGE_GROUP_MEMBERSHIP,
                ),
            )
        except ModelSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(projection)

    async def put_preference(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _read_json_body(request)
        requested = body.get("preferred_narrator_model")
        expected_revision = body.get("expected_revision")
        if not isinstance(requested, str):
            raise HTTPException(
                status_code=400,
                detail="preferred_narrator_model MUST be a string",
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise HTTPException(status_code=400, detail="expected_revision MUST be >= 0")
        try:
            await service.set_preference(
                principal_id,
                requested,
                expected_revision=expected_revision,
            )
        except ModelSettingsConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ModelSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(await service.projection(principal_id))

    async def put_web_search(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
            raise HTTPException(status_code=403, detail="Owner role is required")
        body = await _read_json_body(request)
        enabled = body.get("enabled")
        domains = body.get("allowed_domains")
        expected_revision = body.get("expected_revision")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="enabled MUST be a boolean")
        if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
            raise HTTPException(status_code=400, detail="allowed_domains MUST be a string array")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise HTTPException(status_code=400, detail="expected_revision MUST be >= 0")
        try:
            await service.set_web_search_settings(
                actor_id=principal.oid,
                enabled=enabled,
                allowed_domains=tuple(domains),
                expected_revision=expected_revision,
            )
        except ModelSettingsConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(await service.projection(principal.oid, can_manage_web_search=True))

    return (
        Route("/models/settings", get_settings, methods=["GET"]),
        Route("/models/web-search-settings", put_web_search, methods=["PUT"]),
        Route("/me/model-preferences", put_preference, methods=["PUT"]),
    )


async def _read_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


def _record_revision(record: Mapping[str, Any] | None) -> int:
    if record is None or "revision" not in record:
        return 0
    revision = record.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise RuntimeError("stored narrator preference revision is invalid")
    return revision


def _normalize_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(item.strip().casefold().rstrip(".") for item in domains if item.strip())
    )
    if len(normalized) > 100:
        raise ValueError("allowed_domains MUST contain at most 100 hosts")
    invalid = [
        domain
        for domain in normalized
        if (
            "://" in domain
            or "/" in domain
            or ":" in domain
            or "*" in domain
            or not _valid_domain(domain)
        )
    ]
    if invalid:
        raise ValueError(
            "allowed_domains MUST contain hosts without schemes, paths, ports, or wildcards"
        )
    return normalized


def _valid_domain(domain: str) -> bool:
    if len(domain) > 253 or "." not in domain:
        return False
    return all(
        bool(label)
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in domain.split(".")
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
