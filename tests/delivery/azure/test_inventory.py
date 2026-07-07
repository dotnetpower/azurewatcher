"""AzureResourceGraphInventory - structural + safety invariants (P1 W-2).

Assertions the stub must satisfy so downstream code can be wired against
a real interface:

- Full-scan streams end with an atomic-promote fence (``final=True``).
- Concurrent shard queries respect ``max_concurrent_queries``.
- On query failure, no ``final=True`` batch is emitted - a caller MUST
  retain the previous graph (fail-closed).
- Duplicate resources / links inside one shard are collapsed
  (idempotent-upsert precondition).
- The delta stream also ends with ``final=True``.
- The adapter satisfies the runtime-checkable ``Inventory`` Protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from fdai.delivery.azure.inventory import (
    AzureInventoryConfig,
    AzureResourceGraphInventory,
    ResourceQueryFn,
)
from fdai.shared.providers import (
    Inventory,
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)


def _rr(resource_id: str, rtype: str = "compute.vm") -> ResourceRecord:
    return ResourceRecord(resource_id=resource_id, type=rtype)


def _lr(from_id: str, to_id: str, link_type: str = "contains") -> LinkRecord:
    return LinkRecord(
        from_id=from_id,
        from_type="compute.vm",
        link_type=link_type,
        to_id=to_id,
        to_type="resource-group",
    )


def _adapter(
    query: ResourceQueryFn,
    *,
    types: tuple[str, ...] = ("compute.vm", "object-storage"),
    concurrency: int = 4,
) -> AzureResourceGraphInventory:
    return AzureResourceGraphInventory(
        config=AzureInventoryConfig(resource_types=types, max_concurrent_queries=concurrency),
        query=query,
    )


def test_config_rejects_zero_or_negative_concurrency() -> None:
    async def _noop(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    with pytest.raises(ValueError):
        AzureResourceGraphInventory(
            config=AzureInventoryConfig(resource_types=(), max_concurrent_queries=0),
            query=_noop,
        )


def test_adapter_satisfies_inventory_protocol() -> None:
    async def _noop(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    assert isinstance(_adapter(_noop), Inventory)


@pytest.mark.asyncio
async def test_full_snapshot_ends_with_final_true() -> None:
    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (_rr(f"{rt}/1"),), ()

    adapter = _adapter(_q)
    seen: list[InventoryBatch] = []
    async for batch in adapter.full_snapshot():
        seen.append(batch)

    assert seen  # at least the fence
    assert seen[-1].final is True
    assert seen[-1].resources == ()
    assert seen[-1].links == ()
    # Every prior batch had payload; the fence never carries data.
    for batch in seen[:-1]:
        assert batch.final is False
        assert batch.resources or batch.links


@pytest.mark.asyncio
async def test_full_snapshot_dedupes_resources_and_links_per_shard() -> None:
    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        # Same resource id repeated three times; same link twice.
        return (
            [_rr("dup", rtype=rt)] * 3,
            [_lr("child", "parent")] * 2,
        )

    adapter = _adapter(_q, types=("compute.vm",))
    resources: list[ResourceRecord] = []
    links: list[LinkRecord] = []
    async for batch in adapter.full_snapshot():
        resources.extend(batch.resources)
        links.extend(batch.links)

    assert len(resources) == 1
    assert resources[0].resource_id == "dup"
    assert len(links) == 1


@pytest.mark.asyncio
async def test_full_snapshot_respects_concurrency_semaphore() -> None:
    max_conc = 2
    live = 0
    peak = 0
    lock = asyncio.Lock()

    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        nonlocal live, peak
        async with lock:
            live += 1
            peak = max(peak, live)
        try:
            # Give the scheduler room to overlap.
            await asyncio.sleep(0.01)
            return (_rr(f"{rt}/1"),), ()
        finally:
            async with lock:
                live -= 1

    adapter = _adapter(
        _q,
        types=tuple(f"rt-{i}" for i in range(10)),
        concurrency=max_conc,
    )
    async for _ in adapter.full_snapshot():
        pass

    assert peak <= max_conc, f"concurrency limit breached: peak={peak}"


@pytest.mark.asyncio
async def test_full_snapshot_fails_closed_on_query_error() -> None:
    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        if rt == "boom":
            raise RuntimeError("ARG unavailable")
        return (_rr(f"{rt}/1"),), ()

    adapter = _adapter(_q, types=("compute.vm", "boom", "object-storage"))
    seen: list[InventoryBatch] = []
    with pytest.raises(RuntimeError, match="ARG unavailable"):
        async for batch in adapter.full_snapshot():
            seen.append(batch)

    # Critical: no fence batch ever appeared, so the caller retains the
    # previous graph (docs/roadmap/csp-neutrality.md § 5).
    assert not any(batch.final for batch in seen)


@pytest.mark.asyncio
async def test_delta_stub_emits_final_true_empty_batch() -> None:
    async def _q(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    adapter = _adapter(_q)
    seen: list[InventoryBatch] = []
    async for batch in adapter.delta(cursor="cur-1"):
        seen.append(batch)

    assert len(seen) == 1
    assert seen[0].final is True
    assert seen[0].resources == ()
    assert seen[0].links == ()


@pytest.mark.asyncio
async def test_full_snapshot_with_no_resource_types_still_yields_fence() -> None:
    async def _q(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        raise AssertionError("should not be called")  # pragma: no cover

    adapter = _adapter(_q, types=())
    seen: list[InventoryBatch] = []
    async for batch in adapter.full_snapshot():
        seen.append(batch)
    assert len(seen) == 1
    assert seen[0].final is True
