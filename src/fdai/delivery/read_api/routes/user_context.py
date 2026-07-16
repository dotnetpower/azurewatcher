"""Principal-scoped user context, policy, and proactive briefing routes."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.briefing import OpeningBriefingService, next_cron_run
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.shared.providers.briefing import (
    BriefingConflictError,
    BriefingDeliveryMode,
    BriefingKind,
    BriefingRunStore,
    BriefingSpec,
    BriefingSubscription,
    BriefingSubscriptionStore,
    ConversationPolicyKind,
    ConversationPolicyRecord,
    ConversationPolicyStore,
)
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    UserContextConflictError,
    UserMemoryCategory,
    UserMemoryFact,
    UserMemoryStore,
    UserPreferenceRecord,
    UserPreferenceStore,
)

AuthorizeFn = Callable[[Request], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class UserContextRoutesConfig:
    conversations: ConversationHistoryStore
    preferences: UserPreferenceStore
    memories: UserMemoryStore
    policies: ConversationPolicyStore
    subscriptions: BriefingSubscriptionStore
    runs: BriefingRunStore
    opening_briefing: OpeningBriefingService
    ontology_projector: UserContextOntologyProjector | None = None


def make_user_context_routes(
    *, config: UserContextRoutesConfig, authorize: AuthorizeFn
) -> tuple[Route, ...]:
    async def context(request: Request) -> Response:
        principal_id = await authorize(request)
        now = datetime.now(tz=UTC)
        preference = await config.preferences.get(principal_id=principal_id)
        memories = await config.memories.list_active(principal_id=principal_id, now=now)
        policies = await config.policies.list_for_principal(principal_id=principal_id)
        subscriptions = await config.subscriptions.list_for_principal(principal_id=principal_id)
        runs = await config.runs.list_for_principal(principal_id=principal_id, limit=50)
        conversations = await config.conversations.list_conversations(
            principal_id=principal_id, limit=50
        )
        conversation_views: list[dict[str, Any]] = []
        for conversation in conversations:
            turns = await config.conversations.list_turns(
                principal_id=principal_id,
                conversation_id=conversation.conversation_id,
                limit=200,
            )
            latest_operator_turn = next(
                (turn for turn in reversed(turns) if turn.role.value == "operator"),
                None,
            )
            conversation_views.append(
                {
                    **_json(conversation),
                    "latest_operator_turn_id": (
                        latest_operator_turn.turn_id if latest_operator_turn else None
                    ),
                }
            )
        return JSONResponse(
            {
                "preference": _json(preference) if preference else None,
                "memories": [_json(item) for item in memories],
                "policies": [_json(item) for item in policies],
                "subscriptions": [_json(item) for item in subscriptions],
                "briefing_runs": [_json(item) for item in runs],
                "conversations": conversation_views,
            }
        )

    async def put_preference(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _body(request)
        expected = _optional_int(body, "expected_revision")
        try:
            record = UserPreferenceRecord(
                principal_id=principal_id,
                locale=str(body.get("locale") or "en"),
                verbosity=str(body.get("verbosity") or "concise"),
                timezone=_optional_text(body, "timezone"),
                share_with_learner=bool(body.get("share_with_learner", False)),
                updated_at=datetime.now(tz=UTC),
            )
            stored = await config.preferences.put(record, expected_revision=expected)
            if config.ontology_projector is not None:
                await config.ontology_projector.project_preference(stored)
        except UserContextConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored))

    async def conversation_turns(request: Request) -> Response:
        principal_id = await authorize(request)
        conversation_id = request.path_params["conversation_id"]
        conversation = await config.conversations.get_conversation(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        limit_raw = request.query_params.get("limit", "200")
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="limit MUST be an integer") from exc
        if not 1 <= limit <= 1000:
            raise HTTPException(status_code=400, detail="limit MUST be in [1, 1000]")
        turns = await config.conversations.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=limit,
        )
        return JSONResponse({"turns": [_json(turn) for turn in turns]})

    async def delete_conversation(request: Request) -> Response:
        principal_id = await authorize(request)
        conversation_id = request.path_params["conversation_id"]
        turns = await config.conversations.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=1000,
        )
        deleted = await config.conversations.delete_conversation(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        if deleted and config.ontology_projector is not None:
            for turn in turns:
                await config.ontology_projector.delete(f"turn:{principal_id}:{turn.turn_id}")
            await config.ontology_projector.delete(f"conversation:{principal_id}:{conversation_id}")
        return Response(status_code=204 if deleted else 404)

    async def create_memory(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        conversation_id = _required_text(body, "conversation_id")
        source_turn_id = _required_text(body, "source_turn_id")
        turns = await config.conversations.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=1000,
        )
        if not any(turn.turn_id == source_turn_id for turn in turns):
            raise HTTPException(status_code=404, detail="source turn not found")
        now = datetime.now(tz=UTC)
        category_raw = _required_text(body, "category")
        try:
            category = UserMemoryCategory(category_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid memory category") from exc
        try:
            fact = UserMemoryFact(
                memory_id=f"memory-{uuid4().hex}",
                principal_id=principal_id,
                category=category,
                body=_required_text(body, "body"),
                source_turn_id=source_turn_id,
                consented_at=now,
                created_at=now,
                expires_at=_optional_datetime(body, "expires_at"),
            )
            stored = await config.memories.create(fact)
            if config.ontology_projector is not None:
                await config.ontology_projector.project_memory(stored)
        except UserContextConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored), status_code=201)

    async def delete_memory(request: Request) -> Response:
        principal_id = await authorize(request)
        deleted = await config.memories.delete(
            principal_id=principal_id,
            memory_id=request.path_params["memory_id"],
        )
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(
                f"memory:{principal_id}:{request.path_params['memory_id']}"
            )
        return Response(status_code=204 if deleted else 404)

    async def put_policy(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        try:
            kind = ConversationPolicyKind(_required_text(body, "kind"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid policy kind") from exc
        briefing_spec = _briefing_spec(body.get("briefing_spec"))
        defaults = body.get("response_defaults", {})
        if not isinstance(defaults, Mapping):
            raise HTTPException(status_code=400, detail="response_defaults MUST be an object")
        try:
            record = ConversationPolicyRecord(
                policy_id=_required_text(body, "policy_id"),
                principal_id=principal_id,
                kind=kind,
                enabled=bool(body.get("enabled", True)),
                revision=0,
                confirmed_at=datetime.now(tz=UTC),
                source_turn_id=_required_text(body, "source_turn_id"),
                briefing_spec=briefing_spec,
                response_defaults={str(key): str(value) for key, value in defaults.items()},
            )
            stored = await config.policies.put(
                record,
                expected_revision=_optional_int(body, "expected_revision"),
            )
            if config.ontology_projector is not None:
                await config.ontology_projector.project_policy(stored)
        except BriefingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored))

    async def delete_policy(request: Request) -> Response:
        principal_id = await authorize(request)
        policy_id = request.path_params["policy_id"]
        deleted = await config.policies.delete(
            principal_id=principal_id,
            policy_id=policy_id,
        )
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(f"policy:{principal_id}:{policy_id}")
        return Response(status_code=204 if deleted else 404)

    async def create_subscription(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _confirmed_body(request)
        now = datetime.now(tz=UTC)
        cron_expression = _required_text(body, "cron_expression")
        timezone = _required_text(body, "timezone")
        modes_raw = body.get("delivery_modes", [BriefingDeliveryMode.IN_APP.value])
        if not isinstance(modes_raw, list):
            raise HTTPException(status_code=400, detail="delivery_modes MUST be a list")
        try:
            modes = tuple(BriefingDeliveryMode(str(item)) for item in modes_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid delivery mode") from exc
        if any(mode is not BriefingDeliveryMode.IN_APP for mode in modes):
            raise HTTPException(
                status_code=400,
                detail="only in_app briefing delivery is currently supported",
            )
        try:
            record = BriefingSubscription(
                subscription_id=f"briefing-{uuid4().hex}",
                principal_id=principal_id,
                name=_required_text(body, "name"),
                spec=_briefing_spec(body.get("spec")) or BriefingSpec(),
                cron_expression=cron_expression,
                timezone=timezone,
                delivery_modes=modes,
                enabled=True,
                next_run_at=next_cron_run(cron_expression, timezone, after=now),
                created_at=now,
                channel_binding_ref=_optional_text(body, "channel_binding_ref"),
                max_lateness_seconds=int(body.get("max_lateness_seconds", 3600)),
            )
            stored = await config.subscriptions.create(record)
            if config.ontology_projector is not None:
                await config.ontology_projector.project_subscription(stored)
        except BriefingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_json(stored), status_code=201)

    async def delete_subscription(request: Request) -> Response:
        principal_id = await authorize(request)
        deleted = await config.subscriptions.delete(
            principal_id=principal_id,
            subscription_id=request.path_params["subscription_id"],
        )
        if deleted and config.ontology_projector is not None:
            await config.ontology_projector.delete(
                f"briefing-subscription:{principal_id}:{request.path_params['subscription_id']}"
            )
        return Response(status_code=204 if deleted else 404)

    async def opening_briefing(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _body(request)
        run = await config.opening_briefing.open(
            principal_id=principal_id,
            conversation_id=_required_text(body, "conversation_id"),
        )
        if run is not None and config.ontology_projector is not None:
            await config.ontology_projector.project_briefing_run(run)
        return JSONResponse({"briefing": _json(run) if run else None})

    return (
        Route("/me/context", context, methods=["GET"]),
        Route(
            "/me/conversations/{conversation_id:str}/turns",
            conversation_turns,
            methods=["GET"],
        ),
        Route(
            "/me/conversations/{conversation_id:str}",
            delete_conversation,
            methods=["DELETE"],
        ),
        Route("/me/preferences", put_preference, methods=["PUT"]),
        Route("/me/memories", create_memory, methods=["POST"]),
        Route("/me/memories/{memory_id:str}", delete_memory, methods=["DELETE"]),
        Route("/me/policies", put_policy, methods=["PUT"]),
        Route("/me/policies/{policy_id:str}", delete_policy, methods=["DELETE"]),
        Route("/me/briefing-subscriptions", create_subscription, methods=["POST"]),
        Route(
            "/me/briefing-subscriptions/{subscription_id:str}",
            delete_subscription,
            methods=["DELETE"],
        ),
        Route("/me/opening-briefing", opening_briefing, methods=["POST"]),
    )


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > 64 * 1024:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    value.pop("principal_id", None)
    value.pop("user_id", None)
    return value


async def _confirmed_body(request: Request) -> dict[str, Any]:
    body = await _body(request)
    if body.get("confirmed") is not True:
        raise HTTPException(status_code=409, detail="explicit confirmation is required")
    return body


def _briefing_spec(raw: object) -> BriefingSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise HTTPException(status_code=400, detail="briefing spec MUST be an object")
    try:
        return BriefingSpec(
            kind=BriefingKind(str(raw.get("kind", BriefingKind.MAJOR_ISSUES.value))),
            lookback_seconds=int(raw.get("lookback_seconds", 86_400)),
            minimum_severity=str(raw.get("minimum_severity", "high")),
            categories=tuple(str(item) for item in raw.get("categories", ())),
            max_items=int(raw.get("max_items", 5)),
            include_pending_approvals=bool(raw.get("include_pending_approvals", True)),
            include_failed_actions=bool(raw.get("include_failed_actions", True)),
            scope_ref=(str(raw["scope_ref"]) if raw.get("scope_ref") else None),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid briefing spec") from exc


def _json(value: Any) -> Any:
    raw = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    return json.loads(json.dumps(raw, default=lambda item: getattr(item, "value", str(item))))


def _required_text(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_text(body: Mapping[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_int(body: Mapping[str, Any], key: str) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} MUST be an integer")
    return value


def _optional_datetime(body: Mapping[str, Any], key: str) -> datetime | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} MUST be ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{key} MUST be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail=f"{key} MUST include timezone")
    return parsed


__all__ = ["UserContextRoutesConfig", "make_user_context_routes"]
