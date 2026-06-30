"""Property tests for the registration flow (tasks 4.4–4.7).

- Property 1: Patient registration produces an active patient (Req 1.1).
- Property 4: Doctor registration is pending without permissions (Req 1.5).
- Property 2: Duplicate emails are rejected with no new account (Req 1.2).
- Property 3: Invalid inputs are rejected with the offending field (Req 1.3, 1.4).

Account-creation properties (1, 4, 2) run against a real PostgreSQL database via
the module-scoped ``pg_sessionmaker``/``pg_loop`` fixtures; each Hypothesis
example uses its own session and rolls back for isolation. Property 3 validates
the request schema directly and needs no database.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import given
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.schemas import RegisterRequest
from app.core.errors import AppError
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.services import auth_service
from tests.strategies import (
    emails,
    full_names,
    invalid_emails,
    invalid_passwords,
    valid_passwords,
)

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

@_db_required
@given(email=emails, password=valid_passwords, name=full_names)
def test_patient_registration_produces_active_patient(
    pg_loop, pg_sessionmaker, email, password, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                user = await auth_service.register_user(
                    session,
                    email=email,
                    password=password,
                    full_name=name,
                    role=UserRole.PATIENT,
                )
                assert user.role == UserRole.PATIENT
                assert user.status == UserStatus.ACTIVE
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(email=emails, password=valid_passwords, name=full_names)
def test_doctor_registration_is_pending(
    pg_loop, pg_sessionmaker, email, password, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                user = await auth_service.register_user(
                    session,
                    email=email,
                    password=password,
                    full_name=name,
                    role=UserRole.DOCTOR,
                )
                assert user.role == UserRole.DOCTOR

                assert user.status == UserStatus.PENDING
                assert user.status != UserStatus.ACTIVE
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(email=emails, password=valid_passwords, name=full_names)
def test_duplicate_email_is_rejected(
    pg_loop, pg_sessionmaker, email, password, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                await auth_service.register_user(
                    session,
                    email=email,
                    password=password,
                    full_name=name,
                    role=UserRole.PATIENT,
                )
                with pytest.raises(AppError) as exc_info:
                    await auth_service.register_user(
                        session,
                        email=email,
                        password=password,
                        full_name=name,
                        role=UserRole.PATIENT,
                    )
                assert exc_info.value.code == "email-already-registered"
                assert exc_info.value.field == "email"

                count = await session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.email == email)
                )
                assert count == 1
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@given(email=emails, password=invalid_passwords, name=full_names)
def test_short_password_rejected_with_password_field(email, password, name) -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            email=email, password=password, full_name=name, role="patient"
        )
    fields = {tuple(err["loc"]) for err in exc_info.value.errors()}
    assert any("password" in loc for loc in fields)

@given(email=invalid_emails, password=valid_passwords, name=full_names)
def test_invalid_email_rejected_with_email_field(email, password, name) -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            email=email, password=password, full_name=name, role="patient"
        )
    fields = {tuple(err["loc"]) for err in exc_info.value.errors()}
    assert any("email" in loc for loc in fields)
