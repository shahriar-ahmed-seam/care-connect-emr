"""Appointment reminder dispatch (Requirements 17.1, 17.2).

Sends reminders to both the Patient and the Doctor when an Appointment's start
time is 24 hours away and again when it is 1 hour away. Each reminder creates an
in-app notification entry (Req 17.3) and dispatches an email via the injected
Notification_Service.

:func:`dispatch_due_reminders` is a pure-ish async function (it takes the
current time and an optional notifier) so it can be unit-tested deterministically
and driven on a schedule by the background worker (APScheduler). Reminders are
de-duplicated against existing in-app notifications so overlapping scheduler
ticks do not send a reminder twice.

Functions ``flush`` their writes but do not ``commit``; the caller owns the
transaction boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.enums import AppointmentStatus
from app.models.user import User
from app.services.inapp_notification_service import (
    REMINDER_TYPE,
    create_notification,
    reminder_already_sent,
)
from app.services.notification_service import (
    NotificationService,
    ReminderNotification,
    get_notification_service,
)

REMINDER_OFFSETS = {
    "24h": timedelta(hours=24),
    "1h": timedelta(hours=1),
}

DEFAULT_WINDOW = timedelta(minutes=15)

async def dispatch_due_reminders(
    session: AsyncSession,
    *,
    now: Optional[datetime] = None,
    window: timedelta = DEFAULT_WINDOW,
    notifier: Optional[NotificationService] = None,
) -> List[ReminderNotification]:
    """Create and dispatch any reminders due as of ``now`` (Req 17.1, 17.2).

    For each reminder kind (24h, 1h), finds scheduled appointments whose start
    time falls in ``[now + offset, now + offset + window)`` and, for both the
    Patient and the Doctor, creates an unread in-app notification and dispatches
    an email — unless that reminder was already sent (de-duplicated). Returns the
    list of reminder notifications dispatched on this call.
    """
    now = now or datetime.now(timezone.utc)
    notifier = notifier or get_notification_service()
    dispatched: List[ReminderNotification] = []

    for kind, offset in REMINDER_OFFSETS.items():
        low = now + offset
        high = low + window
        appointments = (
            await session.scalars(
                select(Appointment).where(
                    Appointment.status == AppointmentStatus.SCHEDULED,
                    Appointment.start_time >= low,
                    Appointment.start_time < high,
                )
            )
        ).all()

        for appointment in appointments:
            doctor = await session.get(User, appointment.doctor_id)
            patient = await session.get(User, appointment.patient_id)
            if doctor is None or patient is None:
                continue

            date_str = appointment.start_time.strftime("%d/%m/%Y")
            time_str = appointment.start_time.strftime("%H:%M")

            for user, role in ((patient, "patient"), (doctor, "doctor")):
                if await reminder_already_sent(
                    session,
                    user_id=user.id,
                    appointment_id=appointment.id,
                    kind=kind,
                ):
                    continue

                await create_notification(
                    session,
                    user_id=user.id,
                    type=REMINDER_TYPE,
                    payload={
                        "appointment_id": str(appointment.id),
                        "kind": kind,
                        "role": role,
                        "doctor_name": doctor.full_name,
                        "date": date_str,
                        "time": time_str,
                    },
                )
                reminder = ReminderNotification(
                    to=user.email,
                    recipient_role=role,
                    kind=kind,
                    doctor_name=doctor.full_name,
                    date=date_str,
                    time=time_str,
                )
                notifier.send_reminder(reminder)
                dispatched.append(reminder)

    return dispatched
