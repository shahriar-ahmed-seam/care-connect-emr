"""Unit tests for booking and change notifications (task 8.11).

Verify the Notification_Service is invoked correctly for the appointment
lifecycle:

- Booking confirmation includes the Doctor name, date, and time, sent to the
  Patient's registered email (Req 6.5).
- Cancellation and rescheduling notify both the Patient and the Doctor
  (Req 7.4); a Doctor-initiated cancellation notifies the Patient (Req 7.5).

These run against a real PostgreSQL database via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures with per-test rollback, using a
CapturingNotificationService to assert side effects.
"""

from __future__ import annotations

import os
import uuid
from datetime import date as date_, datetime, time, timezone
from decimal import Decimal

import pytest

from app.models.enums import UserRole, UserStatus
from app.services import appointment_service, auth_service, profile_service
from app.services.notification_service import CapturingNotificationService

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _setup_doctor_patient(session, *, fee=Decimal("750.00")):
    doctor = await auth_service.register_user(
        session, email=f"doc-{uuid.uuid4().hex}@example.com", password=_PASSWORD,
        full_name="Dr Rahman", role=UserRole.DOCTOR,
    )
    doctor.status = UserStatus.ACTIVE
    await session.flush()
    await profile_service.save_doctor_profile(
        session, doctor_id=doctor.id, specialty="Cardiology",
        qualifications="MBBS", consultation_fee_bdt=fee,
    )
    patient = await auth_service.register_user(
        session, email=f"pat-{uuid.uuid4().hex}@example.com", password=_PASSWORD,
        full_name="Ayesha", role=UserRole.PATIENT,
    )
    return doctor, patient

@_db_required
def test_booking_confirmation_includes_doctor_date_time(
    pg_loop, pg_sessionmaker
) -> None:
    """A booking confirmation carries doctor name, date, and time (Req 6.5)."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor, patient = await _setup_doctor_patient(session)
                slot = await appointment_service.create_slot(
                    session, doctor_id=doctor.id, date=date_(2030, 12, 31),
                    start_time=time(14, 30), end_time=time(15, 0),
                )
                notifier = CapturingNotificationService()
                await appointment_service.book_appointment(
                    session, patient_id=patient.id, slot_id=slot.id,
                    notifier=notifier,
                )

                assert len(notifier.bookings) == 1
                confirmation = notifier.bookings[0]
                assert confirmation.to == patient.email
                assert confirmation.doctor_name == "Dr Rahman"
                assert confirmation.date == "2030-12-31"
                assert confirmation.time == "14:30"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
def test_patient_cancellation_notifies_both_parties(
    pg_loop, pg_sessionmaker
) -> None:
    """A Patient cancellation notifies both the Patient and the Doctor (Req 7.4)."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor, patient = await _setup_doctor_patient(session)
                slot = await appointment_service.create_slot(
                    session, doctor_id=doctor.id, date=date_(2030, 12, 31),
                    start_time=time(9, 0), end_time=time(9, 30),
                )
                notifier = CapturingNotificationService()
                appointment = await appointment_service.book_appointment(
                    session, patient_id=patient.id, slot_id=slot.id,
                    notifier=notifier,
                )

                notifier.clear()

                now = datetime(2030, 12, 31, 0, 0, tzinfo=timezone.utc)
                await appointment_service.cancel_appointment(
                    session, appointment_id=appointment.id, actor=patient,
                    now=now, notifier=notifier,
                )

                assert len(notifier.changes) == 2
                recipients = {c.recipient_role: c for c in notifier.changes}
                assert recipients["patient"].to == patient.email
                assert recipients["doctor"].to == doctor.email
                assert all(c.change_type == "cancelled" for c in notifier.changes)
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
def test_doctor_cancellation_notifies_patient(pg_loop, pg_sessionmaker) -> None:
    """A Doctor-initiated cancellation notifies the Patient (Req 7.5)."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor, patient = await _setup_doctor_patient(session)
                slot = await appointment_service.create_slot(
                    session, doctor_id=doctor.id, date=date_(2030, 12, 31),
                    start_time=time(9, 0), end_time=time(9, 30),
                )
                notifier = CapturingNotificationService()
                appointment = await appointment_service.book_appointment(
                    session, patient_id=patient.id, slot_id=slot.id,
                    notifier=notifier,
                )

                notifier.clear()

                now = datetime(2030, 12, 31, 8, 45, tzinfo=timezone.utc)
                await appointment_service.cancel_appointment(
                    session, appointment_id=appointment.id, actor=doctor,
                    now=now, notifier=notifier,
                )

                patient_notes = [
                    c for c in notifier.changes if c.recipient_role == "patient"
                ]
                assert len(patient_notes) == 1
                assert patient_notes[0].to == patient.email
                assert patient_notes[0].change_type == "cancelled"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
def test_reschedule_notifies_both_parties(pg_loop, pg_sessionmaker) -> None:
    """Rescheduling notifies both the Patient and the Doctor (Req 7.4)."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor, patient = await _setup_doctor_patient(session)
                slot_a = await appointment_service.create_slot(
                    session, doctor_id=doctor.id, date=date_(2030, 12, 30),
                    start_time=time(9, 0), end_time=time(9, 30),
                )
                slot_b = await appointment_service.create_slot(
                    session, doctor_id=doctor.id, date=date_(2030, 12, 31),
                    start_time=time(10, 0), end_time=time(10, 30),
                )
                notifier = CapturingNotificationService()
                appointment = await appointment_service.book_appointment(
                    session, patient_id=patient.id, slot_id=slot_a.id,
                    notifier=notifier,
                )

                notifier.clear()
                await appointment_service.reschedule_appointment(
                    session, appointment_id=appointment.id,
                    new_slot_id=slot_b.id, actor=patient, notifier=notifier,
                )

                assert len(notifier.changes) == 2
                recipients = {c.recipient_role: c for c in notifier.changes}
                assert recipients["patient"].to == patient.email
                assert recipients["doctor"].to == doctor.email
                assert all(
                    c.change_type == "rescheduled" for c in notifier.changes
                )
                assert recipients["patient"].date == "2030-12-31"
                assert recipients["patient"].time == "10:00"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
