"""Property tests for RBAC and patient-data auditing (tasks 5.4–5.8).

- Property 11: Actions are permitted only when the role grants the permission,
  including unauthenticated denial (Req 3.1, 3.6).
- Property 12: Patients are scoped to their own data (Req 3.2, 3.3).
- Property 13: Doctors access only records of their own patients, iff a
  scheduled/completed appointment exists (Req 3.4).
- Property 14: Admins are denied consultation free-text (Req 3.5).
- Property 44: Patient-data access is audited (Req 13.5).

The matrix-only properties (11, 14) are pure and need no database. The scoping
and audit properties (12, 13, 44) run against a real PostgreSQL database via the
module-scoped ``pg_sessionmaker``/``pg_loop`` fixtures, with per-example
rollback for isolation.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from sqlalchemy import func, select
from starlette.requests import Request

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.models.appointment import Appointment, AvailabilitySlot
from app.models.audit import AuditLog
from app.models.clinical import MedicalHistory
from app.models.enums import AppointmentStatus, SlotStatus, UserRole, UserStatus
from app.models.user import User
from app.services import auth_service, rbac_service
from app.services.rbac_service import (
    PERMISSION_MATRIX,
    Permission,
    authorize_patient_data_access,
    record_patient_data_access,
    role_has_permission,
)
from tests.strategies import emails, full_names

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_roles = st.sampled_from(list(UserRole))
_permissions = st.sampled_from(list(Permission))
_PASSWORD = "password123"

async def _make_patient(session, *, email: str, name: str) -> User:
    return await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.PATIENT,
    )

async def _make_active_doctor(session, *, email: str, name: str) -> User:
    doctor = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.DOCTOR,
    )
    doctor.status = UserStatus.ACTIVE
    await session.flush()
    return doctor

async def _make_appointment(
    session, *, doctor: User, patient: User, status: AppointmentStatus
) -> Appointment:
    slot = AvailabilitySlot(
        doctor_id=doctor.id,
        date=date(2025, 1, 1),
        start_time=time(10, 0),
        end_time=time(10, 30),
        status=SlotStatus.BOOKED,
    )
    session.add(slot)
    await session.flush()

    start = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        slot_id=slot.id,
        status=status,
        fee_bdt_at_booking=Decimal("500.00"),
        start_time=start,
        end_time=start + timedelta(minutes=30),
    )
    session.add(appointment)
    await session.flush()
    return appointment

def _make_request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/protected",
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("test", 80),
        }
    )

@given(role=_roles, permission=_permissions)
def test_permission_matrix_iff(role, permission) -> None:

    granted = permission in PERMISSION_MATRIX[role]
    assert role_has_permission(role, permission) is granted

    if granted:

        rbac_service.assert_permission(role, permission)
    else:
        with pytest.raises(AppError) as exc:
            rbac_service.assert_permission(role, permission)
        assert exc.value.code == "authorization-error"
        assert exc.value.status_code == 403

@given(
    headers=st.sampled_from(
        [
            [],
            [(b"authorization", b"")],
            [(b"authorization", b"Token abc")],
            [(b"authorization", b"Bearer ")],
        ]
    )
)
def test_unauthenticated_request_denied(headers) -> None:
    request = _make_request(headers)

    async def scenario() -> None:
        with pytest.raises(AppError) as exc:

            await get_current_user(request, db=None)
        assert exc.value.code == "authentication-required"
        assert exc.value.status_code == 401

    asyncio.run(scenario())

@_db_required
@given(
    email_a=emails,
    email_b=emails,
    name_a=full_names,
    name_b=full_names,
    note_a=full_names,
    note_b=full_names,
)
def test_patients_scoped_to_own_data(
    pg_loop, pg_sessionmaker, email_a, email_b, name_a, name_b, note_a, note_b
) -> None:
    assume(email_a != email_b)

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                patient_a = await _make_patient(session, email=email_a, name=name_a)
                patient_b = await _make_patient(session, email=email_b, name=name_b)

                session.add(
                    MedicalHistory(
                        patient_id=patient_a.id,
                        description_enc=note_a,
                        entry_date=date(2025, 1, 1),
                    )
                )
                session.add(
                    MedicalHistory(
                        patient_id=patient_b.id,
                        description_enc=note_b,
                        entry_date=date(2025, 1, 1),
                    )
                )
                await session.flush()

                rows_a = (
                    await session.scalars(
                        select(MedicalHistory).where(
                            MedicalHistory.patient_id == patient_a.id
                        )
                    )
                ).all()
                assert len(rows_a) == 1
                assert all(r.patient_id == patient_a.id for r in rows_a)

                await authorize_patient_data_access(
                    session, user=patient_a, patient_id=patient_a.id
                )

                with pytest.raises(AppError) as exc:
                    await authorize_patient_data_access(
                        session, user=patient_a, patient_id=patient_b.id
                    )
                assert exc.value.code == "authorization-error"
                assert exc.value.status_code == 403
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(
    doctor_email=emails,
    patient_email=emails,
    doctor_name=full_names,
    patient_name=full_names,
    appointment_status=st.sampled_from(list(AppointmentStatus)),
)
def test_doctors_access_only_their_patients(
    pg_loop,
    pg_sessionmaker,
    doctor_email,
    patient_email,
    doctor_name,
    patient_name,
    appointment_status,
) -> None:
    assume(doctor_email != patient_email)

    grants_access = appointment_status in (
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.COMPLETED,
    )

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(
                    session, email=doctor_email, name=doctor_name
                )
                patient = await _make_patient(
                    session, email=patient_email, name=patient_name
                )

                assert not await rbac_service.doctor_has_patient_relationship(
                    session, doctor_id=doctor.id, patient_id=patient.id
                )
                with pytest.raises(AppError) as no_appt:
                    await authorize_patient_data_access(
                        session, user=doctor, patient_id=patient.id
                    )
                assert no_appt.value.code == "authorization-error"

                await _make_appointment(
                    session,
                    doctor=doctor,
                    patient=patient,
                    status=appointment_status,
                )

                relationship = await rbac_service.doctor_has_patient_relationship(
                    session, doctor_id=doctor.id, patient_id=patient.id
                )
                assert relationship is grants_access

                if grants_access:
                    await authorize_patient_data_access(
                        session, user=doctor, patient_id=patient.id
                    )
                else:
                    with pytest.raises(AppError) as exc:
                        await authorize_patient_data_access(
                            session, user=doctor, patient_id=patient.id
                        )
                    assert exc.value.code == "authorization-error"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@given(patient_id=st.uuids())
def test_admins_denied_consultation_freetext(patient_id) -> None:

    assert role_has_permission(UserRole.ADMIN, Permission.MANAGE_USERS)
    assert role_has_permission(UserRole.ADMIN, Permission.MANAGE_SCHEDULES)
    assert role_has_permission(UserRole.ADMIN, Permission.APPROVE_DOCTORS)

    assert not role_has_permission(
        UserRole.ADMIN, Permission.VIEW_CONSULTATION_FREETEXT
    )

    admin = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash="x",
        full_name="Admin",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )

    async def scenario() -> None:

        await authorize_patient_data_access(
            None, user=admin, patient_id=patient_id, free_text=False
        )

        with pytest.raises(AppError) as exc:
            await authorize_patient_data_access(
                None, user=admin, patient_id=patient_id, free_text=True
            )
        assert exc.value.code == "authorization-error"
        assert exc.value.status_code == 403

    asyncio.run(scenario())

@_db_required
@given(
    actor_email=emails,
    patient_email=emails,
    actor_name=full_names,
    patient_name=full_names,
    action=st.sampled_from(["view_record", "edit_vitals", "view_prescription"]),
)
def test_patient_data_access_is_audited(
    pg_loop,
    pg_sessionmaker,
    actor_email,
    patient_email,
    actor_name,
    patient_name,
    action,
) -> None:
    assume(actor_email != patient_email)

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                actor = await _make_active_doctor(
                    session, email=actor_email, name=actor_name
                )
                patient = await _make_patient(
                    session, email=patient_email, name=patient_name
                )

                entry = await record_patient_data_access(
                    session,
                    actor_user_id=actor.id,
                    patient_id=patient.id,
                    action=action,
                )

                await session.refresh(entry)
                stored = entry
                assert stored is not None
                assert stored.actor_user_id == actor.id
                assert stored.patient_id == patient.id
                assert stored.action == action
                assert stored.created_at is not None

                count = await session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.actor_user_id == actor.id,
                        AuditLog.patient_id == patient.id,
                    )
                )
                assert count == 1
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
