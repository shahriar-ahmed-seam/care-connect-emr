"""Property tests for Admin doctor-approval and account management (tasks 6.2–6.4).

- Property 15: Pending list equals the set of pending accounts (Req 4.1, 16.4).
- Property 16: Approval activates and rejection blocks doctor accounts
  (Req 4.2, 4.3).
- Property 17: Deactivation disables authentication (Req 16.3).

All three properties run against a real PostgreSQL database via the
module-scoped ``pg_sessionmaker``/``pg_loop`` fixtures; each Hypothesis example
uses its own session and rolls back for isolation.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import AppError
from app.models.enums import UserRole, UserStatus
from app.models.user import DoctorProfile
from app.services import account_service, auth_service
from app.services.notification_service import CapturingNotificationService
from tests.strategies import full_names

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _make_doctor(session, *, email, name, status=UserStatus.PENDING):
    doctor = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.DOCTOR,
    )
    if status != UserStatus.PENDING:
        doctor.status = status
        await session.flush()
    return doctor

@_db_required
@given(
    statuses=st.lists(st.sampled_from(list(UserStatus)), min_size=0, max_size=8),
    name=full_names,
)
def test_pending_list_equals_pending_accounts(
    pg_loop, pg_sessionmaker, statuses, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                expected_pending: set = set()
                for i, status in enumerate(statuses):
                    doctor = await _make_doctor(
                        session,
                        email=f"doc{i}@example.com",
                        name=name,
                        status=status,
                    )

                    session.add(
                        DoctorProfile(
                            user_id=doctor.id,
                            specialty="Cardiology",
                            qualifications="MBBS, FCPS",
                            consultation_fee_bdt=Decimal("800.00"),
                        )
                    )
                    await session.flush()
                    if status == UserStatus.PENDING:
                        expected_pending.add(doctor.id)

                pending = await account_service.list_pending_accounts(session)
                returned_ids = {u.id for u in pending}

                assert returned_ids == expected_pending

                for u in pending:
                    assert u.status == UserStatus.PENDING
                    assert u.full_name
                    assert u.email
                    assert u.doctor_profile is not None
                    assert u.doctor_profile.specialty
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(approve_email=st.just("approve@example.com"), reject_email=st.just("reject@example.com"), name=full_names)
def test_approval_activates_rejection_blocks(
    pg_loop, pg_sessionmaker, approve_email, reject_email, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:

                approved = await _make_doctor(
                    session, email=approve_email, name=name
                )
                assert approved.status == UserStatus.PENDING

                notifier = CapturingNotificationService()
                result = await account_service.approve_doctor(
                    session, user_id=approved.id, notifier=notifier
                )
                assert result.status == UserStatus.ACTIVE

                assert len(notifier.approvals) == 1
                assert notifier.approvals[0].to == approve_email

                user, issued = await auth_service.authenticate(
                    session, email=approve_email, password=_PASSWORD
                )
                assert issued.token
                assert user.role == UserRole.DOCTOR

                rejected = await _make_doctor(
                    session, email=reject_email, name=name
                )
                result = await account_service.reject_doctor(
                    session, user_id=rejected.id
                )
                assert result.status == UserStatus.REJECTED

                with pytest.raises(AppError) as exc:
                    await auth_service.authenticate(
                        session, email=reject_email, password=_PASSWORD
                    )
                assert exc.value.code == "invalid-credentials"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(email=st.just("active@example.com"), name=full_names)
def test_deactivation_disables_authentication(
    pg_loop, pg_sessionmaker, email, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:

                patient = await auth_service.register_user(
                    session, email=email, password=_PASSWORD, full_name=name,
                    role=UserRole.PATIENT,
                )
                assert patient.status == UserStatus.ACTIVE
                _, issued = await auth_service.authenticate(
                    session, email=email, password=_PASSWORD
                )
                assert issued.token

                result = await account_service.deactivate_account(
                    session, user_id=patient.id
                )
                assert result.status == UserStatus.INACTIVE

                with pytest.raises(AppError) as exc:
                    await auth_service.authenticate(
                        session, email=email, password=_PASSWORD
                    )
                assert exc.value.code == "invalid-credentials"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
