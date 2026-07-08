"""Saga - Auditor (Wave 2 behavior).

Saga is the append-only audit principal and executor of
`governance.escalate-to-github-issue`. Every terminal state a topic
emits (verdict, action-run, rollback, approval, security-event) is
recorded on the audit chain by Saga's typed handler.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fdai.agents.adapters import (
    AuditEntry,
    InMemoryAuditChain,
    InMemoryGithubIssueAdapter,
    InMemoryStateStore,
)
from fdai.agents.base import Agent
from fdai.agents.pantheon import _SAGA

_FINGERPRINT_BUCKET = "issue_fingerprint_index"


class Saga(Agent):
    """Wave-2 Saga: audit chain + GitHub Issue dedup."""

    def __init__(
        self,
        *,
        audit_chain: InMemoryAuditChain | None = None,
        state_store: InMemoryStateStore | None = None,
        github: InMemoryGithubIssueAdapter | None = None,
    ) -> None:
        super().__init__(spec=_SAGA)
        self.audit_chain = audit_chain or InMemoryAuditChain()
        self.state_store = state_store or InMemoryStateStore()
        self.github = github or InMemoryGithubIssueAdapter()

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        principal = str(payload.get("producer_principal", "unknown"))
        correlation_id = str(payload.get("correlation_id", ""))
        self.audit_chain.append(
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload=payload,
        )

    def escalate_to_github_issue(
        self,
        *,
        fingerprint: str,
        emitting_agent: str,
        intent_category: str,
        failure_reason_code: str,
        correlation_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = f"[{intent_category}] {emitting_agent} handoff"
        body_lines = [
            f"Fingerprint: `{fingerprint}`",
            f"Emitting agent: {emitting_agent}",
            f"Failure reason: {failure_reason_code}",
            f"Correlation id: {correlation_id}",
        ]
        if context:
            for k, v in sorted(context.items()):
                body_lines.append(f"- {k}: {v}")
        body = "\n".join(body_lines)

        issue, created = self.github.create_or_comment(
            fingerprint=fingerprint,
            title=title,
            body=body,
        )
        self.state_store.put(
            _FINGERPRINT_BUCKET,
            fingerprint,
            {
                "issue_number": issue.number,
                "occurrence_count": 1 + len(issue.comments),
                "last_correlation_id": correlation_id,
            },
        )
        self.audit_chain.append(
            principal="Saga",
            topic="object.issue",
            correlation_id=correlation_id,
            payload={
                "fingerprint": fingerprint,
                "issue_number": issue.number,
                "created": created,
            },
        )
        return {
            "issue_number": issue.number,
            "created": created,
            "occurrence_count": 1 + len(issue.comments),
        }

    def close_issue(self, *, fingerprint: str, closed_by_pr: str) -> None:
        self.github.close(fingerprint, closed_by_pr=closed_by_pr)
        state = self.state_store.get(_FINGERPRINT_BUCKET, fingerprint) or {}
        state["closed_by_pr"] = closed_by_pr
        self.state_store.put(_FINGERPRINT_BUCKET, fingerprint, state)

    def replay_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return self.audit_chain.entries_for_correlation(correlation_id)


def compute_fingerprint(
    *,
    intent_category: str,
    resource_type: str,
    normalized_selector: str,
    primary_agent: str,
    failure_reason_code: str,
) -> str:
    """Deterministic fingerprint per `agent-pantheon.md` \u00a76.4."""
    material = "|".join(
        (
            intent_category,
            resource_type,
            normalized_selector,
            primary_agent,
            failure_reason_code,
        )
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()  # noqa: S324 - fingerprint id, not security


__all__ = ["Saga", "compute_fingerprint"]
