"""Self-consistency sampler - stability reduction + sampling.

Design reference: ``docs/roadmap/hallucination-rubric-gate.md`` §
Self-consistency.
"""

from __future__ import annotations

import pytest

from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.self_consistency import (
    STABILITY_SIGNAL_KEY,
    SelfConsistencySampler,
    compute_stability,
)
from fdai.core.quality_gate.testing import SequenceCrossCheckModel


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={},
        cited_rule_ids=("r.known",),
    )


class TestComputeStability:
    def test_uniform_is_full_stability(self) -> None:
        modal, count, stability = compute_stability(["a", "a", "a"])
        assert modal == "a"
        assert count == 3
        assert stability == pytest.approx(1.0)

    def test_majority(self) -> None:
        modal, count, stability = compute_stability(["a", "a", "b"])
        assert modal == "a"
        assert count == 2
        assert stability == pytest.approx(2 / 3)

    def test_all_distinct_is_low(self) -> None:
        modal, count, stability = compute_stability(["a", "b", "c"])
        assert count == 1
        assert stability == pytest.approx(1 / 3)

    def test_tie_breaks_on_first_seen(self) -> None:
        # a and b both appear twice; first-seen (a) wins for determinism.
        modal, count, stability = compute_stability(["a", "b", "a", "b"])
        assert modal == "a"
        assert count == 2

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            compute_stability([])


class TestSelfConsistencySampler:
    def test_rejects_zero_samples(self) -> None:
        with pytest.raises(ValueError, match="samples MUST be"):
            SelfConsistencySampler(proposer=SequenceCrossCheckModel(sequence=("a",)), samples=0)

    @pytest.mark.asyncio
    async def test_stable_proposer(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("remediate.tag-add",)), samples=4
        )
        result = await sampler.sample(_candidate())
        assert result.total == 4
        assert result.stability == pytest.approx(1.0)
        assert result.modal_action_type == "remediate.tag-add"
        assert result.signal == {STABILITY_SIGNAL_KEY: 1.0}

    @pytest.mark.asyncio
    async def test_unstable_proposer_lowers_stability(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a", "b", "a", "c")), samples=4
        )
        result = await sampler.sample(_candidate())
        assert result.total == 4
        assert result.modal_action_type == "a"
        assert result.agreement_count == 2
        assert result.stability == pytest.approx(0.5)
        assert result.signal[STABILITY_SIGNAL_KEY] == pytest.approx(0.5)
