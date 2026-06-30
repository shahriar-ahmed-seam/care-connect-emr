"""Async database engine and session factory.

Builds a lazily-initialised SQLAlchemy async engine and ``async_sessionmaker``
from the ``DATABASE_URL`` setting (sourced from the environment only). The
engine is created on first use so importing the application does not require a
live database — useful for unit tests that never touch the DB and for tooling.

``get_sessionmaker`` is the single entry point used by the request-scoped
``get_db`` dependency and by background workers.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not configured; cannot create a DB engine"
            )
        _engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)
    return _engine

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, creating it on first use."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False
        )
    return _sessionmaker
