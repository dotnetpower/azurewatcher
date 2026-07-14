"""Inventory delta forwarding and cursor safety tests."""

from __future__ import annotations

import pytest

from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Inventory:
    def __init__(self, *, final: bool = True) -> None:
        self.final = final
        self.seen_cursor = ""

    async def delta(self, cursor: str):  # type: ignore[no-untyped-def]
        self.seen_cursor = cursor
        yield InventoryBatch(
            resources=(
                ResourceRecord(
                    resource_id="resource:example/vm-1",
                    type="compute.vm",
                    props={"status": "updated"},
                    last_seen="2026-07-15T00:00:00Z",
                ),
            ),
            cursor="cursor-next",
        )
        if self.final:
            yield InventoryBatch(final=True, cursor="cursor-next")


@pytest.mark.asyncio
async def test_forward_delta_publishes_event_and_advances_cursor() -> None:
    inventory = _Inventory()
    state = InMemoryStateStore()
    bus = InMemoryEventBus()

    published = await forward_inventory_delta(
        inventory=inventory,
        state_store=state,
        event_bus=bus,
        topic="events",
        scope="subscription-1",
    )

    assert published == 1
    records = [item async for item in bus.subscribe("events", "reader")]
    assert records[0].payload["event_type"] == "inventory.resource_changed"
    assert records[0].payload["payload"]["resource"]["type"] == "compute.vm"
    cursor = await state.read_state("inventory_delta_cursor:subscription-1")
    assert cursor == {"cursor": "cursor-next"}


@pytest.mark.asyncio
async def test_forward_delta_preserves_cursor_without_final_fence() -> None:
    inventory = _Inventory(final=False)
    state = InMemoryStateStore()
    await state.write_state("inventory_delta_cursor:subscription-1", {"cursor": "cursor-old"})

    with pytest.raises(RuntimeError, match="final fence"):
        await forward_inventory_delta(
            inventory=inventory,
            state_store=state,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope="subscription-1",
        )

    cursor = await state.read_state("inventory_delta_cursor:subscription-1")
    assert cursor == {"cursor": "cursor-old"}
    assert inventory.seen_cursor == "cursor-old"
