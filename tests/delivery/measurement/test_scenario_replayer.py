"""FrozenScenarioReplayer integration against shipped artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fdai.core.risk_gate import ActionPromotionRegistry
from fdai.delivery.measurement.scenario_replayer import FrozenScenarioReplayer
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(shutil.which("opa") is None, reason="OPA is required for scenario replay")
@pytest.mark.asyncio
async def test_replayer_produces_action_measurement_samples() -> None:
    replayer = FrozenScenarioReplayer(
        repo_root=_REPO_ROOT,
        scenario_set_version="v2026.07",
        audit_store=InMemoryStateStore(),
        promotion_registry=ActionPromotionRegistry(),
    )

    samples = await replayer.replay()

    assert samples
    assert all(sample.scenario_set_version == "v2026.07" for sample in samples)
    assert all(sample.guard_metrics for sample in samples)
    assert all(sample.success_metrics for sample in samples)
    assert {sample.action_type_id for sample in samples}
