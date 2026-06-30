"""Appointment_Service: availability slots, search, booking, and lifecycle.

This module implements the Doctor-side availability operations and the
Patient-facing booking lifecycle behind the appointment endpoints.

Slot management (Requirements 5.2–5.6 — tasks 7.x):

- **Create** rejects start>=end and overlaps without mutation, else stores
  ``available``.
- **Remove** deletes an unbooked slot and rejects a booked one.

Search, listing, booking, and lifecycle (Requirements 6.1–6.6, 7.1–7.5 —
task 8):

- **Search** (Req 6.1): :func:`search_doctors_by_specialty` returns exactly the
  active Doctors whose specialty matches the search term (Property 23).
- **Future slots** (Req 6.2): :func:`list_future_available_slots` returns only
  ``available`` slots whose start time is later than now (Property 24).
- **Booking** (Req 6.3–6.6): :func:`book_appointment` claims a slot atomically
  (``SELECT ... FOR UPDATE`` then a conditional ``UPDATE ... WHERE
  status='available'``); a zero-row claim is rejected as ``slot-unavailable``
  so a slot is booked at most once even under concurrency (Property 25). The
  Doctor's consultation fee is snapshotted onto the Appointment (Property 26)
  and a booking confirmation is sent (Req 6.5).
- **Cancellation** (Req 7.1, 7.2, 7.5): :func:`cancel_appointment` honours the
  one-hour rule for Patients (Property 27), frees the slot, and notifies both
  parties.
- **Rescheduling** (Req 7.3): :func:`reschedule_appointment` moves an
  Appointment to another available slot of the same Doctor, conserving the
  count of booked slots (Property 28), and notifies both parties.

Functions ``flush`` their writes but do not ``commit``; the caller owns the
transaction boundary.
"""

from __future__ import annotations

import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import status as http_status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models.appointment import Appointment, AvailabilitySlot
from app.models.enums import AppointmentStatus, SlotStatus, UserRole, UserStatus
from app.models.user import DoctorProfile, User
from app.services import profile_service
from app.services.notification_service import (
    AppointmentChangeNotification,
    BookingConfirmationNotification,
    NotificationService,
    get_notification_service,
)

CANCELLATION_CUTOFF = timedelta(hours=1)

def _times_overlap(
    start_a: time, end_a: time, start_b: time, end_b: time
) -> bool:
    """Return ``True`` iff two half-open time intervals overlap.

    Intervals are treated as ``[start, end)`` so back-to-back slots (one ending
    exactly when the next begins) do not overlap.
    """
    return start_a < end_b and start_b < end_a

async def list_slots(
    session: AsyncSession, *, doctor_id: uuid.UUID
) -> List[AvailabilitySlot]:
    """Return all of a Doctor's slots ordered by date then start time."""
    rows = await session.scalars(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.doctor_id == doctor_id)
        .order_by(
            AvailabilitySlot.date.asc(),
            AvailabilitySlot.start_time.asc(),
        )
    )
    return list(rows.all())

async def create_slot(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    date: date_,
    start_time: time,
    end_time: time,
) -> AvailabilitySlot:
    """Create an availability slot for a Doctor (Req 5.2–5.4).

    Validates the time ordering (Req 5.3) and non-overlap against the Doctor's
    existing slots on the same date (Req 5.4) *before* inserting, so a rejected
    slot never mutates stored state (Property 21). A valid slot is stored with
    status ``available`` (Property 19).
    """
    if start_time >= end_time:
        raise AppError(
            "slot-invalid-times",
            "The start time must precede the end time.",
            status_code=http_status.HTTP_400_BAD_REQUEST,
            field="start_time",
        )

    existing = await session.scalars(
        select(AvailabilitySlot).where(
            AvailabilitySlot.doctor_id == doctor_id,
            AvailabilitySlot.date == date,
        )
    )
    for slot in existing.all():
        if _times_overlap(start_time, end_time, slot.start_time, slot.end_time):
            raise AppError(
                "slot-overlap",
                "The slot overlaps an existing slot.",
                status_code=http_status.HTTP_409_CONFLICT,
            )

    slot = AvailabilitySlot(
        doctor_id=doctor_id,
        date=date,
        start_time=start_time,
        end_time=end_time,
        status=SlotStatus.AVAILABLE,
    )
    session.add(slot)
    await session.flush()
    return slot

async def _slot_has_booking(
    session: AsyncSession, slot: AvailabilitySlot
) -> bool:
    """Return ``True`` iff the slot is booked by a non-cancelled Appointment.

    A slot is considered booked when its status is ``booked`` or when an
    Appointment references it whose status is ``scheduled`` or ``completed``.
    Cancelled appointments release the slot and do not block removal.
    """
    if slot.status == SlotStatus.BOOKED:
        return True
    appointment_id = await session.scalar(
        select(Appointment.id).where(
            Appointment.slot_id == slot.id,
            Appointment.status.in_(
                (AppointmentStatus.SCHEDULED, AppointmentStatus.COMPLETED)
            ),
        )
    )
    return appointment_id is not None

async def remove_slot(
    session: AsyncSession, *, doctor_id: uuid.UUID, slot_id: uuid.UUID
) -> None:
    """Remove one of a Doctor's availability slots (Req 5.5, 5.6 — Property 22).

    Deletes the slot when it has no booked Appointment (Req 5.5). If the slot is
    booked, the removal is rejected and the slot is left intact (Req 5.6). A slot
    that does not exist (or belongs to another Doctor) yields a not-found error.
    """
    slot = await session.get(AvailabilitySlot, slot_id)
    if slot is None or slot.doctor_id != doctor_id:
        raise AppError(
            "slot-not-found",
            "No such availability slot.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    if await _slot_has_booking(session, slot):
        raise AppError(
            "slot-has-booking",
            "This slot has a booked appointment and cannot be removed.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    await session.delete(slot)
    await session.flush()

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _slot_start_datetime(slot: AvailabilitySlot) -> datetime:
    """Combine a slot's date and start time into a UTC-aware datetime."""
    return datetime.combine(slot.date, slot.start_time, tzinfo=timezone.utc)

def _slot_end_datetime(slot: AvailabilitySlot) -> datetime:
    """Combine a slot's date and end time into a UTC-aware datetime."""
    return datetime.combine(slot.date, slot.end_time, tzinfo=timezone.utc)

def _fmt_date(slot: AvailabilitySlot) -> str:
    return slot.date.isoformat()

def _fmt_time(slot: AvailabilitySlot) -> str:
    return slot.start_time.strftime("%H:%M")

async def search_doctors_by_specialty(
    session: AsyncSession, *, specialty_term: str
) -> List[User]:
    """Return active Doctors whose specialty matches ``specialty_term`` (Req 6.1).

    Matching is case-insensitive substring containment against the Doctor's
    profile specialty. Only accounts with the Doctor role *and* an ``active``
    status are returned — pending, rejected, and inactive Doctors are excluded —
    which is exactly the set Property 23 checks. Each returned Doctor has its
    profile eagerly loaded so callers can render the specialty/fee without a
    lazy async access. Results are ordered by name for stable presentation.
    """
    term = specialty_term.strip()

    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = await session.scalars(
        select(User)
        .join(DoctorProfile, DoctorProfile.user_id == User.id)
        .where(
            User.role == UserRole.DOCTOR,
            User.status == UserStatus.ACTIVE,
            DoctorProfile.specialty.ilike(f"%{escaped}%", escape="\\"),
        )
        .options(selectinload(User.doctor_profile))
        .order_by(User.full_name.asc(), User.id.asc())
    )
    return list(rows.all())

async def list_future_available_slots(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    now: Optional[datetime] = None,
) -> List[AvailabilitySlot]:
    """Return a Doctor's ``available`` slots that start later than now (Req 6.2).

    A slot is offered iff its status is ``available`` *and* its start datetime
    (date combined with start time) is strictly later than the current time
    (Property 24). Results are ordered by date then start time.
    """
    current = now or _now_utc()
    rows = await session.scalars(
        select(AvailabilitySlot)
        .where(
            AvailabilitySlot.doctor_id == doctor_id,
            AvailabilitySlot.status == SlotStatus.AVAILABLE,
        )
        .order_by(
            AvailabilitySlot.date.asc(),
            AvailabilitySlot.start_time.asc(),
        )
    )
    return [slot for slot in rows.all() if _slot_start_datetime(slot) > current]

async def _claim_slot(
    session: AsyncSession, *, slot_id: uuid.UUID
) -> AvailabilitySlot:
    """Atomically claim an available slot, returning the locked slot.

    Locks the slot row with ``SELECT ... FOR UPDATE`` and then performs a
    conditional ``UPDATE ... SET status='booked' WHERE id=:id AND
    status='available'``. A zero-row result means the slot was already taken
    (or never existed) and is rejected as ``slot-unavailable`` — this is what
    guarantees a slot is booked at most once under concurrency (Property 25).
    """
    slot = await session.scalar(
        select(AvailabilitySlot)
        .where(AvailabilitySlot.id == slot_id)
        .with_for_update()
    )
    if slot is None:
        raise AppError(
            "slot-unavailable",
            "That time slot is no longer available.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    result = await session.execute(
        update(AvailabilitySlot)
        .where(
            AvailabilitySlot.id == slot_id,
            AvailabilitySlot.status == SlotStatus.AVAILABLE,
        )
        .values(status=SlotStatus.BOOKED)
    )
    if result.rowcount == 0:
        raise AppError(
            "slot-unavailable",
            "That time slot is no longer available.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    await session.refresh(slot)
    return slot

async def book_appointment(
    session: AsyncSession,
    *,
    patient_id: uuid.UUID,
    slot_id: uuid.UUID,
    now: Optional[datetime] = None,
    notifier: Optional[NotificationService] = None,
) -> Appointment:
    """Book an available slot, creating a scheduled Appointment (Req 6.3–6.6).

    Claims the slot atomically (Property 25), snapshots the Doctor's
    consultation fee onto the Appointment (Req 6.6 — Property 26), records the
    start/end times from the slot, and sends a booking confirmation containing
    the Doctor name, date, and time to the Patient (Req 6.5). The Appointment is
    created with status ``scheduled`` (Req 6.3) and the slot is marked
    unavailable by the atomic claim.
    """
    slot = await _claim_slot(session, slot_id=slot_id)

    profile = await profile_service.get_doctor_profile(
        session, doctor_id=slot.doctor_id
    )
    if profile is None:
        raise AppError(
            "doctor-profile-missing",
            "This Doctor has not completed their profile.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        status=AppointmentStatus.SCHEDULED,
        fee_bdt_at_booking=profile.consultation_fee_bdt,
        start_time=_slot_start_datetime(slot),
        end_time=_slot_end_datetime(slot),
    )
    session.add(appointment)
    await session.flush()

    patient = await session.get(User, patient_id)
    doctor = await session.get(User, slot.doctor_id)
    sender = notifier or get_notification_service()
    if patient is not None and doctor is not None:
        sender.send_booking_confirmation(
            BookingConfirmationNotification(
                to=patient.email,
                doctor_name=doctor.full_name,
                date=_fmt_date(slot),
                time=_fmt_time(slot),
            )
        )
    return appointment

async def _load_scheduled_appointment(
    session: AsyncSession, appointment_id: uuid.UUID
) -> Appointment:
    appointment = await session.get(
        Appointment,
        appointment_id,
        options=[
            selectinload(Appointment.slot),
            selectinload(Appointment.patient),
            selectinload(Appointment.doctor),
        ],
    )
    if appointment is None:
        raise AppError(
            "appointment-not-found",
            "No such appointment.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    if appointment.status != AppointmentStatus.SCHEDULED:
        raise AppError(
            "appointment-not-scheduled",
            "Only a scheduled appointment can be changed.",
            status_code=http_status.HTTP_409_CONFLICT,
        )
    return appointment

def _notify_change(
    sender: NotificationService,
    appointment: Appointment,
    slot: AvailabilitySlot,
    change_type: str,
) -> None:
    """Notify both the Patient and the Doctor of a change (Req 7.4, 7.5)."""
    doctor_name = appointment.doctor.full_name
    date = _fmt_date(slot)
    time_str = _fmt_time(slot)
    sender.send_appointment_change(
        AppointmentChangeNotification(
            to=appointment.patient.email,
            recipient_role="patient",
            change_type=change_type,
            doctor_name=doctor_name,
            date=date,
            time=time_str,
        )
    )
    sender.send_appointment_change(
        AppointmentChangeNotification(
            to=appointment.doctor.email,
            recipient_role="doctor",
            change_type=change_type,
            doctor_name=doctor_name,
            date=date,
            time=time_str,
        )
    )

async def cancel_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    actor: User,
    now: Optional[datetime] = None,
    notifier: Optional[NotificationService] = None,
) -> Appointment:
    """Cancel a scheduled Appointment (Req 7.1, 7.2, 7.5 — Property 27).

    A Patient may cancel only when the start time is more than one hour in the
    future; a cancellation within one hour is rejected as ``cancellation-too-
    late`` and the Appointment is left unchanged (Req 7.1, 7.2). A Doctor may
    cancel a scheduled Appointment at any time (Req 7.5). On success the
    Appointment becomes ``cancelled``, the associated slot is freed
    (``available``), and both parties are notified (Req 7.4, 7.5).

    The ``actor`` must be the Appointment's Patient or Doctor; anyone else is
    denied with an authorization error.
    """
    current = now or _now_utc()
    appointment = await _load_scheduled_appointment(session, appointment_id)

    is_patient = actor.id == appointment.patient_id
    is_doctor = actor.id == appointment.doctor_id
    if not (is_patient or is_doctor):
        raise AppError(
            "authorization-error",
            "You may only cancel your own appointments.",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )

    if is_patient and not is_doctor:
        if appointment.start_time <= current + CANCELLATION_CUTOFF:
            raise AppError(
                "cancellation-too-late",
                "Cancellations are not permitted within 1 hour of the start "
                "time.",
                status_code=http_status.HTTP_409_CONFLICT,
            )

    appointment.status = AppointmentStatus.CANCELLED
    slot = appointment.slot
    if slot is not None:
        slot.status = SlotStatus.AVAILABLE
    await session.flush()

    sender = notifier or get_notification_service()
    if slot is not None:
        _notify_change(sender, appointment, slot, "cancelled")
    return appointment

async def reschedule_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    new_slot_id: uuid.UUID,
    actor: User,
    now: Optional[datetime] = None,
    notifier: Optional[NotificationService] = None,
) -> Appointment:
    """Reschedule a scheduled Appointment to another slot (Req 7.3 — Property 28).

    Moves the Appointment to a different ``available`` slot belonging to the
    same Doctor: the new slot is claimed atomically and the previous slot is
    freed, so the total number of booked slots for the Doctor is conserved
    (Property 28). Both parties are notified of the change (Req 7.4).

    Rejects a reschedule whose target slot is the current slot, belongs to a
    different Doctor, or is no longer available. The ``actor`` must be the
    Appointment's Patient or Doctor.
    """
    appointment = await _load_scheduled_appointment(session, appointment_id)

    is_participant = actor.id in (appointment.patient_id, appointment.doctor_id)
    if not is_participant:
        raise AppError(
            "authorization-error",
            "You may only reschedule your own appointments.",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )

    if new_slot_id == appointment.slot_id:
        raise AppError(
            "slot-unavailable",
            "The appointment is already booked for that slot.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    target = await session.scalar(
        select(AvailabilitySlot).where(AvailabilitySlot.id == new_slot_id)
    )
    if target is None or target.doctor_id != appointment.doctor_id:
        raise AppError(
            "slot-not-found",
            "No such availability slot for this Doctor.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    new_slot = await _claim_slot(session, slot_id=new_slot_id)

    previous_slot = appointment.slot
    if previous_slot is not None:
        previous_slot.status = SlotStatus.AVAILABLE

    appointment.slot_id = new_slot.id
    appointment.start_time = _slot_start_datetime(new_slot)
    appointment.end_time = _slot_end_datetime(new_slot)
    await session.flush()
    await session.refresh(appointment, ["slot"])

    sender = notifier or get_notification_service()
    _notify_change(sender, appointment, new_slot, "rescheduled")
    return appointment
