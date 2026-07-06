"""Alembic environment.

Migrations are **raw SQL** (no ORM model reference), so ``target_metadata``
stays ``None``. The database URL comes from the ``AIOPSPILOT_DATABASE_URL``
env var; on a fresh clone with `make dev-up` this maps to the docker-compose
pgvector service.

Only PostgreSQL is supported - the runtime `StateStore` adapter will be
psycopg-backed, so an alembic run against SQLite would silently drift.
"""

from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Load alembic.ini config (available as ``context.config``).
config = context.config

# Environment override for the database URL. Defaults to the docker-compose
# dev stack so `alembic upgrade head` works out of the box.
_DEFAULT_URL = "postgresql+psycopg://aiopspilot:devonly@localhost:5432/aiopspilot"
_url = os.environ.get("AIOPSPILOT_DATABASE_URL", _DEFAULT_URL)

if not _url.startswith(("postgresql://", "postgresql+psycopg://")):
    print(
        f"AIOPSPILOT_DATABASE_URL must be a PostgreSQL URL; got: {_url!r}",
        file=sys.stderr,
    )
    raise SystemExit(2)

config.set_main_option("sqlalchemy.url", _url)

# Migrations are raw SQL - no ORM metadata to introspect.
target_metadata = None


def run_migrations_offline() -> None:
    """Render the migrations as SQL (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Actually apply migrations against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
