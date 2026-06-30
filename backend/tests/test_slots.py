"""Property tests for Doctor availability slots (tasks 7.4–7.7).

- Property 19: Valid slots are stored as available (Req 5.2).
- Property 20: Invalid slot start/end is rejected (Req 5.3).
- Property 21: Overlapping slots are rejected without mutation (Req 5.4).
- Property 22: Slot removal respects bookings (Req 5.5, 5.6).

All run against a real PostgreSQL database via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures, with per-example rollback.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given

from app.core.errors import AppError
from app.models.appointment import Appointment, AvailabilitySlot
from app.models.enums import (
    AppointmentStatus,
    SlotStatus,
    UserRole,
    UserStatus,
)
from app.services import appointment_service, auth_service
from sqlalchemy import func, select
from tests.strategies import (
    full_names,
    invalid_slot_intervals,
    valid_slot_intervals,
)

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _make_active_doctor(session, *, email="doc@example.com", name="Dr"):
    doctor = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.DOCTOR,
    )
    doctor.status = UserStatus.ACTIVE
    await session.flush()
    return doctor

async def _make_patient(session, *, email="patient@example.com", name="Pat"):
    return await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.PATIENT,
    )

async def _count_slots(session, doctor_id) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(AvailabilitySlot)
        .where(AvailabilitySlot.doctor_id == doctor_id)
    )

@_db_required
@given(name=full_names, interval=valid_slot_intervals())
def test_valid_slots_stored_as_available(
    pg_loop, pg_sessionmaker, name, interval
) -> None:
    date, start, end = interval

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name)
                slot = await appointment_service.create_slot(
                    session,
                    doctor_id=doctor.id,
                    date=date,
                    start_time=start,
                    end_time=end,
                )
                assert slot.status == SlotStatus.AVAILABLE

                await session.refresh(slot)
                assert slot.status == SlotStatus.AVAILABLE
                assert slot.date == date
                assert slot.start_time == start
                assert slot.end_time == end
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, interval=invalid_slot_intervals())
def test_invalid_slot_start_end_rejected(
    pg_loop, pg_sessionmaker, name, interval
) -> None:
    date, start, end = interval
    assert start >= end

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name)
                with pytest.raises(AppError) as exc:
                    await appointment_service.create_slot(
                        session,
                        doctor_id=doctor.id,
                        date=date,
                        start_time=start,
                        end_time=end,
                    )
                assert exc.value.code == "slot-invalid-times"

                assert await _count_slots(session, doctor.id) == 0
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, interval=valid_slot_intervals())
def test_overlapping_slots_rejected_without_mutation(
    pg_loop, pg_sessionmaker, name, interval
) -> None:
    date, start, end = interval

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name)

                first = await appointment_service.create_slot(
                    session,
                    doctor_id=doctor.id,
                    date=date,
                    start_time=start,
                    end_time=end,
                )
                before = await _count_slots(session, doctor.id)
                assert before == 1

                with pytest.raises(AppError) as exc:
                    await appointment_service.create_slot(
                        session,
                        doctor_id=doctor.id,
                        date=date,
                        start_time=start,
                        end_time=end,
                    )
                assert exc.value.code == "slot-overlap"

                after = await _count_slots(session, doctor.id)
                assert after == before

                remaining = (
                    await session.scalars(
                        select(AvailabilitySlot).where(
                            AvailabilitySlot.doctor_id == doctor.id
                        )
                    )
                ).all()
                assert len(remaining) == 1
                assert remaining[0].id == first.id
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, interval=valid_slot_intervals())
def test_slot_removal_respects_bookings(
    pg_loop, pg_sessionmaker, name, interval
) -> None:
    date, start, end = interval

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name)
                patient = await _make_patient(session)

                unbooked = await appointment_service.create_slot(
                    session,
                    doctor_id=doctor.id,
                    date=date,
                    start_time=start,
                    end_time=end,
                )
                await appointment_service.remove_slot(
                    session, doctor_id=doctor.id, slot_id=unbooked.id
                )
                assert await session.get(AvailabilitySlot, unbooked.id) is None

                booked = AvailabilitySlot(
                    doctor_id=doctor.id,
                    date=date,
                    start_time=time(9, 0),
                    end_time=time(9, 30),
                    status=SlotStatus.BOOKED,
                )
                session.add(booked)
                await session.flush()

                appt_start = datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc)
                session.add(
                    Appointment(
                        patient_id=patient.id,
                        doctor_id=doctor.id,
                        slot_id=booked.id,
                        status=AppointmentStatus.SCHEDULED,
                        fee_bdt_at_booking=Decimal("500.00"),
                        start_time=appt_start,
                        end_time=appt_start + timedelta(minutes=30),
                    )
                )
                await session.flush()

                with pytest.raises(AppError) as exc:
                    await appointment_service.remove_slot(
                        session, doctor_id=doctor.id, slot_id=booked.id
                    )
                assert exc.value.code == "slot-has-booking"

                assert await session.get(AvailabilitySlot, booked.id) is not None
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
