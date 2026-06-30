"""Property and unit tests for notifications and reminders (task 13).

- Property 45: Generating a notification creates an unread in-app entry (Req 17.3).
- Property 46: Marking a notification read is correct and idempotent (Req 17.4).
- Unit (13.5): 24h and 1h reminders fire for both the patient and the doctor,
  and are not duplicated on a subsequent dispatch (Req 17.1, 17.2).

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
from app.models.enums import (
    AppointmentStatus,
    NotificationStatus,
    SlotStatus,
    UserRole,
    UserStatus,
)
from app.services import auth_service, inapp_notification_service, reminder_service
from app.services.inapp_notification_service import REMINDER_TYPE
from app.services.notification_service import CapturingNotificationService

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _make_user(session, role=UserRole.PATIENT, *, name="User"):
    email = f"u-{uuid.uuid4().hex}@example.com"
    user = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name, role=role
    )
    if role != UserRole.PATIENT:
        user.status = UserStatus.ACTIVE
        await session.flush()
    return user

async def _make_scheduled_appointment(session, *, doctor, patient, start_dt):
    slot = AvailabilitySlot(
        doctor_id=doctor.id,
        date=start_dt.date(),
        start_time=start_dt.timetz().replace(tzinfo=None),
        end_time=(start_dt + timedelta(minutes=30)).timetz().replace(tzinfo=None),
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
        start_time=start_dt,
        end_time=start_dt + timedelta(minutes=30),
    )
    session.add(appointment)
    await session.flush()
    return appointment

@_db_required
@given(
    notif_type=st.sampled_from(["appointment_reminder", "booking", "system"]),
    payload=st.dictionaries(
        st.sampled_from(["a", "b", "kind"]),

        st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=0x9FF),
            min_size=0,
            max_size=20,
        ),
        max_size=3,
    ),
)
def test_generating_notification_creates_unread_entry(
    pg_loop, pg_sessionmaker, notif_type, payload
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                user = await _make_user(session)
                created = await inapp_notification_service.create_notification(
                    session, user_id=user.id, type=notif_type, payload=payload
                )
                assert created.status == NotificationStatus.UNREAD

                feed = await inapp_notification_service.list_notifications(
                    session, user_id=user.id
                )
                assert any(n.id == created.id for n in feed)
                assert feed[0].status == NotificationStatus.UNREAD
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(times=st.integers(min_value=1, max_value=4))
def test_mark_read_is_idempotent(pg_loop, pg_sessionmaker, times) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                user = await _make_user(session)
                created = await inapp_notification_service.create_notification(
                    session, user_id=user.id, type="system", payload=None
                )
                for _ in range(times):
                    updated = await inapp_notification_service.mark_notification_read(
                        session, notification_id=created.id, user_id=user.id
                    )
                    assert updated.status == NotificationStatus.READ
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
def test_reminders_fire_for_both_parties_and_dedupe(pg_loop, pg_sessionmaker) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                now = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
                doctor = await _make_user(session, UserRole.DOCTOR, name="Dr. Sen")
                patient = await _make_user(session, name="Mr. Khan")

                appt_24h = await _make_scheduled_appointment(
                    session, doctor=doctor, patient=patient,
                    start_dt=now + timedelta(hours=24),
                )
                appt_1h = await _make_scheduled_appointment(
                    session, doctor=doctor, patient=patient,
                    start_dt=now + timedelta(hours=1),
                )

                notifier = CapturingNotificationService()
                dispatched = await reminder_service.dispatch_due_reminders(
                    session, now=now, notifier=notifier
                )

                assert len(dispatched) == 4
                kinds = sorted(r.kind for r in dispatched)
                assert kinds == ["1h", "1h", "24h", "24h"]
                roles = sorted(r.recipient_role for r in dispatched)
                assert roles == ["doctor", "doctor", "patient", "patient"]
                assert len(notifier.reminders) == 4

                patient_feed = await inapp_notification_service.list_notifications(
                    session, user_id=patient.id
                )
                doctor_feed = await inapp_notification_service.list_notifications(
                    session, user_id=doctor.id
                )
                assert sum(n.type == REMINDER_TYPE for n in patient_feed) == 2
                assert sum(n.type == REMINDER_TYPE for n in doctor_feed) == 2

                notifier2 = CapturingNotificationService()
                again = await reminder_service.dispatch_due_reminders(
                    session, now=now, notifier=notifier2
                )
                assert again == []
                assert notifier2.reminders == []

                covered = {r for r in (str(appt_24h.id), str(appt_1h.id))}
                assert covered
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
