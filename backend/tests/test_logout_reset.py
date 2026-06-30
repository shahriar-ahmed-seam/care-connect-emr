"""Tests for logout/revocation and password reset (tasks 4.14, 4.15).

- Property 9: Logout invalidates the session token (Req 2.5) — a Hypothesis
  property test against a real database.
- Unit tests (Req 2.6, 2.8): the logout-failure retry path records a
  retry-pending revocation and still ends the session, and a password-reset
  request sends a time-limited reset link only for an active account.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import AppError
from app.core.security import verify_password
from app.models.enums import RevocationStatus, UserRole, UserStatus
from app.services import auth_service
from app.services.mailer import CapturingMailer
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

@_db_required
@given(email=emails, password=_passwords, name=full_names)
def test_logout_invalidates_session_token(
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
                user, issued = await auth_service.authenticate(
                    session, email=email, password=password
                )

                resolved = await auth_service.resolve_current_user(
                    session, issued.token
                )
                assert resolved.id == user.id

                await auth_service.logout(
                    session, jti=issued.jti, expires_at=issued.expires_at
                )
                with pytest.raises(AppError) as exc_info:
                    await auth_service.resolve_current_user(
                        session, issued.token
                    )
                assert exc_info.value.status_code == 401
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@pytest_asyncio.fixture
async def schema_factory() -> AsyncIterator["object"]:
    """Create the full schema on a fresh engine and yield a session factory."""
    if not _DB_URL:
        pytest.skip("No TEST_DATABASE_URL/DATABASE_URL configured")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models
    from app.models.base import Base

    engine = create_async_engine(_DB_URL)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

@pytest.mark.asyncio
async def test_logout_failure_records_retry_and_ends_session(schema_factory) -> None:
    """A failed primary invalidation still ends the session and is queued for
    retry (Req 2.6)."""
    from sqlalchemy import select

    from app.models.audit import RevokedToken

    async with schema_factory() as session:
        user, issued = None, None
        await auth_service.register_user(
            session,
            email="retry@example.com",
            password="password123",
            full_name="Retry User",
            role=UserRole.PATIENT,
        )
        user, issued = await auth_service.authenticate(
            session, email="retry@example.com", password="password123"
        )

        def failing_revoke(jti: str) -> None:
            raise RuntimeError("primary revocation backend unavailable")

        status = await auth_service.logout(
            session,
            jti=issued.jti,
            expires_at=issued.expires_at,
            primary_revoke=failing_revoke,
        )
        assert status == RevocationStatus.RETRY_PENDING

        record = await session.scalar(
            select(RevokedToken).where(RevokedToken.jti == issued.jti)
        )
        assert record is not None
        assert record.status == RevocationStatus.RETRY_PENDING

        with pytest.raises(AppError):
            await auth_service.resolve_current_user(session, issued.token)

        await session.rollback()

@pytest.mark.asyncio
async def test_password_reset_link_sent_only_for_active_account(
    schema_factory,
) -> None:
    """A reset link is sent for an active account and the token resets the
    password; no link is sent for pending or unknown accounts (Req 2.8)."""
    async with schema_factory() as session:
        await auth_service.register_user(
            session,
            email="active@example.com",
            password="oldpassword1",
            full_name="Active User",
            role=UserRole.PATIENT,
        )

        await auth_service.register_user(
            session,
            email="pending@example.com",
            password="oldpassword1",
            full_name="Pending Doctor",
            role=UserRole.DOCTOR,
        )

        mailer = CapturingMailer()

        token = await auth_service.request_password_reset(
            session, email="active@example.com", mailer=mailer
        )
        assert token is not None
        assert len(mailer.sent) == 1
        sent = mailer.sent[0]
        assert sent.to == "active@example.com"
        assert token in sent.body

        mailer.clear()
        token_pending = await auth_service.request_password_reset(
            session, email="pending@example.com", mailer=mailer
        )
        assert token_pending is None
        assert mailer.sent == []

        token_unknown = await auth_service.request_password_reset(
            session, email="nobody@example.com", mailer=mailer
        )
        assert token_unknown is None
        assert mailer.sent == []

        updated = await auth_service.confirm_password_reset(
            session, token=token, new_password="brandnewpass9"
        )
        assert verify_password("brandnewpass9", updated.password_hash)
        assert updated.status == UserStatus.ACTIVE

        await session.rollback()
