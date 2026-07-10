"""Conversational-port introspection contract.

The pantheon's second port (``agent-pantheon.md`` 6.2) is a request-response
natural-language interface. Every agent answers questions about the data it
owns plus the code it owns (``owns_code_paths`` RAG), reachable through Bragi
for operators and for agent-to-agent (A2A) NL introspection.

This module holds the shared, LLM-free scaffolding both the base
:class:`~fdai.agents.base.Agent` and each concrete agent build on:

- :class:`IntrospectionResult` - the value an agent's ``introspect`` returns.
- :func:`is_action_intent` - the MUST-NOT-bypass guard (7.7): the
  conversational port may *describe* actions but never execute one; a request
  phrased as a command re-enters the typed pipeline instead of being answered.
- :func:`capability_facts` / :func:`capability_sentence` - the default
  self-description every agent can answer from its immutable ``AgentSpec``.

Rendering here is deterministic (no model call): a fork swaps in an LLM-backed
narrator over the same ``facts`` without changing this contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.agents.base import AgentSpec

#: Abstain reason emitted when a conversational request is actually a command.
#: The port answers questions; an action must re-enter the typed pipeline with
#: the operator as ``initiator_principal`` (agent-pantheon.md 7.7).
REQUIRES_TYPED_PIPELINE = "requires_typed_pipeline"

#: Abstain reason when the agent has no data for the question.
NO_DATA = "no_data"


@dataclass(frozen=True, slots=True)
class IntrospectionResult:
    """One agent's answer to a natural-language introspection request.

    ``answer`` is the rendered natural-language string (``None`` when the
    agent abstains). ``facts`` is the structured, machine-readable evidence
    the answer is grounded in - always present so an A2A caller can consume
    the data without parsing prose. ``abstain_reason`` is set only when
    ``answer`` is ``None``.
    """

    answer: str | None
    facts: dict[str, Any] = field(default_factory=dict)
    abstain_reason: str | None = None

    @classmethod
    def abstain(cls, reason: str, *, facts: dict[str, Any] | None = None) -> IntrospectionResult:
        return cls(answer=None, facts=facts or {}, abstain_reason=reason)


# ---------------------------------------------------------------------------
# MUST-NOT-bypass guard (agent-pantheon.md 7.7)
# ---------------------------------------------------------------------------

# Imperative verbs that denote a *mutation* request rather than a question.
# A conversational turn that starts with one of these is a command: the port
# refuses to execute and signals the caller to re-enter the typed pipeline.
_ACTION_VERBS: frozenset[str] = frozenset(
    {
        "restart",
        "reboot",
        "delete",
        "remove",
        "drop",
        "destroy",
        "scale",
        "resize",
        "failover",
        "remediate",
        "execute",
        "run",
        "apply",
        "deploy",
        "provision",
        "rollback",
        "revert",
        "approve",
        "reject",
        "disable",
        "enable",
        "create",
        "kill",
        "drain",
        "terminate",
        "mutate",
        "patch",
        "update",
        "set",
        "start",
        "stop",
        "promote",
        "retire",
        "override",
        "flush",
        "purge",
        "grant",
        "revoke",
    }
)

# Polite prefixes stripped before inspecting the leading verb, so
# "please restart vm-1" and "can you delete rg-x" are still caught.
_FILLER_PREFIX: frozenset[str] = frozenset(
    {"please", "can", "could", "would", "you", "kindly", "pls", "hey", "ok", "okay"}
)

_WORD_RE = re.compile(r"[a-z0-9-]+")


def is_action_intent(question: str) -> bool:
    """Return ``True`` when ``question`` is a mutation command, not a query.

    Deterministic and conservative-by-safety: a leading imperative verb
    (after stripping polite filler) means the request wants to *change*
    something, which the conversational port MUST NOT do itself
    (agent-pantheon.md 7.7). Interrogatives ("what/why/who/show/list/...")
    fall through as introspection.
    """
    tokens = _WORD_RE.findall(question.lower())
    for token in tokens:
        if token in _FILLER_PREFIX:
            continue
        return token in _ACTION_VERBS
    return False


def mentioned(question: str, candidates: Any) -> list[str]:
    """Return the ``candidates`` whose name appears as a token in ``question``.

    Case-insensitive whole-token match, used by concrete agents to scope an
    introspection answer to a resource / scope / id the operator named
    (e.g. "cost for rg-abc" -> the ``rg-abc`` scope). Order follows
    ``candidates`` for determinism.
    """
    tokens = {t for t in _WORD_RE.findall(question.lower())}
    return [c for c in candidates if str(c).lower() in tokens]


# ---------------------------------------------------------------------------
# Default capability self-description (every agent, from its AgentSpec)
# ---------------------------------------------------------------------------


def capability_facts(spec: AgentSpec) -> dict[str, Any]:
    """Structured self-description derived from an agent's immutable spec."""
    return {
        "agent": spec.name,
        "layer": spec.layer.value,
        "reports_to": spec.reports_to,
        "owns": list(spec.owns),
        "question_domains": list(spec.question_domains),
        "subscribes": list(spec.subscribes),
        "publishes": list(spec.publishes),
        "hot_path_llm": spec.hot_path_llm,
        "off_path_llm": spec.off_path_llm,
        "hard_dependency": spec.hard_dependency,
    }


def capability_sentence(spec: AgentSpec) -> str:
    """Render a deterministic one-line self-description from a spec."""
    owns = ", ".join(spec.owns) if spec.owns else "no object types"
    domains = ", ".join(spec.question_domains) if spec.question_domains else "none"
    return (
        f"I am {spec.name}, a {spec.layer.value}-layer agent. "
        f"I own {owns}. I can answer questions about: {domains}."
    )


__all__ = [
    "IntrospectionResult",
    "REQUIRES_TYPED_PIPELINE",
    "NO_DATA",
    "is_action_intent",
    "mentioned",
    "capability_facts",
    "capability_sentence",
]
