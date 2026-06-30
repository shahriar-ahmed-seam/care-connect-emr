"""Dashboard_Service: aggregated data for patient, doctor, and admin dashboards.

Backs the dashboard endpoints (Requirements 14.1–14.4, 15.1–15.4, 16.1–16.2):

- **Patient** (Req 14): upcoming appointments ascending, recent prescriptions,
  vitals history; a per-appointment join flag is computed by the API layer.
- **Doctor** (Req 15): today's appointments ascending and the count of pending
  (scheduled) appointments for the current day.
- **Admin** (Req 16): counts of total patients, active doctors, and appointments
  scheduled for the current day; plus the full user list.

The join window (Req 14.3, 15.2) and counting-with-zero (Req 15.4, 16.1) are
the behaviours exercised by Properties 47–49.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.appointment import Appointment
from app.models.clinical import Prescription, Vitals
from app.models.enums import AppointmentStatus, UserRole, UserStatus
from app.models.user import User

JOIN_LEAD = timedelta(minutes=10)

def can_join(appointment: Appointment, now: datetime) -> bool:
    """Whether the join-video control should be shown for an appointment."""
    return (
        appointment.status == AppointmentStatus.SCHEDULED
        and appointment.start_time - JOIN_LEAD <= now <= appointment.end_time
    )

async def get_patient_upcoming_appointments(
    session: AsyncSession, *, patient_id: uuid.UUID, now: datetime
) -> List[Appointment]:
    """Scheduled appointments not yet ended, ordered by start time asc (Req 14.1)."""
    return list(
        (
            await session.scalars(
                select(Appointment)
                .where(
                    Appointment.patient_id == patient_id,
                    Appointment.status == AppointmentStatus.SCHEDULED,
                    Appointment.end_time >= now,
                )
                .order_by(Appointment.start_time.asc())
            )
        ).all()
    )

async def get_patient_recent_prescriptions(
    session: AsyncSession, *, patient_id: uuid.UUID, limit: int = 5
) -> List[Prescription]:
    """A patient's most recent prescriptions, newest first (Req 14.2)."""
    return list(
        (
            await session.scalars(
                select(Prescription)
                .where(Prescription.patient_id == patient_id)
                .options(selectinload(Prescription.medications))
                .order_by(Prescription.issued_at.desc())
                .limit(limit)
            )
        ).all()
    )

async def get_patient_vitals(
    session: AsyncSession, *, patient_id: uuid.UUID
) -> List[Vitals]:
    """A patient's vitals history, newest first (Req 14.4)."""
    return list(
        (
            await session.scalars(
                select(Vitals)
                .where(Vitals.patient_id == patient_id)
                .order_by(Vitals.recorded_at.desc())
            )
        ).all()
    )

def _day_bounds(now: datetime) -> Tuple[datetime, datetime]:
    """Return [start_of_day, start_of_next_day) for ``now`` (UTC)."""
    start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo or timezone.utc)
    return start, start + timedelta(days=1)

async def get_doctor_today_appointments(
    session: AsyncSession, *, doctor_id: uuid.UUID, now: datetime
) -> List[Appointment]:
    """A doctor's appointments for the current day, ordered asc (Req 15.1)."""
    day_start, day_end = _day_bounds(now)
    return list(
        (
            await session.scalars(
                select(Appointment)
                .where(
                    Appointment.doctor_id == doctor_id,
                    Appointment.start_time >= day_start,
                    Appointment.start_time < day_end,
                )
                .order_by(Appointment.start_time.asc())
            )
        ).all()
    )

async def count_doctor_pending_today(
    session: AsyncSession, *, doctor_id: uuid.UUID, now: datetime
) -> int:
    """Count of scheduled appointments today for a doctor; 0 when none (Req 15.4)."""
    day_start, day_end = _day_bounds(now)
    count = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.start_time >= day_start,
            Appointment.start_time < day_end,
        )
    )
    return int(count or 0)

async def admin_counts(
    session: AsyncSession, *, now: datetime
) -> Tuple[int, int, int]:
    """Return (total_patients, active_doctors, appointments_today) (Req 16.1)."""
    total_patients = await session.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.PATIENT)
    )
    active_doctors = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.DOCTOR, User.status == UserStatus.ACTIVE)
    )
    day_start, day_end = _day_bounds(now)
    appts_today = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.start_time >= day_start,
            Appointment.start_time < day_end,
        )
    )
    return int(total_patients or 0), int(active_doctors or 0), int(appts_today or 0)

async def list_all_users(session: AsyncSession) -> List[User]:
    """All user accounts for the Admin user list (Req 16.2 — Property 49)."""
    return list(
        (
            await session.scalars(select(User).order_by(User.created_at.asc()))
        ).all()
    )
