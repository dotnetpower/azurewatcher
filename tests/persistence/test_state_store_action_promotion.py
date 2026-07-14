"""StateStore-backed promotion mode durability and fail-closed tests."""

from __future__ import annotations

import pytest

from fdai.core.risk_gate import PromotionMetrics
from fdai.delivery.persistence.state_store_action_promotion import (
    StateStoreActionPromotionRegistry,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _action_type():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "rule-catalog" / "action-types"
    return next(
        item
        for item in load_action_type_catalog(root, schema_registry=PackageResourceSchemaRegistry())
        if item.name == "remediate.tag-add"
    )


@pytest.mark.asyncio
async def test_promotion_round_trips_across_registry_instances() -> None:
    store = InMemoryStateStore()
    first = StateStoreActionPromotionRegistry(store=store)
    action_type = _action_type()
    first.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=999,
            samples=10_000,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )
    await first.persist(action_type.name)

    second = StateStoreActionPromotionRegistry(store=store)
    await second.refresh(action_type.name)

    assert second.mode_of(action_type.name) is Mode.ENFORCE


@pytest.mark.asyncio
async def test_corrupt_state_clamps_cached_enforce_to_shadow() -> None:
    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(store=store)
    action_type = _action_type()
    registry.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=999,
            samples=10_000,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )
    assert registry.mode_of(action_type.name) is Mode.ENFORCE
    await store.write_state(f"action_promotion:{action_type.name}", {"schema_version": "broken"})

    await registry.refresh(action_type.name)

    assert registry.mode_of(action_type.name) is Mode.SHADOW


@pytest.mark.asyncio
async def test_demotion_is_visible_after_restart() -> None:
    store = InMemoryStateStore()
    first = StateStoreActionPromotionRegistry(store=store)
    action_type = _action_type()
    first.demote(action_type.name)
    await first.persist(action_type.name)

    second = StateStoreActionPromotionRegistry(store=store)
    await second.refresh(action_type.name)
    assert second.mode_of(action_type.name) is Mode.SHADOW
