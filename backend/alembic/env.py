"""Alembic migration environment (async-aware).

The database URL is read exclusively from the environment (``DATABASE_URL`` or
``TEST_DATABASE_URL``); it is never hard-coded (Req 21.3, 13.6). ``target_metadata``
is bound to the ORM models' ``Base.metadata`` so autogenerate can diff the schema.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models
from app.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def _database_url() -> str:
    """Resolve the migration database URL from the environment."""
    url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL (or TEST_DATABASE_URL) must be set to run migrations; "
            "secrets are read from the environment only."
        )
    return url

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
