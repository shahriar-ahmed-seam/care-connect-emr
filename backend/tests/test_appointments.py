"""Property tests for appointment booking and lifecycle (tasks 8.2–8.10).

- Property 23: Doctor search returns exactly matching active doctors (Req 6.1).
- Property 24: Only future available slots are offered (Req 6.2).
- Property 25: Slot booking consistency under concurrency (Req 6.3, 6.4).
- Property 26: Booking snapshots the consultation fee (Req 6.6).
- Property 27: Cancellation honors the one-hour rule (Req 7.1, 7.2, 7.5).
- Property 28: Rescheduling conserves slot bookings (Req 7.3).

All run against a real PostgreSQL database via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures. Properties 23, 24, 26, 27, and 28 use
per-example rollback for isolation; Property 25 commits real concurrent
bookings (to exercise DB-level row locking) and cleans up afterwards.
"""

from __future__ import annotations

import asyncio
import os
import string
import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import delete, func, select

from app.core.errors import AppError
from app.models.appointment import Appointment, AvailabilitySlot
from app.models.enums import AppointmentStatus, SlotStatus, UserRole, UserStatus
from app.models.user import DoctorProfile, User
from app.services import appointment_service, auth_service, profile_service
from app.services.notification_service import CapturingNotificationService
from tests.strategies import (
    consultation_fees_bdt,
    full_names,
    searchable_specialties,
    valid_slot_intervals,
)

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _make_active_doctor(session, *, name="Dr", fee=Decimal("500.00")):
    email = f"doc-{uuid.uuid4().hex}@example.com"
    doctor = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.DOCTOR,
    )
    doctor.status = UserStatus.ACTIVE
    await session.flush()
    await profile_service.save_doctor_profile(
        session,
        doctor_id=doctor.id,
        specialty="General",
        qualifications=None,
        consultation_fee_bdt=fee,
    )
    return doctor

async def _make_patient(session, *, name="Pat"):
    email = f"pat-{uuid.uuid4().hex}@example.com"
    return await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.PATIENT,
    )

@_db_required
@given(
    docs=st.lists(
        st.tuples(searchable_specialties, st.sampled_from(list(UserStatus))),
        min_size=0,
        max_size=6,
    ),
    term=st.text(alphabet=string.ascii_letters, min_size=1, max_size=5),
)
def test_doctor_search_returns_matching_active(
    pg_loop, pg_sessionmaker, docs, term
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                expected: set = set()
                for specialty, status in docs:
                    email = f"doc-{uuid.uuid4().hex}@example.com"
                    doctor = await auth_service.register_user(
                        session, email=email, password=_PASSWORD,
                        full_name="Doc", role=UserRole.DOCTOR,
                    )
                    doctor.status = status
                    await session.flush()
                    session.add(
                        DoctorProfile(
                            user_id=doctor.id,
                            specialty=specialty,
                            qualifications=None,
                            consultation_fee_bdt=Decimal("500.00"),
                        )
                    )
                    await session.flush()
                    if status == UserStatus.ACTIVE and term.lower() in specialty.lower():
                        expected.add(doctor.id)

                results = await appointment_service.search_doctors_by_specialty(
                    session, specialty_term=term
                )
                returned = {d.id for d in results}
                assert returned == expected
                for d in results:
                    assert d.status == UserStatus.ACTIVE
                    assert term.lower() in d.doctor_profile.specialty.lower()
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(
    raw_slots=st.lists(
        st.tuples(valid_slot_intervals(), st.sampled_from(list(SlotStatus))),
        min_size=0,
        max_size=8,
    ),
)
def test_only_future_available_slots_offered(
    pg_loop, pg_sessionmaker, raw_slots
) -> None:

    now = datetime(2027, 1, 1, 12, 0, tzinfo=timezone.utc)

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                expected: set = set()
                for (sdate, start, end), status in raw_slots:
                    slot = AvailabilitySlot(
                        doctor_id=doctor.id,
                        date=sdate,
                        start_time=start,
                        end_time=end,
                        status=status,
                    )
                    session.add(slot)
                    await session.flush()
                    slot_start = datetime.combine(sdate, start, tzinfo=timezone.utc)
                    if status == SlotStatus.AVAILABLE and slot_start > now:
                        expected.add(slot.id)

                results = await appointment_service.list_future_available_slots(
                    session, doctor_id=doctor.id, now=now
                )
                returned = {s.id for s in results}
                assert returned == expected
                for s in results:
                    assert s.status == SlotStatus.AVAILABLE
                    combined = datetime.combine(
                        s.date, s.start_time, tzinfo=timezone.utc
                    )
                    assert combined > now
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, fee=consultation_fees_bdt, new_fee=consultation_fees_bdt)
def test_booking_snapshots_consultation_fee(
    pg_loop, pg_sessionmaker, name, fee, new_fee
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name, fee=fee)
                patient = await _make_patient(session)
                slot = await appointment_service.create_slot(
                    session,
                    doctor_id=doctor.id,
                    date=date_(2030, 12, 31),
                    start_time=time(9, 0),
                    end_time=time(9, 30),
                )

                notifier = CapturingNotificationService()
                appointment = await appointment_service.book_appointment(
                    session,
                    patient_id=patient.id,
                    slot_id=slot.id,
                    notifier=notifier,
                )
                quantized = fee.quantize(Decimal("0.01"))
                assert appointment.fee_bdt_at_booking == quantized

                profile = await profile_service.get_doctor_profile(
                    session, doctor_id=doctor.id
                )
                profile.consultation_fee_bdt = new_fee
                await session.flush()
                await session.refresh(appointment)
                assert appointment.fee_bdt_at_booking == quantized
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, offset_minutes=st.integers(min_value=-120, max_value=300))
def test_cancellation_honors_one_hour_rule(
    pg_loop, pg_sessionmaker, name, offset_minutes
) -> None:
    now = datetime(2027, 1, 1, 12, 0, tzinfo=timezone.utc)
    start = now + timedelta(minutes=offset_minutes)
    allowed = offset_minutes > 60

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name)
                patient = await _make_patient(session)
                slot = AvailabilitySlot(
                    doctor_id=doctor.id,
                    date=start.date(),
                    start_time=time(start.hour, start.minute),
                    end_time=time(23, 59),
                    status=SlotStatus.BOOKED,
                )
                session.add(slot)
                await session.flush()
                appointment = Appointment(
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    slot_id=slot.id,
                    status=AppointmentStatus.SCHEDULED,
                    fee_bdt_at_booking=Decimal("500.00"),
                    start_time=start,
                    end_time=start + timedelta(minutes=30),
                )
                session.add(appointment)
                await session.flush()

                notifier = CapturingNotificationService()
                if allowed:
                    result = await appointment_service.cancel_appointment(
                        session,
                        appointment_id=appointment.id,
                        actor=patient,
                        now=now,
                        notifier=notifier,
                    )
                    assert result.status == AppointmentStatus.CANCELLED
                    await session.refresh(slot)
                    assert slot.status == SlotStatus.AVAILABLE

                    assert len(notifier.changes) == 2
                else:
                    with pytest.raises(AppError) as exc:
                        await appointment_service.cancel_appointment(
                            session,
                            appointment_id=appointment.id,
                            actor=patient,
                            now=now,
                            notifier=notifier,
                        )
                    assert exc.value.code == "cancellation-too-late"
                    await session.refresh(appointment)
                    await session.refresh(slot)
                    assert appointment.status == AppointmentStatus.SCHEDULED
                    assert slot.status == SlotStatus.BOOKED
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, interval=valid_slot_intervals())
def test_rescheduling_conserves_slot_bookings(
    pg_loop, pg_sessionmaker, name, interval
) -> None:
    sdate, start, end = interval

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=name)
                patient = await _make_patient(session)

                slot_a = await appointment_service.create_slot(
                    session,
                    doctor_id=doctor.id,
                    date=sdate,
                    start_time=start,
                    end_time=end,
                )

                slot_b = await appointment_service.create_slot(
                    session,
                    doctor_id=doctor.id,
                    date=sdate + timedelta(days=1),
                    start_time=start,
                    end_time=end,
                )

                notifier = CapturingNotificationService()
                appointment = await appointment_service.book_appointment(
                    session,
                    patient_id=patient.id,
                    slot_id=slot_a.id,
                    notifier=notifier,
                )

                async def booked_count() -> int:
                    return await session.scalar(
                        select(func.count())
                        .select_from(AvailabilitySlot)
                        .where(
                            AvailabilitySlot.doctor_id == doctor.id,
                            AvailabilitySlot.status == SlotStatus.BOOKED,
                        )
                    )

                before = await booked_count()
                assert before == 1

                result = await appointment_service.reschedule_appointment(
                    session,
                    appointment_id=appointment.id,
                    new_slot_id=slot_b.id,
                    actor=patient,
                    notifier=notifier,
                )

                after = await booked_count()
                assert after == before

                assert result.slot_id == slot_b.id
                await session.refresh(slot_a)
                await session.refresh(slot_b)
                assert slot_a.status == SlotStatus.AVAILABLE
                assert slot_b.status == SlotStatus.BOOKED

                assert len(notifier.changes) == 2
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(name=full_names, n_patients=st.integers(min_value=2, max_value=4))
def test_slot_booking_consistency_under_concurrency(
    pg_loop, pg_sessionmaker, name, n_patients
) -> None:
    async def scenario() -> None:

        async with pg_sessionmaker() as session:
            doctor = await _make_active_doctor(session, name=name)
            slot = await appointment_service.create_slot(
                session,
                doctor_id=doctor.id,
                date=date_(2030, 12, 31),
                start_time=time(9, 0),
                end_time=time(9, 30),
            )
            patient_ids = []
            for _ in range(n_patients):
                patient = await _make_patient(session)
                patient_ids.append(patient.id)
            slot_id = slot.id
            doctor_id = doctor.id
            user_ids = [doctor_id, *patient_ids]
            await session.commit()

        async def attempt(patient_id) -> bool:
            async with pg_sessionmaker() as s:
                try:
                    await appointment_service.book_appointment(
                        s,
                        patient_id=patient_id,
                        slot_id=slot_id,
                        notifier=CapturingNotificationService(),
                    )
                    await s.commit()
                    return True
                except AppError as exc:
                    await s.rollback()
                    assert exc.code == "slot-unavailable"
                    return False

        try:
            results = await asyncio.gather(
                *[attempt(pid) for pid in patient_ids]
            )

            assert sum(1 for r in results if r) == 1

            async with pg_sessionmaker() as session:

                booked = await session.get(AvailabilitySlot, slot_id)
                assert booked.status == SlotStatus.BOOKED
                appt_count = await session.scalar(
                    select(func.count())
                    .select_from(Appointment)
                    .where(Appointment.slot_id == slot_id)
                )
                assert appt_count == 1
        finally:

            async with pg_sessionmaker() as session:
                await session.execute(
                    delete(Appointment).where(Appointment.slot_id == slot_id)
                )
                await session.execute(
                    delete(AvailabilitySlot).where(AvailabilitySlot.id == slot_id)
                )
                await session.execute(
                    delete(DoctorProfile).where(
                        DoctorProfile.user_id == doctor_id
                    )
                )
                await session.execute(
                    delete(User).where(User.id.in_(user_ids))
                )
                await session.commit()

    pg_loop.run_until_complete(scenario())
