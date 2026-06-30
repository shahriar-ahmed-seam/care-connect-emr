"""Doctor self-service routes: ``/doctors/me/*``.

Wires a Doctor's own profile management (Requirement 5.1) and availability-slot
creation/removal (Requirements 5.2–5.6) to the Profile_Service and
Appointment_Service. Profile routes require ``MANAGE_DOCTOR_PROFILE`` and slot
routes require ``MANAGE_OWN_SLOTS``; both resolve the acting Doctor from the
authenticated token so a Doctor can only manage their own resources.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require
from app.api.schemas import (
    DoctorProfileRequest,
    DoctorProfileResponse,
    DoctorSearchResponse,
    DoctorSearchResult,
    MessageResponse,
    SlotCreateRequest,
    SlotResponse,
    SlotsResponse,
)
from app.core.errors import AppError
from app.models.appointment import AvailabilitySlot
from app.models.user import DoctorProfile, User
from app.services import appointment_service, profile_service
from app.services.rbac_service import Permission

router = APIRouter(prefix="/doctors", tags=["doctors"])

def _profile_response(profile: DoctorProfile) -> DoctorProfileResponse:
    return DoctorProfileResponse(
        specialty=profile.specialty,
        qualifications=profile.qualifications,
        consultation_fee_bdt=str(profile.consultation_fee_bdt),
    )

def _slot_response(slot: AvailabilitySlot) -> SlotResponse:
    return SlotResponse(
        id=str(slot.id),
        date=slot.date.isoformat(),
        start_time=slot.start_time.isoformat(),
        end_time=slot.end_time.isoformat(),
        status=slot.status.value,
    )

@router.get("", response_model=DoctorSearchResponse)
async def search_doctors(
    specialty: str = "",
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DoctorSearchResponse:
    """Search active Doctors by specialty (Req 6.1).

    Returns exactly the active Doctors whose profile specialty matches the
    ``specialty`` query term (case-insensitive substring).
    """
    doctors = await appointment_service.search_doctors_by_specialty(
        db, specialty_term=specialty
    )
    results = []
    for doctor in doctors:
        profile = doctor.doctor_profile
        results.append(
            DoctorSearchResult(
                id=str(doctor.id),
                full_name=doctor.full_name,
                specialty=profile.specialty if profile else "",
                qualifications=profile.qualifications if profile else None,
                consultation_fee_bdt=(
                    str(profile.consultation_fee_bdt) if profile else "0"
                ),
            )
        )
    return DoctorSearchResponse(doctors=results)

@router.get("/{doctor_id}/slots", response_model=SlotsResponse)
async def list_doctor_slots(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SlotsResponse:
    """List a Doctor's future available slots (Req 6.2).

    Returns only ``available`` slots whose start time is later than now.
    """
    slots = await appointment_service.list_future_available_slots(
        db, doctor_id=doctor_id
    )
    return SlotsResponse(slots=[_slot_response(slot) for slot in slots])

@router.get("/me/profile", response_model=DoctorProfileResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require(Permission.MANAGE_DOCTOR_PROFILE)),
) -> DoctorProfileResponse:
    """Retrieve the acting Doctor's profile (Req 5.1)."""
    profile = await profile_service.get_doctor_profile(db, doctor_id=doctor.id)
    if profile is None:
        raise AppError(
            "profile-not-found",
            "You have not set up a profile yet.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _profile_response(profile)

@router.put("/me/profile", response_model=DoctorProfileResponse)
async def save_my_profile(
    payload: DoctorProfileRequest,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require(Permission.MANAGE_DOCTOR_PROFILE)),
) -> DoctorProfileResponse:
    """Save the acting Doctor's profile (specialty, qualifications, fee) (Req 5.1)."""
    profile = await profile_service.save_doctor_profile(
        db,
        doctor_id=doctor.id,
        specialty=payload.specialty,
        qualifications=payload.qualifications,
        consultation_fee_bdt=payload.consultation_fee_bdt,
    )
    return _profile_response(profile)

@router.post(
    "/me/slots",
    response_model=SlotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_slot(
    payload: SlotCreateRequest,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require(Permission.MANAGE_OWN_SLOTS)),
) -> SlotResponse:
    """Create an availability slot for the acting Doctor (Req 5.2–5.4)."""
    slot = await appointment_service.create_slot(
        db,
        doctor_id=doctor.id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    return _slot_response(slot)

@router.delete("/me/slots/{slot_id}", response_model=MessageResponse)
async def remove_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require(Permission.MANAGE_OWN_SLOTS)),
) -> MessageResponse:
    """Remove an unbooked availability slot for the acting Doctor (Req 5.5, 5.6)."""
    await appointment_service.remove_slot(db, doctor_id=doctor.id, slot_id=slot_id)
    return MessageResponse(message="Availability slot removed.")
