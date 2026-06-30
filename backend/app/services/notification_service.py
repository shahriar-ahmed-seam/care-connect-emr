"""Minimal Notification_Service abstraction.

The full Notification_Service (in-app notification rows plus email triggers for
bookings, changes, approvals, and reminders) is implemented in a later task
(task 13). Several earlier flows, however, must already *trigger* a notification
— notably the Doctor-approval email an Admin sends when approving an account
(Requirement 4.4).

To avoid coupling those flows to an as-yet-unbuilt component, this module
defines a tiny :class:`NotificationService` protocol plus an in-memory
:class:`CapturingNotificationService` default. The capturing implementation
records the notifications it is asked to deliver (instead of dialling SMTP),
which keeps local/dev runs side-effect free and lets tests assert that the
expected notification was invoked.

Service functions accept an injectable notifier so tests can supply their own
capturing instance; the production wiring in task 13 will substitute a real
implementation that writes in-app rows and enqueues emails while satisfying this
same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable

@dataclass(frozen=True)
class DoctorApprovalNotification:
    """An approval notification destined for a newly approved Doctor (Req 4.4)."""

    to: str
    full_name: str

@dataclass(frozen=True)
class BookingConfirmationNotification:
    """A booking confirmation sent to a Patient on appointment creation (Req 6.5).

    Carries the Doctor name, the appointment date, and the time so the
    Email_Service (or any notifier) can compose a confirmation message
    addressed to the Patient's registered email.
    """

    to: str
    doctor_name: str
    date: str
    time: str

@dataclass(frozen=True)
class AppointmentChangeNotification:
    """A cancellation/reschedule notification to a participant (Req 7.4, 7.5).

    Sent to both the Patient and the Doctor when an Appointment is cancelled or
    rescheduled (Req 7.4); a Doctor-initiated cancellation notifies the Patient
    (Req 7.5). ``change_type`` is ``"cancelled"`` or ``"rescheduled"`` and
    ``recipient_role`` records whether this copy is addressed to the
    ``"patient"`` or the ``"doctor"``.
    """

    to: str
    recipient_role: str
    change_type: str
    doctor_name: str
    date: str
    time: str

@dataclass(frozen=True)
class ReminderNotification:
    """An appointment reminder sent ahead of the start time (Req 17.1, 17.2).

    ``kind`` is ``"24h"`` or ``"1h"`` and ``recipient_role`` is ``"patient"`` or
    ``"doctor"``.
    """

    to: str
    recipient_role: str
    kind: str
    doctor_name: str
    date: str
    time: str

@runtime_checkable
class NotificationService(Protocol):
    """Anything capable of delivering domain notifications.

    Only the methods needed by current flows are declared; task 13 widens this
    surface (reminder notifications and in-app rows) without breaking existing
    callers.
    """

    def send_doctor_approval(
        self, notification: DoctorApprovalNotification
    ) -> None:
        ...

    def send_booking_confirmation(
        self, notification: BookingConfirmationNotification
    ) -> None:
        ...

    def send_appointment_change(
        self, notification: AppointmentChangeNotification
    ) -> None:
        ...

    def send_reminder(
        self, notification: ReminderNotification
    ) -> None:
        ...

@dataclass
class CapturingNotificationService:
    """An in-memory notifier that records what it was asked to deliver."""

    approvals: List[DoctorApprovalNotification] = field(default_factory=list)
    bookings: List[BookingConfirmationNotification] = field(default_factory=list)
    changes: List[AppointmentChangeNotification] = field(default_factory=list)
    reminders: List[ReminderNotification] = field(default_factory=list)

    def send_doctor_approval(
        self, notification: DoctorApprovalNotification
    ) -> None:
        self.approvals.append(notification)

    def send_booking_confirmation(
        self, notification: BookingConfirmationNotification
    ) -> None:
        self.bookings.append(notification)

    def send_appointment_change(
        self, notification: AppointmentChangeNotification
    ) -> None:
        self.changes.append(notification)

    def send_reminder(self, notification: ReminderNotification) -> None:
        self.reminders.append(notification)

    def clear(self) -> None:
        self.approvals.clear()
        self.bookings.clear()
        self.changes.clear()
        self.reminders.clear()

_default_notification_service = CapturingNotificationService()

def get_notification_service() -> NotificationService:
    """Return the process-wide default Notification_Service."""
    return _default_notification_service
