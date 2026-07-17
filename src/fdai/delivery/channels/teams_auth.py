"""Bot Framework service JWT and Teams user-principal binding."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient

_ISSUER: Final[str] = "https://api.botframework.com"
_JWKS_URI: Final[str] = "https://login.botframework.com/v1/.well-known/keys"
_ALGORITHMS: Final[tuple[str, ...]] = ("RS256",)
_LEEWAY_SECONDS: Final[int] = 60


class TeamsAuthenticationError(RuntimeError):
    """A Teams service token or user binding could not be trusted."""


class TeamsAuthConfigError(ValueError):
    """Teams authentication configuration is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class BotServiceIdentity:
    """Verified Bot Framework service identity bound to one service URL."""

    service_url: str


@dataclass(frozen=True, slots=True)
class BotFrameworkJwtAuthenticator:
    """Verify an incoming Bot Framework service JWT with cached JWKS."""

    jwks_client: PyJWKClient
    app_id: str
    issuer: str = _ISSUER
    algorithms: tuple[str, ...] = field(default=_ALGORITHMS)
    leeway_seconds: int = _LEEWAY_SECONDS

    async def __call__(self, token: str) -> BotServiceIdentity | None:
        try:
            return await asyncio.to_thread(self._verify, token)
        except TeamsAuthenticationError:
            return None

    def _verify(self, token: str) -> BotServiceIdentity:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.algorithms),
                audience=self.app_id,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "iss", "aud", "serviceurl"]},
            )
        except jwt.PyJWTError as exc:
            raise TeamsAuthenticationError(
                f"Bot Framework token verification failed: {type(exc).__name__}"
            ) from exc
        service_url = claims.get("serviceurl")
        if not isinstance(service_url, str) or not _valid_service_url(service_url):
            raise TeamsAuthenticationError("Bot Framework service URL claim is invalid")
        return BotServiceIdentity(service_url=service_url.rstrip("/"))

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> BotFrameworkJwtAuthenticator:
        env = environ if environ is not None else os.environ
        app_id = env.get("FDAI_TEAMS_BOT_APP_ID", "").strip()
        if not app_id or len(app_id) > 256:
            raise TeamsAuthConfigError("FDAI_TEAMS_BOT_APP_ID is required")
        issuer = env.get("FDAI_TEAMS_BOT_ISSUER", "").strip() or _ISSUER
        jwks_uri = env.get("FDAI_TEAMS_BOT_JWKS_URI", "").strip() or _JWKS_URI
        if not _valid_https_url(issuer) or not _valid_https_url(jwks_uri):
            raise TeamsAuthConfigError("Teams Bot issuer and JWKS URI MUST use HTTPS")
        return cls(
            jwks_client=PyJWKClient(
                jwks_uri,
                cache_keys=True,
                lifespan=3600,
                timeout=10,
            ),
            app_id=app_id,
            issuer=issuer,
        )


@dataclass(frozen=True, slots=True)
class TeamsPrincipalResolver:
    """Resolve same-tenant Teams AAD object ids to canonical FDAI principals."""

    tenant_id: str
    principal_bindings: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise TeamsAuthConfigError("Teams tenant id MUST NOT be empty")
        if not self.principal_bindings:
            raise TeamsAuthConfigError("Teams principal bindings MUST NOT be empty")
        if any(
            not key.strip() or not value.strip() for key, value in self.principal_bindings.items()
        ):
            raise TeamsAuthConfigError("Teams principal bindings MUST be non-empty")

    async def __call__(self, activity: Mapping[str, Any]) -> str | None:
        if activity.get("channelId") != "msteams":
            return None
        sender = activity.get("from")
        if not isinstance(sender, Mapping):
            return None
        object_id = sender.get("aadObjectId")
        tenant_id = _activity_tenant(activity)
        if not isinstance(object_id, str) or tenant_id != self.tenant_id:
            return None
        return self.principal_bindings.get(object_id)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> TeamsPrincipalResolver:
        env = environ if environ is not None else os.environ
        tenant_id = env.get("FDAI_TEAMS_TENANT_ID", "").strip()
        raw_bindings = env.get("FDAI_TEAMS_PRINCIPAL_BINDINGS_JSON", "").strip()
        if not tenant_id or not raw_bindings:
            raise TeamsAuthConfigError(
                "FDAI_TEAMS_TENANT_ID and FDAI_TEAMS_PRINCIPAL_BINDINGS_JSON are required"
            )
        try:
            parsed = json.loads(raw_bindings)
        except json.JSONDecodeError as exc:
            raise TeamsAuthConfigError("Teams principal bindings JSON is invalid") from exc
        if (
            not isinstance(parsed, dict)
            or not parsed
            or len(parsed) > 1000
            or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
            )
        ):
            raise TeamsAuthConfigError(
                "Teams principal bindings MUST be a bounded string-to-string object"
            )
        return cls(tenant_id=tenant_id, principal_bindings=parsed)


def service_identity_matches_activity(
    identity: BotServiceIdentity,
    activity: Mapping[str, Any],
) -> bool:
    service_url = activity.get("serviceUrl")
    return (
        activity.get("channelId") == "msteams"
        and isinstance(service_url, str)
        and _valid_service_url(service_url)
        and service_url.rstrip("/") == identity.service_url
    )


def _activity_tenant(activity: Mapping[str, Any]) -> str | None:
    conversation = activity.get("conversation")
    if isinstance(conversation, Mapping):
        tenant_id = conversation.get("tenantId")
        if isinstance(tenant_id, str) and tenant_id:
            return tenant_id
    channel_data = activity.get("channelData")
    tenant = channel_data.get("tenant") if isinstance(channel_data, Mapping) else None
    tenant_id = tenant.get("id") if isinstance(tenant, Mapping) else None
    return tenant_id if isinstance(tenant_id, str) and tenant_id else None


def _valid_service_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def _valid_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


__all__ = [
    "BotFrameworkJwtAuthenticator",
    "BotServiceIdentity",
    "TeamsAuthConfigError",
    "TeamsAuthenticationError",
    "TeamsPrincipalResolver",
    "service_identity_matches_activity",
]
