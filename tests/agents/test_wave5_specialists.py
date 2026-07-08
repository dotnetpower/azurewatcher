"""Wave 5 domain-specialist tests."""

from __future__ import annotations

import asyncio

from fdai.agents.bus import InMemoryBus
from fdai.agents.freyr import Freyr
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.agents.registry import load_pantheon

# ---------------------------------------------------------------------------
# Njord
# ---------------------------------------------------------------------------


def test_njord_emits_anomaly_when_spend_exceeds_baseline() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    n = Njord(bus=bus, anomaly_ratio=1.5)
    # Prime baseline
    for _ in range(10):
        asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=100.0))
    # Spike
    asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=200.0))
    anomalies = bus.messages_on("object.cost-anomaly")
    assert len(anomalies) == 1
    payload = anomalies[0].payload
    assert payload["scope"] == "rg-1"
    assert payload["ratio"] >= 1.5


def test_njord_no_anomaly_within_baseline() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    n = Njord(bus=bus, anomaly_ratio=1.5)
    for _ in range(10):
        asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=100.0))
    asyncio.run(n.ingest_cost_sample(scope="rg-1", amount_usd=120.0))
    assert bus.messages_on("object.cost-anomaly") == []


def test_njord_cost_impact_returns_table_value() -> None:
    n = Njord()
    est = n.cost_impact("remediate.enable-encryption")
    assert est.monthly_delta_usd == 3.5
    assert est.confidence >= 0.5


def test_njord_cost_impact_defaults_low_confidence_for_unknown() -> None:
    n = Njord()
    est = n.cost_impact("unknown.thing")
    assert est.monthly_delta_usd == 0.0
    assert est.confidence < 0.5


# ---------------------------------------------------------------------------
# Freyr
# ---------------------------------------------------------------------------


def test_freyr_forecast_recommends_scale_up_on_high_util() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Freyr(bus=bus, scale_up_threshold=0.75)
    for u in (0.6, 0.7, 0.8, 0.85, 0.9):
        asyncio.run(f.ingest_utilization(resource_id="vm-1", utilization=u))
    advice = f.sizing_advice("vm-1")
    assert advice.action == "scale_up"


def test_freyr_recommends_scale_down_on_low_util() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Freyr(bus=bus, scale_down_threshold=0.25)
    for u in (0.3, 0.2, 0.15, 0.1, 0.1):
        asyncio.run(f.ingest_utilization(resource_id="vm-2", utilization=u))
    advice = f.sizing_advice("vm-2")
    assert advice.action == "scale_down"


def test_freyr_publishes_capacity_forecast_events() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Freyr(bus=bus)
    for u in (0.4, 0.5, 0.6):
        asyncio.run(f.ingest_utilization(resource_id="vm-3", utilization=u))
    events = bus.messages_on("object.capacity-forecast")
    assert len(events) == 3
    assert events[-1].payload["resource_id"] == "vm-3"


# ---------------------------------------------------------------------------
# Loki
# ---------------------------------------------------------------------------


def test_loki_respects_blast_radius_cap() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=2)
    proposal = asyncio.run(
        loki.propose_experiment(
            experiment_id="ex-1",
            action_type="ops.restart-service",
            targets=("a", "b", "c", "d"),
        )
    )
    assert proposal.accepted
    assert len(proposal.targets) == 2
    events = bus.messages_on("object.chaos-experiment")
    assert events[0].payload["blast_radius_used"] == 2


def test_loki_refuses_further_proposals_when_radius_full() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=1)
    asyncio.run(
        loki.propose_experiment(
            experiment_id="ex-1",
            action_type="x.y",
            targets=("t1",),
        )
    )
    second = asyncio.run(
        loki.propose_experiment(
            experiment_id="ex-2",
            action_type="x.y",
            targets=("t2",),
        )
    )
    assert not second.accepted
    assert second.reason == "blast_radius_full"


def test_loki_release_targets_frees_slots() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=1)
    asyncio.run(loki.propose_experiment(experiment_id="e1", action_type="x", targets=("t1",)))
    loki.release_targets(("t1",))
    third = asyncio.run(
        loki.propose_experiment(experiment_id="e2", action_type="x", targets=("t2",))
    )
    assert third.accepted
