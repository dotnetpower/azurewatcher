"""Jira implementation of the
:class:`~fdai.shared.providers.tool.ToolExecutor` seam.

Design contract: ``docs/roadmap/decisioning/execution-model.md § 5.6 Tool call``.
A ticketing :class:`~fdai.shared.providers.tool.ToolExecutor` that maps a
``tool.*`` ActionType onto a Jira "create issue" call over the Jira Cloud
REST API. It mirrors :mod:`fdai.delivery.mcp.executor`: the upstream Day-1
binding stays
:class:`~fdai.shared.providers.testing.tool.RecordingToolExecutor`, so
dev / local-fake runs never make a network call. ``core/`` only knows the
``ToolExecutor`` Protocol - this module is bound at the composition root by
a fork.

Safety semantics (identical to the MCP executor)
------------------------------------------------

- **Shadow is a real no-op.** A shadow request MUST NOT create a ticket
  and MUST NOT write the idempotency ledger - it returns a planned
  receipt describing what *would* run. An ActionType absent from
  ``tool_map`` fails closed with a ``config`` :class:`ToolError` even in
  shadow, so a mis-wired map surfaces before enforce.
- **Enforce requires the label.** An ``enforce`` request without the
  ``enforce`` label raises :class:`ToolPromotionError`.
- **Idempotent by key.** A prior successful ledger entry short-circuits to
  :attr:`ToolCallOutcome.ALREADY_APPLIED`; no duplicate ticket is opened.
  This is the anti-duplicate-ticket guard - a redelivered event MUST NOT
  spam a Jira project.
- **Fail-closed.** A transport error or non-2xx response raises
  :class:`ToolError`; the caller writes exactly one audit entry.

Auth: Jira Cloud uses HTTP Basic auth with an account email plus an API
token. The email is non-secret config; the API token is resolved through
an injected
:class:`~fdai.shared.providers.secret_provider.SecretProvider` at call
time (never cached, never logged, never surfaced in an error message).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

import httpx

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.secret_provider import SecretProvider
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolPromotionError,
)

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_ISSUE_TYPE: Final[str] = "Task"
_CREATE_ISSUE_PATH: Final[str] = "/rest/api/3/issue"


@runtime_checkable
class JiraIdempotencyLedger(Protocol):
    """Durable dedupe store for Jira issue creation.

    Kept minimal and async so a fork can back it with Postgres / Redis.
    The in-process :class:`InMemoryJiraLedger` default survives one process
    only; a real deployment injects a persistent implementation so a
    retried enforce call after a restart still short-circuits and no
    duplicate ticket is opened.
    """

    async def seen(self, key: str) -> str | None:
        """Return the recorded issue key for ``key`` or ``None``."""
        ...

    async def record(self, key: str, receipt_ref: str) -> None:
        """Persist a successful issue creation keyed by ``key``."""
        ...


class InMemoryJiraLedger:
    """Per-process ledger - the upstream default when none is injected."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def seen(self, key: str) -> str | None:
        return self._store.get(key)

    async def record(self, key: str, receipt_ref: str) -> None:
        self._store[key] = receipt_ref


@dataclass(frozen=True, slots=True)
class JiraToolExecutorConfig:
    """Configuration for the Jira ticketing executor.

    ``tool_map`` binds each CSP-neutral ``tool.*`` ActionType name to a
    Jira project key (e.g. ``{"tool.open-incident-ticket": "OPS"}``). A
    dispatch whose ActionType is absent fails closed with
    :class:`ToolError` (kind ``config``).

    ``account_email`` is the Basic-auth username (non-secret).
    ``api_token_secret`` is the *name* looked up on the injected
    :class:`SecretProvider`; the raw token NEVER lives in the config.
    """

    base_url: str
    account_email: str
    api_token_secret: str
    tool_map: Mapping[str, str]
    default_issue_type: str = _DEFAULT_ISSUE_TYPE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("JiraToolExecutorConfig.base_url MUST be non-empty")
        # Jira Cloud Basic auth sends the API token on every request; a
        # plaintext endpoint would leak it on the wire.
        if not self.base_url.lower().startswith("https://"):
            raise ValueError(
                "JiraToolExecutorConfig.base_url MUST use https:// - Basic "
                "auth sends the API token on every request "
                f"(got {self.base_url!r})"
            )
        if not self.account_email:
            raise ValueError("JiraToolExecutorConfig.account_email MUST be non-empty")
        if not self.api_token_secret:
            raise ValueError("JiraToolExecutorConfig.api_token_secret MUST be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("JiraToolExecutorConfig.timeout_seconds MUST be positive")


class JiraToolExecutor:
    """Create a Jira issue for one ``tool.*`` ActionType dispatch."""

    def __init__(
        self,
        *,
        config: JiraToolExecutorConfig,
        http_client: httpx.AsyncClient,
        secrets: SecretProvider,
        ledger: JiraIdempotencyLedger | None = None,
    ) -> None:
        self._config: Final[JiraToolExecutorConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._secrets: Final[SecretProvider] = secrets
        self._ledger: Final[JiraIdempotencyLedger] = ledger or InMemoryJiraLedger()

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        # 1. Promotion check - enforce needs the explicit label.
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise ToolPromotionError(
                "enforce-mode Jira tool call requires an explicit 'enforce' "
                "label (execution-model.md 5.6 promotion contract)"
            )

        # 2. Idempotency - a prior success wins, no duplicate ticket.
        prior_ref = await self._ledger.seen(request.idempotency_key)
        if prior_ref is not None:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.ALREADY_APPLIED,
                receipt_ref=prior_ref,
                already_existed=True,
                detail="idempotency ledger hit",
            )

        project_key = self._config.tool_map.get(request.action_type_name)
        if project_key is None:
            raise ToolError(
                kind="config",
                message=(f"no Jira project mapped for ActionType {request.action_type_name!r}"),
            )

        # 3. Shadow is a real no-op: never create, never record the ledger.
        if request.mode is Mode.SHADOW:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref=f"shadow:{project_key}:{request.idempotency_key}",
                detail=(f"shadow: would open a Jira {project_key} issue (no side effect)"),
            )

        # 4. Enforce path - the real create-issue call.
        return await self._create_issue(request=request, project_key=project_key)

    async def _create_issue(self, *, request: ToolCallRequest, project_key: str) -> ToolCallReceipt:
        fields = self._build_fields(request=request, project_key=project_key)
        token = await self._secrets.get(self._config.api_token_secret)
        basic = base64.b64encode(f"{self._config.account_email}:{token}".encode()).decode("ascii")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {basic}",
        }

        url = f"{self._config.base_url.rstrip('/')}{_CREATE_ISSUE_PATH}"
        try:
            response = await self._http.post(
                url,
                headers=headers,
                content=json.dumps({"fields": fields}),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ToolError(
                kind="transport",
                message=f"Jira request failed for project {project_key!r}: {type(exc).__name__}",
            ) from exc

        if not response.is_success:
            snippet = response.text[:200].replace("\n", " ")
            raise ToolError(
                kind="http",
                message=(
                    f"Jira returned HTTP {response.status_code} for project "
                    f"{project_key!r}: {snippet!r}"
                ),
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolError(
                kind="protocol",
                message=f"Jira returned non-JSON for project {project_key!r}",
            ) from exc

        issue_key = _issue_key(payload)
        if issue_key is None:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.FAILED,
                receipt_ref=f"jira-error:{project_key}",
                rollback_succeeded=None,
                detail="Jira response missing an issue key",
            )

        await self._ledger.record(request.idempotency_key, issue_key)
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=issue_key,
            detail=f"opened Jira issue {issue_key}",
        )

    def _build_fields(self, *, request: ToolCallRequest, project_key: str) -> dict[str, Any]:
        args = request.arguments
        summary = str(args.get("summary") or f"FDAI: {request.action_type_name}")
        issue_type = str(args.get("issue_type") or self._config.default_issue_type)
        description_text = str(args.get("description") or "")
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary[:255],
            "issuetype": {"name": issue_type},
        }
        if description_text:
            # Jira Cloud v3 expects an Atlassian Document Format body.
            fields["description"] = _adf_paragraph(description_text)
        labels = args.get("labels")
        if isinstance(labels, (list, tuple)) and labels:
            # Jira labels cannot contain spaces; drop invalid ones rather
            # than fail the whole ticket.
            clean = [str(lbl) for lbl in labels if str(lbl) and " " not in str(lbl)]
            if clean:
                fields["labels"] = clean
        return fields


def _adf_paragraph(text: str) -> dict[str, Any]:
    """Wrap plain text in a minimal Atlassian Document Format doc."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _issue_key(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    key = payload.get("key")
    return str(key) if isinstance(key, str) and key else None


__all__ = [
    "InMemoryJiraLedger",
    "JiraIdempotencyLedger",
    "JiraToolExecutor",
    "JiraToolExecutorConfig",
]
