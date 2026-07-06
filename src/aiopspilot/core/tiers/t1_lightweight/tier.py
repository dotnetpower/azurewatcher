"""T1 lightweight tier - embedding similarity + learned-action reuse.

Phase 2 T1 (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § T1 Lightweight Tier`]).

Contract
--------

Given an :class:`Event`, the T1 tier tries to resolve it deterministically
by matching the event's embedding against a pattern library of past
resolved incidents. A match requires the similarity score to clear a
**configured threshold** (thresholds are config, not hard-coded). On
match, T1 returns a *reused* :class:`LearnedAction` whose provenance is
attached - the action still passes the verifier + risk-gate before it
can execute (reuse is not auto-trust).

Below threshold → :attr:`T1Outcome.ABSTAIN` → the trust-router routes
the event to T2 (LLM reasoning) per
[`docs/roadmap/llm-strategy.md § Pipeline Stages`].

DI seams
--------

- :class:`EmbeddingModel` - turn an event/incident text into a vector.
  Real backends (sentence-transformers, OpenAI embeddings) go here; the
  fake in :mod:`.testing` returns a deterministic vector so tests are
  reproducible without network.
- :class:`PatternLibrary` - pgvector-backed in production; in-memory fake
  under :mod:`.testing` for local dev + unit tests.

Neither seam is invoked from ``core/`` directly; the composition root
binds a concrete pair. This module is the T1 orchestrator only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import sqrt
from typing import Any, Protocol, runtime_checkable

from aiopspilot.shared.contracts.models import Event


class T1Outcome(StrEnum):
    """Terminal outcome for one :meth:`T1Tier.evaluate` call."""

    REUSED = "reused"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class LearnedAction:
    """An action learned from a past resolved incident.

    Provenance is mandatory: :attr:`incident_id` (the audit trail id of
    the origin) + :attr:`success_rate` (over prior reuses) let the risk
    gate weigh whether to trust reuse. A reused action is **not
    auto-trusted** - see the P2 doc.
    """

    signature: str
    """Stable hash of ``(rule_id, action_type, parameter-key set)``. Used
    by :class:`PatternLibrary` for O(1) lookup once similarity picks a
    neighbour."""

    rule_id: str
    action_type: str
    params: Mapping[str, Any]
    incident_id: str
    success_rate: float
    reuse_count: int = 0


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    """One neighbour + score returned by the pattern library."""

    action: LearnedAction
    score: float


@dataclass(frozen=True, slots=True)
class T1Decision:
    """Frozen record produced by :meth:`T1Tier.evaluate`."""

    outcome: T1Outcome
    event_id: str
    threshold: float
    best_match: SimilarityMatch | None = None
    reason: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Every diagnostic the router / audit trail cares about. Redundant
    with ``reason`` when a single fact drives the outcome."""

    requires_reverification: bool = True
    """A ``REUSED`` decision MUST be re-validated through the verifier
    and risk-gate before its LearnedAction can execute (phase-2
    § T1 § Learned-action reuse). Always ``True`` for :class:`T1Outcome`
    values that would drive execution - callers who ignore it are
    violating the safety contract."""


# ---------------------------------------------------------------------------
# DI seams
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingModel(Protocol):
    """Produce a fixed-length vector from an event/text."""

    dim: int

    async def embed(self, text: str) -> Sequence[float]: ...


@runtime_checkable
class PatternLibrary(Protocol):
    """Similarity index of past resolved incidents.

    The production backend is pgvector; the fake in :mod:`.testing` uses
    plain cosine over an in-memory list. Return the top ``k`` matches
    ranked by descending similarity score.
    """

    async def search(
        self, query_vector: Sequence[float], *, k: int = 5
    ) -> tuple[SimilarityMatch, ...]: ...


# ---------------------------------------------------------------------------
# Tier
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class T1Config:
    """T1 thresholds. Config-driven per phase-2 § T1."""

    similarity_threshold: float = 0.8
    """Cosine similarity floor for a reuse decision. Below → abstain."""

    min_success_rate: float = 0.9
    """A learned action MUST have cleared a success-rate floor over its
    prior reuses; unproven candidates are abstained even on high similarity."""


class T1Tier:
    """Compose embedding + similarity + safety-re-verify for T1 reuse."""

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel,
        pattern_library: PatternLibrary,
        config: T1Config | None = None,
    ) -> None:
        cfg = config or T1Config()
        if not 0.0 <= cfg.similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold MUST be in [0.0, 1.0]")
        if not 0.0 <= cfg.min_success_rate <= 1.0:
            raise ValueError("min_success_rate MUST be in [0.0, 1.0]")
        self._embed = embedding_model
        self._library = pattern_library
        self._config = cfg

    async def evaluate(self, *, event: Event) -> T1Decision:
        """Return a :class:`T1Decision` for one event."""
        query_text = _event_text(event)
        vector = await self._embed.embed(query_text)
        matches = await self._library.search(vector, k=5)

        if not matches:
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=None,
                reason="no_neighbour_found",
                reasons=("no_neighbour_found",),
            )

        # matches are already ordered by descending score by contract;
        # we still take the max to be safe.
        best = max(matches, key=lambda m: m.score)
        reasons: list[str] = []

        if best.score < self._config.similarity_threshold:
            reasons.append(
                f"similarity={best.score:.4f}<threshold={self._config.similarity_threshold:.4f}"
            )

        if best.action.success_rate < self._config.min_success_rate:
            reasons.append(
                f"success_rate={best.action.success_rate:.4f}<"
                f"floor={self._config.min_success_rate:.4f}"
            )

        if reasons:
            return T1Decision(
                outcome=T1Outcome.ABSTAIN,
                event_id=str(event.event_id),
                threshold=self._config.similarity_threshold,
                best_match=best,
                reason=reasons[0],
                reasons=tuple(reasons),
            )

        return T1Decision(
            outcome=T1Outcome.REUSED,
            event_id=str(event.event_id),
            threshold=self._config.similarity_threshold,
            best_match=best,
            reason=None,
            reasons=(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_text(event: Event) -> str:
    """Deterministic text projection of an event for embedding.

    Includes only fields the pattern library can reasonably look up
    against; the resource props subset is intentional to keep vectors
    stable across cosmetic payload churn (timestamps, correlation ids).
    """
    payload = event.payload
    resource = payload.get("resource") if isinstance(payload, Mapping) else None
    resource_type = ""
    props_summary = ""
    if isinstance(resource, Mapping):
        rt = resource.get("type")
        if isinstance(rt, str):
            resource_type = rt
        props = resource.get("props")
        if isinstance(props, Mapping):
            keys = sorted(str(k) for k in props.keys())
            props_summary = ",".join(keys)
    return f"event_type={event.event_type};resource_type={resource_type};props={props_summary}"


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity used by the fake pattern library."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


__all__ = [
    "EmbeddingModel",
    "LearnedAction",
    "PatternLibrary",
    "SimilarityMatch",
    "T1Config",
    "T1Decision",
    "T1Outcome",
    "T1Tier",
    "cosine_similarity",
]
