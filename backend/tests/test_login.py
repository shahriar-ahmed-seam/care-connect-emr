"""Property tests for authentication (tasks 4.9–4.12).

- Property 6: Authentication accepts valid and rejects invalid credentials
  (Req 2.1, 2.2).
- Property 7: Pending accounts cannot authenticate (Req 2.3).
- Property 8: Repeated failures lock authentication (Req 2.4).
- Property 10: Tokens expire exactly at 24 hours (Req 2.7).

The credential/lockout properties run against a real PostgreSQL database via the
module-scoped ``pg_sessionmaker``/``pg_loop`` fixtures, with per-example
rollback. The token-expiry property is pure and needs no database.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.errors import AppError
from app.core.security import (
    TokenExpiredError,
    create_access_token,
    decode_access_token,
)
from app.models.enums import UserRole, UserStatus
from app.services import auth_service
from tests.strategies import emails, full_names

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_passwords = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=40,
)

_issue_times = st.datetimes(
    min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31)
).map(lambda dt: dt.replace(tzinfo=timezone.utc))

async def _create_user(session, *, email, password, name, role):
    return await auth_service.register_user(
        session, email=email, password=password, full_name=name, role=role
    )

@_db_required
@given(
    email=emails,
    password=_passwords,
    wrong=_passwords,
    name=full_names,
)
def test_authentication_accepts_valid_rejects_invalid(
    pg_loop, pg_sessionmaker, email, password, wrong, name
) -> None:
    assume(password != wrong)

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                await _create_user(
                    session,
                    email=email,
                    password=password,
                    name=name,
                    role=UserRole.PATIENT,
                )

                user, issued = await auth_service.authenticate(
                    session, email=email, password=password
                )
                assert user.email == email
                assert issued.token

                with pytest.raises(AppError) as wrong_pw:
                    await auth_service.authenticate(
                        session, email=email, password=wrong
                    )
                assert wrong_pw.value.code == "invalid-credentials"

                with pytest.raises(AppError) as wrong_email:
                    await auth_service.authenticate(
                        session, email=f"nobody-{email}", password=password
                    )
                assert wrong_email.value.code == "invalid-credentials"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(email=emails, password=_passwords, name=full_names)
def test_pending_accounts_cannot_authenticate(
    pg_loop, pg_sessionmaker, email, password, name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _create_user(
                    session,
                    email=email,
                    password=password,
                    name=name,
                    role=UserRole.DOCTOR,
                )
                assert doctor.status == UserStatus.PENDING

                with pytest.raises(AppError) as exc_info:
                    await auth_service.authenticate(
                        session, email=email, password=password
                    )
                assert exc_info.value.code == "account-pending"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(email=emails, password=_passwords, wrong=_passwords, name=full_names, base=_issue_times)
def test_repeated_failures_lock_authentication(
    pg_loop, pg_sessionmaker, email, password, wrong, name, base
) -> None:
    assume(password != wrong)

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                await _create_user(
                    session,
                    email=email,
                    password=password,
                    name=name,
                    role=UserRole.PATIENT,
                )

                for _ in range(auth_service.LOCKOUT_MAX_FAILURES):
                    with pytest.raises(AppError) as failed:
                        await auth_service.authenticate(
                            session, email=email, password=wrong, now=base
                        )
                    assert failed.value.code == "invalid-credentials"

                with pytest.raises(AppError) as locked:
                    await auth_service.authenticate(
                        session, email=email, password=password, now=base
                    )
                assert locked.value.code == "account-locked"

                later = base + timedelta(minutes=16)
                user, issued = await auth_service.authenticate(
                    session, email=email, password=password, now=later
                )
                assert issued.token
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@settings(max_examples=200)
@given(issued_at=_issue_times, role=st.sampled_from(["patient", "doctor", "admin"]))
def test_tokens_expire_exactly_at_24_hours(issued_at, role) -> None:
    issued = create_access_token(subject="user-123", role=role, now=issued_at)
    expiry = issued_at + timedelta(hours=24)

    claims = decode_access_token(issued.token, now=expiry - timedelta(seconds=1))
    assert claims["sub"] == "user-123"
    assert claims["role"] == role

    with pytest.raises(TokenExpiredError):
        decode_access_token(issued.token, now=expiry)

    with pytest.raises(TokenExpiredError):
        decode_access_token(issued.token, now=expiry + timedelta(seconds=1))
