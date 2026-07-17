"""Bounded authenticated HTTP ingress routes for conversation channels."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.delivery.channels.slack import SlackBotChannel
from fdai.delivery.channels.teams import TeamsBotChannel
from fdai.delivery.channels.teams_auth import (
    BotServiceIdentity,
    service_identity_matches_activity,
)

TeamsActivityAuthenticator = Callable[[str], Awaitable[bool | BotServiceIdentity | None]]
TeamsPrincipalResolver = Callable[[Mapping[str, object]], Awaitable[str | None]]


def make_slack_events_route(
    *,
    channel: SlackBotChannel,
    path: str = "/channels/slack/events",
) -> Route:
    async def endpoint(request: Request) -> Response:
        rejected = _content_length_rejection(request, channel.max_body_bytes)
        if rejected is not None:
            return rejected
        body = await request.body()
        result = await channel.accept(headers=dict(request.headers), body=body)
        if result.challenge is not None:
            return JSONResponse({"challenge": result.challenge})
        if not result.accepted:
            status = 401 if result.reason == "invalid signature" else 400
            return JSONResponse({"accepted": False, "reason": result.reason}, status_code=status)
        return JSONResponse({"accepted": True}, status_code=202)

    return Route(path, endpoint, methods=["POST"])


def make_teams_activity_route(
    *,
    channel: TeamsBotChannel,
    authenticate: TeamsActivityAuthenticator,
    resolve_principal: TeamsPrincipalResolver | None = None,
    path: str = "/channels/teams/activities",
    max_body_bytes: int = 256 * 1024,
) -> Route:
    if max_body_bytes < 1:
        raise ValueError("Teams activity body cap MUST be positive")

    async def endpoint(request: Request) -> Response:
        rejected = _content_length_rejection(request, max_body_bytes)
        if rejected is not None:
            return rejected
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse({"accepted": False, "reason": "unauthorized"}, status_code=401)
        service_identity = await authenticate(authorization[7:])
        if not service_identity:
            return JSONResponse({"accepted": False, "reason": "unauthorized"}, status_code=401)
        body = await request.body()
        if len(body) > max_body_bytes:
            return JSONResponse({"accepted": False, "reason": "body too large"}, status_code=413)
        try:
            activity = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"accepted": False, "reason": "invalid JSON"}, status_code=400)
        if not isinstance(activity, Mapping):
            return JSONResponse({"accepted": False, "reason": "invalid activity"}, status_code=400)
        if isinstance(
            service_identity, BotServiceIdentity
        ) and not service_identity_matches_activity(service_identity, activity):
            return JSONResponse({"accepted": False, "reason": "unauthorized"}, status_code=401)
        principal_id = None
        if resolve_principal is not None:
            principal_id = await resolve_principal(activity)
            if principal_id is None:
                return JSONResponse(
                    {"accepted": False, "reason": "principal not allowed"},
                    status_code=403,
                )
        result = await channel.accept_authenticated_activity(
            activity=activity,
            principal_id=principal_id,
        )
        if not result.accepted:
            return JSONResponse({"accepted": False, "reason": result.reason}, status_code=400)
        return JSONResponse({"accepted": True}, status_code=202)

    return Route(path, endpoint, methods=["POST"])


def _content_length_rejection(request: Request, maximum: int) -> JSONResponse | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        if int(raw) <= maximum:
            return None
    except ValueError:
        return JSONResponse({"accepted": False, "reason": "invalid length"}, status_code=400)
    return JSONResponse({"accepted": False, "reason": "body too large"}, status_code=413)


__all__ = [
    "TeamsActivityAuthenticator",
    "TeamsPrincipalResolver",
    "make_slack_events_route",
    "make_teams_activity_route",
]
