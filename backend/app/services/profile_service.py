"""Profile_Service: Doctor profile persistence (Requirement 5.1).

A Doctor maintains a profile of their specialty, qualifications, and
consultation fee in BDT so patients can discover and book them. This module
provides save (upsert) and retrieve operations used behind the doctor-profile
endpoints.

Like the rest of the service layer it is framework-light: functions take an
``AsyncSession`` and plain arguments and ``flush`` (not ``commit``) their
writes, leaving the transaction boundary to the caller.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import DoctorProfile

async def get_doctor_profile(
    session: AsyncSession, *, doctor_id: uuid.UUID
) -> Optional[DoctorProfile]:
    """Return the Doctor's profile, or ``None`` if none has been saved yet."""
    return await session.scalar(
        select(DoctorProfile).where(DoctorProfile.user_id == doctor_id)
    )

async def save_doctor_profile(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    specialty: str,
    qualifications: Optional[str],
    consultation_fee_bdt: Decimal,
) -> DoctorProfile:
    """Create or update a Doctor's profile (Req 5.1 — Property 18).

    Upserts the single profile row for ``doctor_id``: an existing profile has
    its fields overwritten; otherwise a new profile is created. Saving then
    retrieving yields equal field values (the round-trip Property 18 checks).
    """
    profile = await get_doctor_profile(session, doctor_id=doctor_id)
    if profile is None:
        profile = DoctorProfile(
            user_id=doctor_id,
            specialty=specialty,
            qualifications=qualifications,
            consultation_fee_bdt=consultation_fee_bdt,
        )
        session.add(profile)
    else:
        profile.specialty = specialty
        profile.qualifications = qualifications
        profile.consultation_fee_bdt = consultation_fee_bdt
    await session.flush()
    return profile
