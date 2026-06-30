"""Property tests for dashboard backend endpoints (task 14).

- Property 47: Appointment lists are ordered by start time ascending (Req 14.1, 15.1).
- Property 48: Dashboard counts equal actual entity counts, 0 when none (Req 15.4, 16.1).
- Property 49: User list reflects all accounts with required fields (Req 16.2).

DB-backed tests run against PostgreSQL via the module-scoped fixtures with
per-example rollback.
"""

from __future__ import annotations

import os
import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.models.appointment import Appointment, AvailabilitySlot
from app.models.enums import AppointmentStatus, SlotStatus, UserRole, UserStatus
from app.services import auth_service, dashboard_service

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"
_NOW = datetime(2030, 6, 1, 8, 0, tzinfo=timezone.utc)

async def _make_user(session, role=UserRole.PATIENT, *, status=None, name="User"):
    email = f"u-{uuid.uuid4().hex}@example.com"
    user = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name, role=role
    )
    if status is not None:
        user.status = status
        await session.flush()
    elif role != UserRole.PATIENT:
        user.status = UserStatus.ACTIVE
        await session.flush()
    return user

async def _make_appt(session, *, doctor, patient, start_dt, status=AppointmentStatus.SCHEDULED):
    slot = AvailabilitySlot(
        doctor_id=doctor.id,
        date=start_dt.date(),
        start_time=start_dt.time().replace(microsecond=0),
        end_time=(start_dt + timedelta(minutes=30)).time().replace(microsecond=0),
        status=SlotStatus.BOOKED,
    )
    session.add(slot)
    await session.flush()
    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        slot_id=slot.id,
        status=status,
        fee_bdt_at_booking=Decimal("500.00"),
        start_time=start_dt,
        end_time=start_dt + timedelta(minutes=30),
    )
    session.add(appt)
    await session.flush()
    return appt

def _ascending(values) -> bool:
    return all(values[i] <= values[i + 1] for i in range(len(values) - 1))

@_db_required
@given(

    patient_offsets=st.lists(
        st.integers(min_value=1, max_value=240), min_size=1, max_size=6, unique=True
    ),

    doctor_minutes=st.lists(
        st.integers(min_value=0, max_value=900), min_size=1, max_size=6, unique=True
    ),
)
def test_appointment_lists_ascending(
    pg_loop, pg_sessionmaker, patient_offsets, doctor_minutes
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_user(session, UserRole.DOCTOR, name="Dr")
                patient = await _make_user(session, name="Pat")

                for h in patient_offsets:
                    await _make_appt(
                        session, doctor=doctor, patient=patient,
                        start_dt=_NOW + timedelta(hours=h),
                    )

                upcoming = await dashboard_service.get_patient_upcoming_appointments(
                    session, patient_id=patient.id, now=_NOW
                )
                assert _ascending([a.start_time for a in upcoming])
                assert all(a.patient_id == patient.id for a in upcoming)
                assert len(upcoming) == len(patient_offsets)

                day_start = datetime(2030, 6, 1, 0, 0, tzinfo=timezone.utc)
                for m in doctor_minutes:
                    await _make_appt(
                        session, doctor=doctor, patient=patient,
                        start_dt=day_start + timedelta(minutes=m),
                    )
                today = await dashboard_service.get_doctor_today_appointments(
                    session, doctor_id=doctor.id, now=_NOW
                )
                assert _ascending([a.start_time for a in today])
                assert all(
                    a.start_time.date() == date_(2030, 6, 1) for a in today
                )
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(
    n_patients=st.integers(min_value=0, max_value=4),
    n_active_doctors=st.integers(min_value=0, max_value=4),
    n_pending_doctors=st.integers(min_value=0, max_value=3),
    n_appts_today=st.integers(min_value=0, max_value=4),
)
def test_dashboard_counts(
    pg_loop, pg_sessionmaker, n_patients, n_active_doctors,
    n_pending_doctors, n_appts_today,
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                patients = [
                    await _make_user(session, name=f"P{i}") for i in range(n_patients)
                ]
                for _ in range(n_active_doctors):
                    await _make_user(session, UserRole.DOCTOR, status=UserStatus.ACTIVE)
                for _ in range(n_pending_doctors):
                    await _make_user(session, UserRole.DOCTOR, status=UserStatus.PENDING)

                doctor = await _make_user(session, UserRole.DOCTOR, status=UserStatus.ACTIVE)
                day_start = datetime(2030, 6, 1, 0, 0, tzinfo=timezone.utc)
                if n_appts_today > 0:

                    if not patients:
                        patients = [await _make_user(session, name="Px")]
                    for i in range(n_appts_today):
                        await _make_appt(
                            session, doctor=doctor, patient=patients[0],
                            start_dt=day_start + timedelta(hours=9, minutes=i * 31),
                        )

                total_patients, active_doctors, appts_today = (
                    await dashboard_service.admin_counts(session, now=_NOW)
                )
                expected_patients = len(patients)
                assert total_patients == expected_patients

                assert active_doctors == n_active_doctors + 1
                assert appts_today == n_appts_today

                pending_today = await dashboard_service.count_doctor_pending_today(
                    session, doctor_id=doctor.id, now=_NOW
                )
                assert pending_today == n_appts_today
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(
    n_patients=st.integers(min_value=0, max_value=4),
    n_doctors=st.integers(min_value=0, max_value=4),
)
def test_admin_user_list_complete(
    pg_loop, pg_sessionmaker, n_patients, n_doctors
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                created_ids = set()
                for i in range(n_patients):
                    u = await _make_user(session, name=f"P{i}")
                    created_ids.add(u.id)
                for i in range(n_doctors):
                    u = await _make_user(session, UserRole.DOCTOR, name=f"D{i}")
                    created_ids.add(u.id)

                users = await dashboard_service.list_all_users(session)
                listed_ids = {u.id for u in users}
                assert created_ids <= listed_ids
                assert len(users) == n_patients + n_doctors

                for u in users:
                    assert u.full_name is not None and u.full_name != ""
                    assert u.email is not None and u.email != ""
                    assert u.role is not None
                    assert u.status is not None
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
