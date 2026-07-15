"""Bragi - Narrator (Wave 4 behavior).

Bragi is the operator conversational port. It routes NL queries to a
primary agent using a deterministic scoring model built on
:pyattr:`AgentSpec.question_domains`, aggregates typed responses, and
renders a natural-language answer.

Wave 4 keeps the LLM off the hot path: routing is T0 keyword + T1
embedding-similarity (with the T1 similarity implementation stubbed
deterministically until an embedding provider lands). The T2 LLM
fallback for intent classification and the multi-turn context window
integrate with the seams here but are exercised only in the
conversational-port smoke tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    is_action_intent,
    leading_verb,
)
from fdai.agents._framework.pantheon import _BRAGI, PANTHEON_NAMES, PANTHEON_SPECS
from fdai.core.rbac.roles import Capability, Role, has_capability

_LOG = logging.getLogger(__name__)

AnswerFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

#: A proposal sink accepts one raw operator ActionProposal and hands it to the
#: typed pipeline (the composition root wires this to ``Huginn.ingest`` - the
#: sole writer of ``object.event``). Returns the normalized event payload, or
#: ``None`` when the collector deduplicated it. Bragi NEVER calls an executor
#: (agent-pantheon.md 7.7); it only submits through this sink.
ProposalSink = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

#: Deterministic verb -> ActionType mapping for operator conversational
#: requests (Wave 4, LLM-free). The verb is the leading imperative token that
#: :func:`~fdai.agents.introspection.is_action_intent` already recognised; a
#: verb with no mapping abstains rather than guessing an action.
_INTENT_ACTION: dict[str, str] = {
    "restart": "ops.restart-service",
    "reboot": "ops.restart-service",
    "failover": "ops.failover-primary",
    "delete": "remediate.delete-storage",
    "destroy": "remediate.delete-storage",
    "drop": "remediate.delete-storage",
    "encrypt": "remediate.enable-encryption",
}

#: Bounds on operator-supplied values that ride into a proposal, and on the
#: in-memory maps a long-lived Bragi accumulates, so a conversational port that
#: runs for weeks cannot leak one entry per session / correlation forever or let
#: one large value bloat the pipeline + audit.
_MAX_QUESTION_CHARS = 2_000
_MAX_RESOURCE_CHARS = 200
_MAX_SESSION_CHARS = 200
_MAX_SESSIONS = 1_000
_MAX_PROGRESS_KEYS = 5_000
#: Cap on progress steps retained per correlation. A pipeline has a handful of
#: lifecycle states, but at-least-once redelivery (or a chatty retry) could
#: append without limit, so the per-correlation list is bounded too - not just
#: the key count.
_MAX_PROGRESS_STEPS = 64
_MAX_CONTRIBUTORS = 3
_CONTRIBUTOR_TIMEOUT_SECONDS = 2.0


def _evict_oldest(mapping: dict[str, Any], cap: int, *, keep: str | None = None) -> None:
    """Bound ``mapping`` to ``cap`` entries, dropping oldest-first (insertion
    order), never evicting ``keep`` (the entry currently being written)."""
    while len(mapping) > cap:
        for key in mapping:
            if key != keep:
                del mapping[key]
                break
        else:  # only `keep` remains - nothing more to drop
            break


#: Entry RBAC gate for execute-class conversational requests. A console
#: session's Entra role is mapped to the canonical capability matrix
#: (:mod:`fdai.core.rbac.roles`) and MUST carry ``AUTHOR_DRAFT_PR`` to submit an
#: action - the SAME capability the HTTP console-action route requires, so the
#: two entry surfaces never drift. In particular ``BreakGlass`` is hard-isolated
#: (NOT a superset of Owner) and does NOT carry ``AUTHOR_DRAFT_PR``, so it cannot
#: submit a normal action from either surface. Refused before the proposal
#: enters the pipeline (defense-in-depth with Forseti's principal-level RBAC
#: deny).
_ROLE_BY_NAME: dict[str, Role] = {role.value.lower(): role for role in Role}
#: The capability an operator MUST hold to submit an action proposal. Same
#: capability as ``console_action._SUBMIT_CAPABILITY`` (single source of truth in
#: the RBAC matrix), so the conversational and HTTP entry gates cannot diverge.
_SUBMIT_CAPABILITY = Capability.AUTHOR_DRAFT_PR


@dataclass
class RoutingDecision:
    primary_agent: str | None
    scores: dict[str, float]
    tie_break: str | None
    contributors: tuple[str, ...] = ()


@dataclass
class Turn:
    turn_index: int
    question: str
    primary_agent: str | None
    answer: dict[str, Any]
    decision: RoutingDecision


@dataclass
class ConversationSession:
    session_id: str
    user_id: str
    turns: list[Turn] = field(default_factory=list)


_PANTHEON_PRECEDENCE = {
    "governance": 0,
    "pipeline": 1,
    "domain": 2,
}


class Bragi(Agent):
    """Wave-4 Bragi: routing + orchestration + session tracker."""

    def __init__(self) -> None:
        super().__init__(spec=_BRAGI)
        self._sessions: dict[str, ConversationSession] = {}
        self._agent_responders: dict[str, AnswerFn] = {}
        self._proposal_sink: ProposalSink | None = None
        # Per-correlation pipeline progress, appended as verdict / action-run
        # states arrive on the typed port, so an operator can be told where
        # their submitted action is (submitted -> verdicted -> hil_pending ->
        # executing -> succeeded / denied). Bounded both ways: the key count
        # by _evict_oldest (_MAX_PROGRESS_KEYS) and each list's length by
        # _MAX_PROGRESS_STEPS, with redelivered steps deduped.
        self._progress: dict[str, list[dict[str, Any]]] = {}

    # ---- registration --------------------------------------------------

    def register_responder(self, agent_name: str, fn: AnswerFn) -> None:
        self._agent_responders[agent_name] = fn

    def register_proposal_sink(self, fn: ProposalSink) -> None:
        """Wire the typed-pipeline entry (composition root binds Huginn.ingest).

        Without a sink, an action request falls back to the
        ``requires_typed_pipeline`` signal (no pipeline available) so behavior
        is unchanged where the pantheon is not wired.
        """
        self._proposal_sink = fn

    # ---- action proposal (conversational-port re-entry, 7.7) -----------

    async def submit_action_proposal(
        self, *, session_id: str, user_id: str, question: str, initiator_role: str | None = None
    ) -> dict[str, Any]:
        """Translate an operator command into a typed ActionProposal.

        Builds a proposal whose ``initiator_principal`` is the operator (never
        Bragi), names the ActionType the leading verb maps to, and hands it to
        the typed pipeline through the wired sink (Huginn -> Forseti -> Var ->
        Thor). Returns a status envelope with the ``correlation_id`` the
        operator can track; it NEVER executes the action itself.

        When ``initiator_role`` is supplied (the console session's Entra role),
        an entry RBAC gate refuses a request below the execute floor
        (``Contributor``) before the proposal enters the pipeline - so a Reader
        cannot submit any action. ``None`` skips the entry gate (a
        pantheon-internal caller with no console role); Forseti's principal RBAC
        still applies downstream.
        """
        correlation_id = f"conv-{uuid.uuid4()}"
        if initiator_role is not None:
            role = _ROLE_BY_NAME.get(initiator_role.strip().lower())
            if role is None or not has_capability((role,), _SUBMIT_CAPABILITY):
                return {
                    "submitted": False,
                    "abstain_reason": "rbac_role_floor",
                    "required_role": "Contributor",
                    "initiator_role": initiator_role,
                    "correlation_id": correlation_id,
                }
        action_type, resource_id = translate_action_intent(question)
        if action_type is None:
            # A recognised command verb with no ActionType mapping: abstain
            # rather than guess. The operator is told it is unsupported.
            return {
                "submitted": False,
                "abstain_reason": "unmapped_action_intent",
                "correlation_id": correlation_id,
            }
        if self._proposal_sink is None:
            # No pipeline wired (pantheon not composed): signal re-entry.
            return {
                "submitted": False,
                "abstain_reason": "requires_typed_pipeline",
                "correlation_id": correlation_id,
                "action_type": action_type,
            }
        proposal: dict[str, Any] = {
            "idempotency_key": correlation_id,
            "correlation_id": correlation_id,
            "initiator_principal": user_id,
            "operator_initiated": True,
            "action_type": action_type,
            "resource_id": resource_id[:_MAX_RESOURCE_CHARS] if resource_id else None,
            "event_type": "operator_request",
            "params": {
                "question": question[:_MAX_QUESTION_CHARS],
                "session_id": session_id[:_MAX_SESSION_CHARS],
            },
        }
        await self._proposal_sink(proposal)
        self._progress.setdefault(correlation_id, []).append(
            {"topic": "object.conversation", "state": "submitted", "action_type": action_type}
        )
        _evict_oldest(self._progress, _MAX_PROGRESS_KEYS, keep=correlation_id)
        return {
            "submitted": True,
            "correlation_id": correlation_id,
            "action_type": action_type,
            "initiator_principal": user_id,
        }

    # ---- typed port (progress rendering) -------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Record pipeline progress for a submitted proposal.

        Bragi subscribes to ``object.verdict`` and ``object.action-run`` only
        to render progress back to the operator (agent-pantheon.md 7.7 - Bragi
        renders, never executes). It appends the state; it publishes nothing.
        """
        if topic not in ("object.verdict", "object.action-run"):
            return None
        correlation_id = str(payload.get("correlation_id", ""))
        if not correlation_id:
            return None
        entry = {
            "topic": topic,
            "state": payload.get("state") or payload.get("risk_verdict"),
            "action_type": payload.get("action_type"),
            "outcome": payload.get("outcome"),
        }
        steps = self._progress.setdefault(correlation_id, [])
        # Idempotency: at-least-once delivery can redeliver the same lifecycle
        # record, which would otherwise show the operator a duplicated step
        # ("executing, executing"). Skip an append identical to the last step.
        if steps and steps[-1] == entry:
            return None
        steps.append(entry)
        # Bound the per-correlation list too (not just the key count): a
        # redelivery / retry burst must not grow one conversation's progress
        # log without limit. Keep the most recent steps.
        if len(steps) > _MAX_PROGRESS_STEPS:
            del steps[:-_MAX_PROGRESS_STEPS]
        _evict_oldest(self._progress, _MAX_PROGRESS_KEYS, keep=correlation_id)
        return None

    def progress_for(self, correlation_id: str) -> list[dict[str, Any]]:
        """The recorded pipeline progress for one submitted proposal."""
        return list(self._progress.get(correlation_id, []))

    # ---- agent-to-agent introspection ----------------------------------

    async def introspect_agent(
        self,
        agent_name: str,
        question: str,
        *,
        requester: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Agent-to-agent (A2A) NL introspection (agent-pantheon.md 6.2).

        A pantheon agent (``requester``) asks another agent a
        natural-language question through Bragi - the same conversational
        port operators use - when the typed schema is not a fit (e.g. Odin
        asking Saga "who executed correlation abc"). The request is
        read-only: each agent's conversational port refuses a command and
        signals it must re-enter the typed pipeline (7.7), so A2A can never
        become a side-channel that bypasses judge/approve/execute.

        The shared correlation trace (``context['correlation_id']``) is the
        only thing the two ports share; the response carries ``requester``
        so the audit trail shows which agent asked.
        """
        if requester not in PANTHEON_NAMES:
            # A2A is pantheon-internal: an unknown requester would poison the
            # audit trail (spoofed "who asked"). Reject at the boundary.
            raise ValueError(f"unknown requester agent: {requester!r}")
        ctx: dict[str, Any] = {**(context or {}), "requester": requester, "a2a": True}
        responder = self._agent_responders.get(agent_name)
        if responder is None:
            return {
                "primary_agent": agent_name,
                "answer": None,
                "facts": {},
                "abstain_reason": "responder_not_registered",
                "requester": requester,
                "trace_ref": str(ctx.get("correlation_id") or ""),
            }
        answer = await responder(question, ctx)
        # Defensive copy: never mutate a dict the responder may still own
        # (a fork responder could return a cached / shared object).
        answer = dict(answer)
        answer.setdefault("primary_agent", agent_name)
        answer["requester"] = requester
        return answer

    # ---- routing -------------------------------------------------------

    def route(self, question: str) -> RoutingDecision:
        explicit = _explicit_agent_names(question)
        if explicit:
            primary, *explicit_contributors = explicit
            return RoutingDecision(
                primary_agent=primary,
                scores={name: 10.0 for name in explicit},
                tie_break="explicit_agent",
                contributors=tuple(explicit_contributors[:_MAX_CONTRIBUTORS]),
            )
        tokens = _tokenize(question)
        scores: dict[str, float] = {}
        matched_domains: dict[str, str] = {}
        for spec in PANTHEON_SPECS:
            best_score = 0.0
            best_domain: str | None = None
            for domain in spec.question_domains:
                score = _domain_score(domain, tokens)
                if score > best_score:
                    best_score = score
                    best_domain = domain
            if best_score > 0:
                scores[spec.name] = best_score
                if best_domain is not None:
                    matched_domains[spec.name] = best_domain

        if not scores:
            return RoutingDecision(primary_agent=None, scores={}, tie_break=None)

        # Tie-break: specificity (already in score) > layer precedence.
        winner, tie_break = _pick_winner(scores)
        contributors = tuple(name for name in scores if name != winner)
        return RoutingDecision(
            primary_agent=winner,
            scores=scores,
            tie_break=tie_break,
            contributors=contributors,
        )

    # ---- session -------------------------------------------------------

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        initiator_role: str | None = None,
        allow_action_proposal: bool = True,
    ) -> Turn:
        """Route + call primary + record the turn.

        ``initiator_role`` (the console session's Entra role) is applied by the
        entry RBAC gate when the turn is an action command; ``None`` skips it.
        A read-only channel sets ``allow_action_proposal=False`` so an action
        utterance is redirected to the dedicated proposal route without
        publishing anything from the conversational port.
        """
        session = self._sessions.setdefault(
            session_id,
            ConversationSession(session_id=session_id, user_id=user_id),
        )
        if session.user_id != user_id:
            raise PermissionError(f"session {session_id!r} belongs to a different user")
        # Bound the session map so a long-lived narrator cannot leak one entry
        # per session id forever (evicts oldest, never the active session).
        _evict_oldest(self._sessions, _MAX_SESSIONS, keep=session_id)
        # MUST-NOT-bypass (agent-pantheon.md 7.7): a command ("restart vm-1")
        # is not answered by the conversational port. Bragi translates it into
        # a typed ActionProposal whose initiator is the operator and hands it
        # to the pipeline (Huginn -> Forseti judge -> Var approve -> Thor
        # execute). Bragi never calls an executor; it only submits + renders.
        if is_action_intent(question):
            if allow_action_proposal:
                result = await self.submit_action_proposal(
                    session_id=session_id,
                    user_id=user_id,
                    question=question,
                    initiator_role=initiator_role,
                )
            else:
                result = {
                    "submitted": False,
                    "abstain_reason": "action_route_required",
                }
            answer: dict[str, Any] = {
                "answer": None,
                "primary_agent": None,
                "requires_typed_pipeline": True,
                **result,
            }
            turn = Turn(
                turn_index=len(session.turns),
                question=question,
                primary_agent=None,
                answer=answer,
                decision=RoutingDecision(primary_agent=None, scores={}, tie_break=None),
            )
            session.turns.append(turn)
            return turn
        decision = self.route(question)
        if decision.primary_agent is None:
            answer = {
                "answer": None,
                "primary_agent": None,
                "abstain_reason": "no_route",
                "handoff_needed": True,
            }
        else:
            responder = self._agent_responders.get(decision.primary_agent)
            if responder is None:
                answer = {
                    "answer": None,
                    "primary_agent": decision.primary_agent,
                    "abstain_reason": "responder_not_registered",
                }
            else:
                answer = await responder(question, {"session_id": session_id})
                answer.setdefault("primary_agent", decision.primary_agent)
                contributor_answers, contributor_errors = await self._ask_contributors(
                    decision.contributors,
                    question=question,
                    session_id=session_id,
                )
                successful = [item["agent"] for item in contributor_answers]
                answer["contributors"] = successful
                answer["contributor_answers"] = contributor_answers
                if contributor_errors:
                    answer["contributor_errors"] = contributor_errors
                primary_text = answer.get("answer")
                if isinstance(primary_text, str) and contributor_answers:
                    lines = [f"{decision.primary_agent}: {primary_text}"]
                    lines.extend(
                        f"{item['agent']}: {item['answer']}"
                        for item in contributor_answers
                        if isinstance(item.get("answer"), str)
                    )
                    answer["answer"] = "\n".join(lines)
                answer["score_breakdown"] = decision.scores
                answer["tie_break_reason"] = decision.tie_break

        turn = Turn(
            turn_index=len(session.turns),
            question=question,
            primary_agent=decision.primary_agent,
            answer=answer,
            decision=decision,
        )
        session.turns.append(turn)
        return turn

    async def _ask_contributors(
        self,
        contributors: tuple[str, ...],
        *,
        question: str,
        session_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Call bounded secondary responders without risking the primary reply."""

        selected = contributors[:_MAX_CONTRIBUTORS]

        async def call(agent_name: str) -> tuple[str, dict[str, Any] | None, str | None]:
            responder = self._agent_responders.get(agent_name)
            if responder is None:
                return agent_name, None, "responder_not_registered"
            try:
                result = await asyncio.wait_for(
                    responder(question, {"session_id": session_id, "contributor": True}),
                    timeout=_CONTRIBUTOR_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                return agent_name, None, "timeout"
            except Exception as exc:  # noqa: BLE001 - isolate one secondary responder
                _LOG.warning(
                    "bragi_contributor_failed",
                    extra={"agent": agent_name, "error_type": type(exc).__name__},
                )
                return agent_name, None, "responder_error"
            return agent_name, result, None

        results = await asyncio.gather(*(call(name) for name in selected))
        answers: list[dict[str, Any]] = []
        errors: list[str] = []
        for agent_name, result, error in results:
            if error is not None:
                errors.append(f"{agent_name}:{error}")
                continue
            if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
                errors.append(f"{agent_name}:abstained")
                continue
            facts = result.get("facts")
            answers.append(
                {
                    "agent": agent_name,
                    "answer": result["answer"],
                    "facts": dict(facts) if isinstance(facts, dict) else {},
                }
            )
        return answers, errors

    def prior_turns(self, session_id: str, *, limit: int = 5) -> tuple[Turn, ...]:
        session = self._sessions.get(session_id)
        if session is None:
            return ()
        return tuple(session.turns[-limit:])

    def sessions_for(self, user_id: str) -> tuple[ConversationSession, ...]:
        return tuple(s for s in self._sessions.values() if s.user_id == user_id)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        roster = {spec.name: list(spec.question_domains) for spec in PANTHEON_SPECS}
        facts = {
            **capability_facts(self.spec),
            "roster": roster,
        }
        answer = (
            "I am the narrator: I route your question to the agent that owns it. "
            f"{len(PANTHEON_SPECS)} agents are reachable - ask about topics like "
            "cost, capacity, anomalies, action status, audit history, or rules."
        )
        return IntrospectionResult(answer=answer, facts=facts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_WORD = re.compile(r"[a-z0-9]+")


def translate_action_intent(
    question: str,
    action_type_names: Collection[str] = (),
) -> tuple[str | None, str | None]:
    """Map an operator command to ``(action_type, resource_id)``.

    The single source of truth for conversational action translation, shared by
    Bragi's pantheon-internal ``submit_action_proposal`` and the read-API
    console-action route (``fdai.delivery.read_api.console_action``) so the two
    surfaces never drift. Returns ``(None, None)`` when the leading command verb
    maps to no ActionType (the caller then abstains rather than guessing).
    """
    action_type = _catalog_action_intent(question, action_type_names)
    if action_type is None:
        verb = leading_verb(question)
        action_type = _INTENT_ACTION.get(verb or "")
    if action_type is None:
        return None, None
    return action_type, _resource_of(question, action_type=action_type)


def _catalog_action_intent(
    question: str,
    action_type_names: Collection[str],
) -> str | None:
    """Resolve an exact catalog id or one unambiguous full suffix match."""

    normalized = question.lower()
    names = tuple(sorted({name for name in action_type_names if name}))
    exact = [
        name
        for name in names
        if re.search(rf"(?<![a-z0-9.-]){re.escape(name.lower())}(?![a-z0-9.-])", normalized)
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    tokens = _tokenize(question)
    matches: list[tuple[int, str]] = []
    for name in names:
        suffix = name.split(".", 1)[-1]
        parts = tuple(part for part in suffix.split("-") if part)
        if len(parts) >= 2 and all(part in tokens for part in parts):
            matches.append((len(parts), name))
    if not matches:
        return None
    best_length = max(length for length, _ in matches)
    best = [name for length, name in matches if length == best_length]
    return best[0] if len(best) == 1 else None


def _resource_of(question: str, *, action_type: str | None = None) -> str | None:
    """Best-effort resource id from an operator command.

    The first token that looks like a resource identifier (contains a hyphen
    or a digit, e.g. ``vm-1`` / ``prod-pg-01``). Deterministic and
    conservative: returns ``None`` when nothing resembles an id, so the
    proposal carries no resource rather than a wrong guess.
    """
    ignored = set(re.split(r"[.-]", action_type.lower())) if action_type else set()
    if action_type:
        ignored.add(action_type.split(".", 1)[-1].lower())
    for token in re.findall(r"[a-z0-9-]+", question.lower()):
        if token in ignored:
            continue
        if len(token) >= 3 and ("-" in token or any(c.isdigit() for c in token)):
            return str(token)
    return None


def _tokenize(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower())}


def _explicit_agent_names(question: str) -> list[str]:
    """Return canonical agent names explicitly mentioned, in text order."""

    canonical = {name.lower(): name for name in PANTHEON_NAMES}
    found: list[str] = []
    for token in _WORD.findall(question.lower()):
        name = canonical.get(token)
        if name is not None and name not in found:
            found.append(name)
    return found


def _domain_score(domain: str, tokens: set[str]) -> float:
    """Score how well the tokens match a `question_domains` entry.

    Deterministic, LLM-free (Wave 4). Split the domain identifier on
    underscore / non-word so tokens can match individual parts.

    - Full match (every domain part hit): +2.0 (specificity bonus).
    - Each partial exact-word hit: +1.0.
    - Each prefix / suffix match on a shared 4+ character base: +0.6.
      This gives simple stemming ("changed" -> "change") without a
      dictionary.
    """
    domain_tokens = set(re.split(r"[_\W]+", domain.lower())) - {""}
    if not domain_tokens:
        return 0.0
    exact = len(tokens & domain_tokens)
    if exact == len(domain_tokens):
        return 2.0
    if exact:
        return 1.0 * exact
    partial = 0
    for t in tokens:
        if len(t) < 4:
            continue
        for d in domain_tokens:
            if len(d) < 4:
                continue
            if abs(len(t) - len(d)) <= 3 and (t.startswith(d) or d.startswith(t)):
                partial += 1
                break
    if partial:
        return 0.6 * partial
    return 0.0


def _pick_winner(scores: dict[str, float]) -> tuple[str, str | None]:
    """Return (winner_name, tie_break_reason).

    Tie-break order: score desc > layer precedence asc (governance
    beats pipeline beats domain) > name asc for determinism.
    """
    if not scores:
        raise ValueError("empty scores")
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], _layer_of(kv[0]), kv[0]))
    top_name, top_score = ordered[0]
    if len(ordered) == 1 or ordered[1][1] != top_score:
        return top_name, "score"
    # Tie on score
    return top_name, "layer_precedence"


def _layer_of(agent_name: str) -> int:
    for spec in PANTHEON_SPECS:
        if spec.name == agent_name:
            return _PANTHEON_PRECEDENCE[spec.layer.value]
    return 99


__all__ = ["Bragi", "RoutingDecision", "Turn", "ConversationSession", "translate_action_intent"]
