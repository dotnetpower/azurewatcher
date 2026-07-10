"""Azure Resource Graph (ARG) implementation of the ``Inventory`` Protocol.

This module realizes the 5th CSP-neutral wire contract for Azure - see
``docs/roadmap/csp-neutrality.md § 5. Inventory Contract`` and the Protocol
in ``src/fdai/shared/providers/inventory.py``.

P1 W-2 scope (stub)
-------------------

The **structural contract** is frozen here so downstream consumers (the
T0 engine's future graph-derived blast-radius, and the risk-gate) can be
wired against a real interface:

- **Parallel full-scan**: :meth:`AzureResourceGraphInventory.full_snapshot`
  shards work by ``resource_type`` under a **bounded semaphore**
  (``max_concurrent_queries``, default 4). The stub uses a synthetic
  ``ResourceQueryFn`` so tests can assert the concurrency structure without
  standing up ARG.
- **Atomic-promote fence**: the stream **always** ends with an
  :class:`InventoryBatch` whose ``final=True``. A caller MUST discard a
  stream that ends without it; the stub enforces this on every path.
- **Idempotent upsert (interface)**: batches are keyed on
  ``resource_id`` for resources and ``(from_id, link_type, to_id)`` for
  links. Adapters MUST NOT emit duplicates within one snapshot - this
  stub deduplicates the synthetic input to make the invariant testable.
- **Delta stream**: :meth:`AzureResourceGraphInventory.delta` accepts a
  cursor and returns an empty final batch by default; production wiring
  reads Activity Log entries forwarded onto a Kafka topic.

What is deliberately NOT here yet
---------------------------------

- No ``azure-mgmt-resourcegraph`` client is instantiated (that lands in
  P1 W-3 together with the OIDC-federated ``WorkloadIdentity`` binding).
- No Kusto query templates ship - they are configuration, not code.
- No writes into ``ontology_resource`` / ``ontology_link``; the caller
  (event-ingest) is the upsert authority per the Inventory contract.
- No Azure SDK imports appear anywhere in the module tree yet. When they
  land they stay confined to this file (or a sibling under
  ``delivery/azure/``) - ``core/`` never imports them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)

_DEFAULT_MAX_CONCURRENT_QUERIES: Final[int] = 4

# Injected async callable: given a resource_type, return the batch of
# resources + links the adapter would have fetched from ARG for that
# shard. Kept as a Protocol-like callable so tests can supply a fake
# without instantiating any Azure client.
ResourceQueryFn = Callable[[str], Awaitable[tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]]]


@dataclass(frozen=True, slots=True)
class AzureInventoryConfig:
    """Adapter configuration.

    Values come from :class:`fdai.shared.config.AppConfig` at the
    composition root; nothing here is hard-coded per environment.
    """

    resource_types: tuple[str, ...]
    """Which CSP-neutral ``resource_type`` values to shard the full-scan on.

    Sourced from the canonical vocabulary
    (``rule-catalog/vocabulary/resource-types.yaml``) - a fork narrows
    this list at deploy time to scope the initial scan.
    """

    max_concurrent_queries: int = _DEFAULT_MAX_CONCURRENT_QUERIES
    """Upper bound on concurrent ARG queries during ``full_snapshot``.

    A large tenant must not exhaust the ARG budget; ``docs/roadmap/csp-neutrality.md § 5``
    requires bounded concurrency for the parallel scan.
    """

    subscription_scopes: tuple[str, ...] = field(default_factory=tuple)
    """Subscription (or management-group) scopes the ARG queries run under.

    Empty tuple means "single scope resolved from the injected
    :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
    binding at query time" - the adapter never reads a subscription id
    from an environment variable directly.
    """


class AzureResourceGraphInventory:
    """Azure Resource Graph ``Inventory`` adapter (sharded full-scan).

    Implements the :class:`Inventory` Protocol over an injected
    :type:`ResourceQueryFn`. The live query function is produced by
    :class:`~fdai.delivery.azure.arg_query.AzureArgQueryFactory` and wired
    at the composition root through
    :func:`fdai.composition.bind_azure_inventory`; tests inject a synthetic
    ``ResourceQueryFn`` to assert the concurrency structure and
    atomic-promote fence without standing up ARG. The ``full_snapshot``
    path is live once bound; the ``delta`` (Activity-Log -> Kafka) path is
    still a stub until the forwarder ships (see ``csp-neutrality.md § 5``).
    """

    def __init__(
        self,
        *,
        config: AzureInventoryConfig,
        query: ResourceQueryFn,
    ) -> None:
        if config.max_concurrent_queries < 1:
            raise ValueError("AzureInventoryConfig.max_concurrent_queries MUST be >= 1")
        self._config = config
        self._query = query

    # ------------------------------------------------------------------
    # Inventory Protocol
    # ------------------------------------------------------------------

    async def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        """Parallel full-scan, sharded by ``resource_type``.

        Emits one :class:`InventoryBatch` per shard as its ARG query
        completes, then a final ``final=True`` fence batch the caller
        uses to atomically promote the new graph
        (``docs/roadmap/csp-neutrality.md § 5``).

        ``since`` is currently unused - the stub returns the full shard
        each call. Production may honor it as an ``since <= last_seen``
        optimization; it MUST NOT substitute for :meth:`delta`.
        """
        del since  # reserved (see docstring)

        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        async def _fetch(rt: str) -> InventoryBatch:
            async with semaphore:
                resources_raw, links_raw = await self._query(rt)
            resources = _dedupe_resources(resources_raw)
            links = _dedupe_links(links_raw)
            return InventoryBatch(resources=resources, links=links)

        tasks = [
            asyncio.create_task(_fetch(rt), name=f"arg-shard-{rt}")
            for rt in self._config.resource_types
        ]

        try:
            for coro in asyncio.as_completed(tasks):
                batch = await coro
                if batch.resources or batch.links:
                    yield batch
        except BaseException:
            # Fail-closed: cancel outstanding shards so a partial snapshot
            # never quietly lands. The caller retains the previous graph
            # because we never yielded a `final=True` batch. Await the
            # cancels so shard sockets close before the exception unwinds
            # past our generator - otherwise aiohttp / httpx warn about
            # unfinished coroutines on shutdown.
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        yield InventoryBatch(final=True)

    async def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:
        """Incremental change stream.

        P1 W-2 stub: consumes ``cursor`` (unused) and yields a single
        ``final=True`` empty batch so callers exercise the same
        atomic-promote fence as ``full_snapshot``. The real Activity-Log
        delta lands in P1 W-3.
        """
        del cursor
        yield InventoryBatch(final=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dedupe_resources(records: Iterable[ResourceRecord]) -> tuple[ResourceRecord, ...]:
    seen: dict[str, ResourceRecord] = {}
    for record in records:
        seen[record.resource_id] = record
    return tuple(seen.values())


def _dedupe_links(records: Iterable[LinkRecord]) -> tuple[LinkRecord, ...]:
    seen: dict[tuple[str, str, str], LinkRecord] = {}
    for record in records:
        seen[(record.from_id, record.link_type, record.to_id)] = record
    return tuple(seen.values())


__all__ = [
    "AzureInventoryConfig",
    "AzureResourceGraphInventory",
    "ResourceQueryFn",
]
