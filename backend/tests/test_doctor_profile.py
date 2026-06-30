"""Property test for Doctor profile management (task 7.2).

- Property 18: Doctor profile round-trips (Req 5.1).

Runs against a real PostgreSQL database via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures, with per-example rollback.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from hypothesis import given

from app.models.enums import UserRole, UserStatus
from app.services import auth_service, profile_service
from tests.strategies import (
    consultation_fees_bdt,
    full_names,
    qualifications,
    specialties,
)

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

@_db_required
@given(
    name=full_names,
    specialty=specialties,
    quals=qualifications,
    fee=consultation_fees_bdt,
)
def test_doctor_profile_round_trips(
    pg_loop, pg_sessionmaker, name, specialty, quals, fee
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await auth_service.register_user(
                    session,
                    email="doc-profile@example.com",
                    password="password123",
                    full_name=name,
                    role=UserRole.DOCTOR,
                )
                doctor.status = UserStatus.ACTIVE
                await session.flush()

                profile = await profile_service.save_doctor_profile(
                    session,
                    doctor_id=doctor.id,
                    specialty=specialty,
                    qualifications=quals,
                    consultation_fee_bdt=fee,
                )

                await session.refresh(profile)

                assert profile is not None
                assert profile.specialty == specialty
                assert profile.qualifications == quals

                assert profile.consultation_fee_bdt == fee.quantize(Decimal("0.01"))
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
