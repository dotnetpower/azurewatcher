"""State store - Postgres-backed by default; DI seam for alternate backends.

Async by contract - real backends (asyncpg on PostgreSQL) are I/O bound and
would otherwise block the event loop. Only CPU / startup-only seams
(SchemaRegistry, ContractValidator, ConfigProvider) stay sync.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StateStore(Protocol):
    """Append-only audit + tracked state + KPI emission."""

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        """Append a single audit record.

        Real backends hash-chain the entry to the previous one (see
        ``security-and-identity.md § Auditability``). The Protocol only fixes
        the boundary; the chaining rule is a contract on implementations.
        """
        ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        """Return the tracked state for ``key`` or ``None`` when absent."""
        ...

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        """Persist ``value`` under ``key``.

        Semantics are idempotent by key: re-applying the same ``(key, value)``
        pair MUST NOT create duplicate history - the value replaces the prior
        state atomically.
        """
        ...


__all__ = ["StateStore"]
