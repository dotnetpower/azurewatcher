"""Norns - Learner (Wave 2 behavior).

Norns watches the audit stream, counts fingerprint occurrences, and
publishes RuleCandidate proposals to Mimir when a threshold is
crossed. Wave 2 implements a deterministic streaming counter (T0); T1
clustering and T2 batch summary land in later waves.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fdai.agents.base import Agent
from fdai.agents.pantheon import _NORNS


class Norns(Agent):
    """Wave-2 Norns: fingerprint aggregator + candidate proposer."""

    def __init__(self, *, promotion_threshold: int = 3) -> None:
        super().__init__(spec=_NORNS)
        self._fingerprint_counter: Counter[str] = Counter()
        self._proposed: set[str] = set()
        self._promotion_threshold = promotion_threshold
        self.pending_candidates: list[dict[str, Any]] = []

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.issue":
            fp = str(payload.get("fingerprint", ""))
            if not fp:
                return
            self._fingerprint_counter[fp] += 1
            if (
                self._fingerprint_counter[fp] >= self._promotion_threshold
                and fp not in self._proposed
            ):
                self._proposed.add(fp)
                self.pending_candidates.append(
                    {
                        "source_signal": "handoff_fingerprint",
                        "evidence": {
                            "fingerprint": fp,
                            "occurrence_count": self._fingerprint_counter[fp],
                        },
                        "proposed_by": "Norns",
                        "proposal_kind": "new",
                    }
                )

    def occurrences(self, fingerprint: str) -> int:
        return self._fingerprint_counter[fingerprint]


__all__ = ["Norns"]
