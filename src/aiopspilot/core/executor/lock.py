"""Per-resource lock manager for the executor.

Multiple concurrent events may target the same resource — a rotate-secret
action and a right-size action on the same Container App, say. Applying
them in parallel would violate the ordering rule in
``architecture.instructions.md § Idempotency, Ordering, and Replay``:

> Events that mutate the same resource are serialized on a per-resource
> key; concurrent actions on one resource are mutually excluded.

Design
------

- One :class:`asyncio.Lock` per ``resource_id``, created lazily.
- Locks stay in-process; horizontal scaling requires the executor to be
  bounded to a single replica or to use a distributed lock (out of scope
  for P1).
- The manager MUST be safe to reuse across concurrent tasks — the
  per-resource-id dictionary itself is guarded by an internal lock.
- Locks are held for the *duration of the action*; short critical
  sections keep the throughput acceptable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ResourceLockManager:
    """Serialize actions per-resource in-process.

    Not persistent — a process restart forgets in-flight locks. That is
    acceptable because the audit log records every action; a replayed
    event acquires the lock and dedupes on ``idempotency_key`` before
    doing any work.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def _get(self, resource_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = self._locks.get(resource_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[resource_id] = lock
            return lock

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        """Hold the lock for ``resource_id`` until the ``async with`` exits."""
        lock = await self._get(resource_id)
        async with lock:
            yield

    def snapshot(self) -> dict[str, bool]:
        """Test-only helper: which resource ids are currently locked."""
        return {rid: lock.locked() for rid, lock in self._locks.items()}


__all__ = ["ResourceLockManager"]
