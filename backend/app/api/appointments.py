"""Appointment routes: ``/appointments/*``.

Wires the Patient-facing booking lifecycle to the Appointment_Service
(Requirements 6.3–6.6, 7.1–7.5):

- ``POST /appointments`` books an available slot (Patients only, via the
  ``BOOK_APPOINTMENT`` permission). The booking claims the slot atomically and
  snapshots the Doctor's consultation fee.
- ``POST /appointments/{id}/cancel`` cancels a scheduled Appointment. Either
  participant (the Patient or the Doctor) may cancel; the Appointment_Service
  enforces the Patient one-hour rule (Req 7.1, 7.2) and frees the slot.
- ``POST /appointments/{id}/reschedule`` moves a scheduled Appointment to
  another available slot of the same Doctor (Req 7.3).

Cancel and reschedule resolve the acting user from the token and let the service
enforce participant-level authorization, so a Doctor can cancel their own
Appointment (Req 7.5) while a non-participant is denied.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require
from app.api.schemas import (
    AppointmentResponse,
    BookAppointmentRequest,
    RescheduleAppointmentRequest,
)
from app.models.appointment import Appointment
from app.models.user import User
from app.services import appointment_service
from app.services.rbac_service import Permission

router = APIRouter(prefix="/appointments", tags=["appointments"])

def _appointment_response(appointment: Appointment) -> AppointmentResponse:
    return AppointmentResponse(
        id=str(appointment.id),
        patient_id=str(appointment.patient_id),
        doctor_id=str(appointment.doctor_id),
        slot_id=str(appointment.slot_id),
        status=appointment.status.value,
        fee_bdt_at_booking=str(appointment.fee_bdt_at_booking),
        start_time=appointment.start_time.isoformat(),
        end_time=appointment.end_time.isoformat(),
    )

@router.post(
    "",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def book_appointment(
    payload: BookAppointmentRequest,
    db: AsyncSession = Depends(get_db),
    patient: User = Depends(require(Permission.BOOK_APPOINTMENT)),
) -> AppointmentResponse:
    """Book an available slot for the acting Patient (Req 6.3–6.6)."""
    appointment = await appointment_service.book_appointment(
        db, patient_id=patient.id, slot_id=payload.slot_id
    )
    return _appointment_response(appointment)

@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> AppointmentResponse:
    """Cancel a scheduled Appointment (Req 7.1, 7.2, 7.5)."""
    appointment = await appointment_service.cancel_appointment(
        db, appointment_id=appointment_id, actor=actor
    )
    return _appointment_response(appointment)

@router.post("/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: RescheduleAppointmentRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> AppointmentResponse:
    """Reschedule a scheduled Appointment to another slot (Req 7.3)."""
    appointment = await appointment_service.reschedule_appointment(
        db,
        appointment_id=appointment_id,
        new_slot_id=payload.slot_id,
        actor=actor,
    )
    return _appointment_response(appointment)
