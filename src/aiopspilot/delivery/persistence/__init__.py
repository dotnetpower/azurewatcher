"""Persistence adapters — CSP-neutral wire-level backends.

These modules realize :class:`~aiopspilot.shared.providers.state_store.StateStore`
against real databases (currently PostgreSQL). Postgres is not
Azure-specific — the same adapter binds to a Cloud SQL, RDS, or
self-hosted Postgres server — so it lives here rather than under
``delivery/azure/``.
"""

from __future__ import annotations

from aiopspilot.delivery.persistence.postgres import (
    PostgresStateStore,
    PostgresStateStoreConfig,
)

__all__ = ["PostgresStateStore", "PostgresStateStoreConfig"]
