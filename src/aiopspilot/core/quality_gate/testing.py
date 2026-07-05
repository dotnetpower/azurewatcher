"""In-memory fakes for the quality gate seams — used by tests + local dev."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiopspilot.core.quality_gate.gate import (
    CrossCheckModel,
    GroundingSource,
    QualityCandidate,
    VerifierPolicy,
)
from aiopspilot.shared.contracts.models import Rule


class StaticVerifier(VerifierPolicy):
    """Deterministic verifier that returns a preconfigured outcome."""

    def __init__(self, *, outcome: bool | None) -> None:
        self._outcome = outcome

    def verify(self, candidate: QualityCandidate) -> bool | None:
        del candidate
        return self._outcome


class MatchTypeCrossCheckModel(CrossCheckModel):
    """A cross-check model that always agrees on the candidate's action_type."""

    def __init__(self, *, model_id: str = "fake-agree") -> None:
        self._id = model_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        return candidate.action_type, dict(candidate.params)


class MismatchCrossCheckModel(CrossCheckModel):
    """A cross-check model that always disagrees on the action_type."""

    def __init__(self, *, model_id: str = "fake-disagree") -> None:
        self._id = model_id

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        return f"{candidate.action_type}::other", {}


class InMemoryGroundingSource(GroundingSource):
    """A grounding source backed by an in-process rule map."""

    def __init__(self, rules: Mapping[str, Rule]) -> None:
        self._rules = dict(rules)

    def known_rule_ids(self) -> set[str]:
        return set(self._rules.keys())

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)


__all__ = [
    "InMemoryGroundingSource",
    "MatchTypeCrossCheckModel",
    "MismatchCrossCheckModel",
    "StaticVerifier",
]
