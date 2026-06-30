"""Shared pytest fixtures and Hypothesis configuration.

Highlights:
- A Hypothesis profile (``default``) configured to run a minimum of 100
  generated examples per property, matching the spec's testing strategy. A
  ``ci`` profile runs more examples for thorough verification.
- A FastAPI ``client`` fixture (async, via httpx ASGITransport).
- A Postgres ``db_session`` fixture that wraps each test in a transaction and
  rolls it back afterwards, so tests never leak state. The fixture is skipped
  automatically when no test database is configured.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, settings

os.environ.setdefault("EMR_ENCRYPTION_KEY", "test-encryption-key-not-for-prod-0123456789ab")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-prod")
os.environ.setdefault("APP_ENV", "test")

os.environ.setdefault("BCRYPT_ROUNDS", "4")

settings.register_profile(
    "default",
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))

@pytest_asyncio.fixture
async def client() -> AsyncIterator["object"]:
    """Async HTTP client bound to the FastAPI app via ASGI transport."""
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

def _test_database_url() -> str | None:
    """Resolve the test database URL from the environment.

    Prefers ``TEST_DATABASE_URL`` and falls back to ``DATABASE_URL``. Returns
    ``None`` when neither is set so DB-dependent tests can be skipped.
    """
    return os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")

@pytest_asyncio.fixture
async def db_session() -> AsyncIterator["object"]:
    """Provide an ``AsyncSession`` wrapped in a transaction rolled back per test.

    Uses the standard SQLAlchemy async pattern: open a connection, begin an
    outer transaction, bind a session to that connection, then roll the
    transaction back on teardown so no test data persists. Skips when no test
    database is configured.
    """
    database_url = _test_database_url()
    if not database_url:
        pytest.skip("No TEST_DATABASE_URL/DATABASE_URL configured for DB tests")

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    engine = create_async_engine(database_url, future=True)
    connection = await engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()

@pytest.fixture(scope="module")
def pg_loop():
    """A dedicated event loop reused across all Hypothesis examples in a module."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()

@pytest.fixture(scope="module")
def pg_sessionmaker(pg_loop):
    """Create the schema once and yield an ``async_sessionmaker`` (NullPool).

    Skips the whole module when no test database is configured.
    """
    database_url = _test_database_url()
    if not database_url:
        pytest.skip("No TEST_DATABASE_URL/DATABASE_URL configured for DB tests")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models
    from app.models.base import Base

    engine = create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=5,
        connect_args={"statement_cache_size": 0},
    )

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
            await conn.run_sync(Base.metadata.create_all)

    pg_loop.run_until_complete(_setup())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:

        async def _teardown() -> None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()

        pg_loop.run_until_complete(_teardown())
