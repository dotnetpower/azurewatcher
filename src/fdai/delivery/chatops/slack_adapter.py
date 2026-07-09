"""Slack implementation of :class:`HilChannel` - Block Kit message + HMAC auth.

Realizes the ChatOps A1 (approval) contract for Slack. The adapter dispatches a
Block Kit message via an Incoming Webhook (P1 default) and mirrors the safety
posture of :mod:`fdai.delivery.chatops.teams_adapter`: HTTPS-only, fail-closed
on any non-2xx, defense-in-depth secret redaction, and an opaque ``approval_id``
carried on the interactive buttons (the decision endpoint re-verifies the
identity + action hash before honoring an APPROVE).

Design boundaries
-----------------

- ``core/`` never imports this module; it lives under ``delivery/chatops/`` and
  is bound at the composition root through the
  :class:`~fdai.shared.providers.hil_channel.HilChannel` Protocol seam.
- Webhook mode only. A signing secret (when supplied) attaches an
  ``X-FDAI-Signature`` HMAC over the request body, matching the Teams adapter's
  convention so a single fdai callback receiver verifies both. Slack's own
  request-signing is an inbound concern handled by that receiver, not here.
- HTTP transport is an injected :class:`httpx.AsyncClient`; tests hand it a
  client backed by :class:`httpx.MockTransport`.

Wire contract (P1 - Incoming Webhook)
-------------------------------------

- ``send`` -> ``POST {webhook_url}`` with a Block Kit body. Slack Incoming
  Webhooks answer ``200`` with the literal body ``ok``; any other status or
  body is a fail-closed error.
- ``poll`` -> no-op, always PENDING (the interactive callback that surfaces a
  click is delivered to ``fdai-api``, not polled here).

Safety invariants
-----------------

- **Fail-closed**: any non-2xx response, timeout, malformed body, or a body
  that is not ``ok`` raises :class:`HilChannelError`; the caller falls back to
  the persisted HIL queue and pages the operational lane.
- **Body redaction**: the rendered message is re-scanned for a small set of
  high-signal secret patterns and refused when a match is found.
- **Bounded error bodies**: the vendor error snippet is truncated before it is
  embedded in the raised error.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilDecision,
    HilResponse,
)

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
_DEFAULT_MAX_ERROR_BODY_BYTES: Final[int] = 512
_SIGNATURE_HEADER: Final[str] = "X-FDAI-Signature"
_TIMESTAMP_HEADER: Final[str] = "X-FDAI-Timestamp"
_SLACK_OK_BODY: Final[str] = "ok"

# Small, high-signal secret patterns re-checked before dispatch (defense in
# depth - the caller is expected to have redacted already).
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"SharedAccessKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
)


@dataclass(frozen=True, slots=True)
class SlackHilAdapterConfig:
    """Configuration for the Slack HIL adapter."""

    webhook_url: str
    """Slack Incoming Webhook URL. MUST be https://."""

    webhook_secret: str | None = None
    """Shared secret used to compute the ``X-FDAI-Signature`` HMAC over the
    outbound body, so the fdai callback receiver can verify provenance."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    """Per-HTTP-request timeout applied to ``send``."""

    max_error_body_bytes: int = _DEFAULT_MAX_ERROR_BODY_BYTES
    """Cap on the vendor error snippet embedded in :class:`HilChannelError`."""


class SlackHilAdapter(HilChannel):
    """Slack implementation of :class:`HilChannel` (Incoming Webhook mode)."""

    def __init__(
        self,
        *,
        config: SlackHilAdapterConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        if not config.webhook_url or not config.webhook_url.strip():
            raise ValueError("webhook_url MUST NOT be empty")
        if not config.webhook_url.startswith("https://"):
            # A Slack Incoming Webhook is always HTTPS; a misconfigured
            # http:// variant would leak the HMAC signature. Fail-closed at
            # construction rather than at first send.
            raise ValueError("webhook_url MUST use https:// scheme")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if config.max_error_body_bytes < 64:
            raise ValueError("max_error_body_bytes MUST be >= 64")
        self._config: Final[SlackHilAdapterConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client

    # ------------------------------------------------------------------
    # HilChannel Protocol
    # ------------------------------------------------------------------

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        message = _render_block_kit(request)
        payload = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")

        secret_hit = _scan_for_secrets(payload.decode("utf-8"))
        if secret_hit is not None:
            raise HilChannelError(
                f"message body matched a secret pattern ({secret_hit}); refusing to send",
                approval_id=request.approval_id,
            )

        headers = self._auth_headers(payload=payload)

        try:
            response = await self._http.post(
                self._config.webhook_url,
                content=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise HilChannelError(
                f"send request failed: {exc.__class__.__name__}",
                approval_id=request.approval_id,
            ) from exc

        if response.status_code >= 400:
            raise HilChannelError(
                f"send returned HTTP {response.status_code}: {self._trim(response.text)}",
                approval_id=request.approval_id,
                status_code=response.status_code,
            )
        # Slack Incoming Webhooks answer 200 with the literal body "ok".
        # Anything else (e.g. "invalid_payload", "channel_not_found") is a
        # fail-closed error even under a 200.
        if response.text.strip().lower() != _SLACK_OK_BODY:
            raise HilChannelError(
                f"send returned a non-ok body: {self._trim(response.text)}",
                approval_id=request.approval_id,
                status_code=response.status_code,
            )

        return HilApprovalReceipt(
            approval_id=request.approval_id,
            channel_ref=f"slack:{request.approval_id}",
            sent_at=datetime.now(tz=UTC),
        )

    async def poll(self, receipt: HilApprovalReceipt) -> HilResponse:
        # P1 posture - Incoming Webhook send-only. The interactive callback
        # is delivered to fdai-api, not polled here; surface PENDING so the
        # caller falls back to its persisted HIL queue.
        return HilResponse(
            approval_id=receipt.approval_id,
            decision=HilDecision.PENDING,
        )

    # ------------------------------------------------------------------
    # Response parser (public, static)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_response(payload: object) -> HilResponse:
        """Parse a Slack interactive-message callback payload.

        The fdai callback receiver hands the JSON ``payload`` of a Slack
        ``block_actions`` interaction here. The approve / reject button carries
        its ``value`` as ``"<action>:<approval_id>"``; the acting user is
        ``payload["user"]["id"]``. An unrecognized action or a missing
        ``approval_id`` maps to :data:`HilDecision.PENDING` so the caller keeps
        its state.

        Raises :class:`HilChannelError` when the payload is not a dict.
        """
        if not isinstance(payload, dict):
            raise HilChannelError(
                "callback payload is not a JSON object",
                approval_id="",
            )

        action, approval_id = _extract_action_value(payload)
        if not approval_id:
            raise HilChannelError(
                "callback payload is missing 'approval_id'",
                approval_id="",
            )

        decision: HilDecision
        if action == "approve":
            decision = HilDecision.APPROVE
        elif action == "reject":
            decision = HilDecision.REJECT
        elif action == "timeout":
            decision = HilDecision.TIMEOUT
        else:
            decision = HilDecision.PENDING

        approver_id = None
        user = payload.get("user")
        if isinstance(user, dict):
            uid = user.get("id")
            approver_id = uid if isinstance(uid, str) and uid else None

        reason_raw = payload.get("reason")
        reason = reason_raw if isinstance(reason_raw, str) and reason_raw else None
        if reason is not None and _scan_for_secrets(reason) is not None:
            reason = "[redacted]"

        return HilResponse(
            approval_id=approval_id,
            decision=decision,
            approver_id=approver_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _auth_headers(self, *, payload: bytes) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/plain",
        }
        if self._config.webhook_secret is not None:
            timestamp = str(int(datetime.now(tz=UTC).timestamp()))
            signature = _hmac_sha256(
                secret=self._config.webhook_secret,
                timestamp=timestamp,
                payload=payload,
            )
            headers[_TIMESTAMP_HEADER] = timestamp
            headers[_SIGNATURE_HEADER] = f"sha256={signature}"
        return headers

    def _trim(self, text: str) -> str:
        cap = self._config.max_error_body_bytes
        raw = text.replace("\n", " ")
        if len(raw) <= cap:
            return raw
        return raw[:cap] + "..."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hmac_sha256(*, secret: str, timestamp: str, payload: bytes) -> str:
    """Compute ``hex(HMAC-SHA256(secret, timestamp + "." + payload))``."""
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(payload)
    return mac.hexdigest()


def _scan_for_secrets(body: str) -> str | None:
    """Return the name of the first matching secret pattern, else ``None``."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(body):
            return pattern.pattern
    return None


def _extract_action_value(payload: dict[str, Any]) -> tuple[str, str]:
    """Return ``(action, approval_id)`` from a Slack ``block_actions`` payload.

    The button ``value`` is ``"<action>:<approval_id>"``. A top-level
    ``approval_id`` / ``action`` (already-normalized payload) is honored as a
    fallback so a receiver that pre-flattens the Slack shape also works.
    """
    actions = payload.get("actions")
    if isinstance(actions, list) and actions:
        first = actions[0]
        if isinstance(first, dict):
            value = first.get("value")
            if isinstance(value, str) and ":" in value:
                action, _, approval_id = value.partition(":")
                return action.lower(), approval_id
    # Fallback: an already-normalized payload.
    raw_action = payload.get("action")
    action = raw_action.lower() if isinstance(raw_action, str) else ""
    approval_id_raw = payload.get("approval_id")
    approval_id = approval_id_raw if isinstance(approval_id_raw, str) else ""
    return action, approval_id


def _render_block_kit(request: HilApprovalRequest) -> dict[str, Any]:
    """Render a Slack Block Kit message for one HIL approval request.

    Buttons carry ``value = "<action>:<approval_id>"``; the opaque
    ``approval_id`` alone cannot forge an approval (fdai-api re-verifies).
    """
    fields = [
        {"type": "mrkdwn", "text": f"*Action*\n{request.action_type}"},
        {"type": "mrkdwn", "text": f"*Target*\n{request.target_resource_ref}"},
        {"type": "mrkdwn", "text": f"*Blast radius*\n{request.blast_radius_summary}"},
        {"type": "mrkdwn", "text": f"*TTL*\n{request.ttl_seconds}s"},
    ]
    if request.rule_ids:
        fields.append({"type": "mrkdwn", "text": f"*Rules*\n{', '.join(request.rule_ids)}"})

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "FDAI HIL approval"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Action `{request.action_id}` requires approval.",
            },
        },
        {"type": "section", "fields": fields},
    ]
    if request.reasons:
        reason_lines = "\n".join(f"- {r}" for r in request.reasons)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Reasons*\n{reason_lines}"},
            }
        )
    blocks.append(
        {
            "type": "actions",
            "block_id": f"fdai-hil:{request.approval_id}",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "value": f"approve:{request.approval_id}",
                    "action_id": "fdai-hil-approve",
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "value": f"reject:{request.approval_id}",
                    "action_id": "fdai-hil-reject",
                },
            ],
        }
    )
    return {"text": "FDAI HIL approval request", "blocks": blocks}


__all__ = ["SlackHilAdapter", "SlackHilAdapterConfig"]
