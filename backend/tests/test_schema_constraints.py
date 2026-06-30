"""DB-level schema constraint tests (task 3.3).

These verify two database-enforced invariants from the design:

- ``users.email`` is a case-insensitive ``citext`` UNIQUE column, so duplicate
  registrations (including case variants) are rejected at the DB level
  (Requirements 1.2, 1.4).
- ``availability_slots`` carries a CHECK constraint ``start_time < end_time``,
  so a slot whose start is at or after its end is rejected (Requirement 5.3).

They exercise the real PostgreSQL schema (created from the ORM metadata) rather
than application logic, so a Postgres database is required. When neither
``TEST_DATABASE_URL`` nor ``DATABASE_URL`` is configured the whole module is
skipped, consistent with the shared ``db_session`` fixture.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, time
from decimal import Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _DB_URL,
    reason="No TEST_DATABASE_URL/DATABASE_URL configured for DB schema tests",
)

@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator["object"]:
    """Create the full schema on a fresh engine and yield a session factory.

    The schema is built from ``Base.metadata`` (the same metadata Alembic uses)
    after ensuring the ``citext`` extension exists. Each test obtains its own
    session(s) from the factory so a constraint violation in one transaction
    does not poison another. The schema is dropped on teardown.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models
    from app.models.base import Base

    engine = create_async_engine(_DB_URL)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

def _make_user(email: str):
    from app.models import User, UserRole, UserStatus

    return User(
        email=email,
        password_hash="not-a-real-hash",
        full_name="Test User",
        role=UserRole.PATIENT,
        status=UserStatus.ACTIVE,
    )

async def _insert_doctor(session_factory) -> uuid.UUID:
    """Insert a doctor user and return its id (FK target for slots)."""
    from app.models import User, UserRole, UserStatus

    doctor_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            User(
                id=doctor_id,
                email=f"doctor-{doctor_id}@example.com",
                password_hash="not-a-real-hash",
                full_name="Dr. Test",
                role=UserRole.DOCTOR,
                status=UserStatus.ACTIVE,
            )
        )
        await session.commit()
    return doctor_id

@pytest.mark.asyncio
async def test_duplicate_email_is_rejected(session_factory) -> None:
    """A second account with the same email violates the UNIQUE constraint."""
    from sqlalchemy.exc import IntegrityError

    async with session_factory() as session:
        session.add(_make_user("patient@example.com"))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_make_user("patient@example.com"))
            await session.commit()

@pytest.mark.asyncio
async def test_duplicate_email_is_case_insensitive(session_factory) -> None:
    """citext makes the UNIQUE email constraint case-insensitive (Req 1.2)."""
    from sqlalchemy.exc import IntegrityError

    async with session_factory() as session:
        session.add(_make_user("Patient@Example.com"))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_make_user("patient@example.COM"))
            await session.commit()

@pytest.mark.asyncio
async def test_slot_start_after_end_is_rejected(session_factory) -> None:
    """A slot whose start is later than its end violates the CHECK (Req 5.3)."""
    from sqlalchemy.exc import IntegrityError

    from app.models import AvailabilitySlot, SlotStatus

    doctor_id = await _insert_doctor(session_factory)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                AvailabilitySlot(
                    doctor_id=doctor_id,
                    date=date(2025, 1, 1),
                    start_time=time(15, 0),
                    end_time=time(14, 0),
                    status=SlotStatus.AVAILABLE,
                )
            )
            await session.commit()

@pytest.mark.asyncio
async def test_slot_equal_start_end_is_rejected(session_factory) -> None:
    """A zero-length slot (start == end) is rejected by the CHECK (Req 5.3)."""
    from sqlalchemy.exc import IntegrityError

    from app.models import AvailabilitySlot, SlotStatus

    doctor_id = await _insert_doctor(session_factory)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                AvailabilitySlot(
                    doctor_id=doctor_id,
                    date=date(2025, 1, 1),
                    start_time=time(14, 0),
                    end_time=time(14, 0),
                    status=SlotStatus.AVAILABLE,
                )
            )
            await session.commit()

@pytest.mark.asyncio
async def test_valid_slot_is_accepted(session_factory) -> None:
    """A slot whose start precedes its end is stored successfully (Req 5.2)."""
    from sqlalchemy import select

    from app.models import AvailabilitySlot, SlotStatus

    doctor_id = await _insert_doctor(session_factory)

    async with session_factory() as session:
        slot = AvailabilitySlot(
            doctor_id=doctor_id,
            date=date(2025, 1, 1),
            start_time=time(9, 0),
            end_time=time(9, 30),
            status=SlotStatus.AVAILABLE,
        )
        session.add(slot)
        await session.commit()

    async with session_factory() as session:
        stored = (await session.execute(select(AvailabilitySlot))).scalars().all()
        assert len(stored) == 1
        assert stored[0].status == SlotStatus.AVAILABLE
