"""Auth_Service: registration, authentication, sessions, and password reset.

This module implements the authentication domain logic behind the ``/auth/*``
endpoints. It is deliberately framework-light: functions take an
``AsyncSession`` and plain arguments and raise :class:`AppError` on failure, so
they can be exercised directly by property-based tests against a real database
as well as wired into FastAPI routes.

Covered behaviour:

- **Registration** (Req 1.1–1.6): create a Patient as ``active`` or a Doctor as
  ``pending``; reject duplicate emails; store only a salted password hash.
- **Authentication** (Req 2.1–2.4, 2.7, 16.3): verify credentials, deny
  ``pending``/``inactive``/``rejected`` accounts, enforce a 5-failure /
  15-minute lockout per email, and issue a 24-hour JWT on success.
- **Session resolution** (Req 2.5, 2.7): decode a token, enforce expiry, and
  reject revoked tokens.
- **Logout / revocation** (Req 2.5, 2.6): record a token's ``jti`` as revoked;
  on a primary-invalidation failure, still end the session and persist a
  retry record.
- **Password reset** (Req 2.8): issue a time-limited reset link to an active
  account and apply a new password from a valid reset token.

Functions ``flush`` their writes but do not ``commit`` — the caller (endpoint
or test) owns the transaction boundary, which keeps tests cleanly isolated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Tuple

from fastapi import status as http_status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import (
    IssuedToken,
    TokenError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.audit import AuthAttempt, RevokedToken
from app.models.enums import RevocationStatus, UserRole, UserStatus
from app.models.user import User
from app.services.mailer import EmailMessage, Mailer, get_mailer

LOCKOUT_MAX_FAILURES = 5
LOCKOUT_WINDOW = timedelta(minutes=15)

RESET_TOKEN_TTL = timedelta(hours=1)
_RESET_TOKEN_TYPE = "pwreset"

_revocation_cache: set[str] = set()

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
) -> User:
    """Create a new user account (Req 1.1, 1.2, 1.5, 1.6).

    A Doctor account is created with status ``pending`` (permissions withheld
    until an Admin approves it); every other role is ``active``. Email
    uniqueness is checked up front and a duplicate is rejected without creating
    a second account (Req 1.2). The password is stored only as a salted hash.

    Email-format and password-length validation are enforced at the request
    (Pydantic) boundary (Req 1.3, 1.4); this function assumes valid inputs but
    still relies on the DB UNIQUE constraint as a backstop.
    """
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise AppError(
            "email-already-registered",
            "That email address is already registered.",
            status_code=http_status.HTTP_409_CONFLICT,
            field="email",
        )

    account_status = (
        UserStatus.PENDING if role == UserRole.DOCTOR else UserStatus.ACTIVE
    )
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        status=account_status,
    )
    session.add(user)
    await session.flush()
    return user

async def _failed_attempts_since_last_success(
    session: AsyncSession, email: str, now: datetime
) -> int:
    """Count consecutive failed attempts for ``email`` within the window.

    Returns the number of failed authentication attempts that occurred after
    the most recent successful attempt, restricted to the trailing
    :data:`LOCKOUT_WINDOW` ending at ``now``. A success resets the count.
    """
    window_start = now - LOCKOUT_WINDOW
    rows = (
        await session.scalars(
            select(AuthAttempt)
            .where(
                AuthAttempt.email == email,
                AuthAttempt.attempted_at > window_start,
                AuthAttempt.attempted_at <= now,
            )
            .order_by(AuthAttempt.attempted_at.asc(), AuthAttempt.id.asc())
        )
    ).all()

    consecutive_failures = 0
    for attempt in rows:
        if attempt.successful:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
    return consecutive_failures

async def is_locked(session: AsyncSession, email: str, now: datetime) -> bool:
    """Return ``True`` if authentication for ``email`` is currently locked.

    Lockout triggers once :data:`LOCKOUT_MAX_FAILURES` consecutive failures
    occur within :data:`LOCKOUT_WINDOW` (Req 2.4). Because the count is
    window-based, the lock naturally clears 15 minutes after the triggering
    failures age out of the window.
    """
    failures = await _failed_attempts_since_last_success(session, email, now)
    return failures >= LOCKOUT_MAX_FAILURES

async def _record_attempt(
    session: AsyncSession, email: str, *, successful: bool, now: datetime
) -> None:
    session.add(
        AuthAttempt(email=email, successful=successful, attempted_at=now)
    )
    await session.flush()

async def authenticate(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    now: Optional[datetime] = None,
) -> Tuple[User, IssuedToken]:
    """Authenticate a user and issue a session token (Req 2.1–2.4, 2.7).

    Raises :class:`AppError` with a stable code on every denial:

    - ``account-locked`` (HTTP 429) when the email is under a lockout, even if
      the supplied credentials are correct (Req 2.4).
    - ``invalid-credentials`` (HTTP 401) when no active account matches the
      email/password combination (Req 2.2), including ``inactive``/``rejected``
      accounts (Req 16.3) — without leaking which.
    - ``account-pending`` (HTTP 403) when the credentials are correct but the
      account is awaiting approval (Req 2.3).

    On success returns the ``User`` and a freshly issued :class:`IssuedToken`.
    """
    current = now or _now_utc()

    if await is_locked(session, email, current):
        raise AppError(
            "account-locked",
            "Too many failed attempts. Try again in 15 minutes.",
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = await session.scalar(select(User).where(User.email == email))
    password_ok = user is not None and verify_password(password, user.password_hash)

    if not password_ok:
        await _record_attempt(session, email, successful=False, now=current)
        raise AppError(
            "invalid-credentials",
            "The email or password is incorrect.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        )

    await _record_attempt(session, email, successful=True, now=current)

    if user.status == UserStatus.PENDING:
        raise AppError(
            "account-pending",
            "Your account is awaiting approval.",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )
    if user.status != UserStatus.ACTIVE:

        raise AppError(
            "invalid-credentials",
            "The email or password is incorrect.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        )

    issued = create_access_token(
        subject=str(user.id), role=user.role.value, now=current
    )
    return user, issued

async def _is_token_revoked(session: AsyncSession, jti: str) -> bool:
    if jti in _revocation_cache:
        return True
    revoked = await session.scalar(
        select(RevokedToken).where(RevokedToken.jti == jti)
    )
    return revoked is not None

async def resolve_current_user(
    session: AsyncSession, token: str, *, now: Optional[datetime] = None
) -> User:
    """Resolve the authenticated user for ``token`` or raise 401 (Req 2.5, 2.7).

    Decodes and signature-verifies the token, enforces the 24-hour expiry
    boundary, rejects tokens whose ``jti`` has been revoked via logout
    (Property 9), and rejects tokens for missing or non-active accounts.
    """
    try:
        claims = decode_access_token(token, now=now)
    except TokenExpiredError as exc:
        raise AppError(
            "token-expired",
            "Your session has expired. Please log in again.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        ) from exc
    except TokenError as exc:
        raise AppError(
            "authentication-required",
            "Invalid authentication token.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        ) from exc

    jti = claims.get("jti")
    if jti is None or await _is_token_revoked(session, jti):
        raise AppError(
            "authentication-required",
            "This session is no longer valid.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        )

    subject = claims.get("sub")
    user: Optional[User] = None
    if subject is not None:
        try:
            user = await session.get(User, uuid.UUID(str(subject)))
        except (ValueError, TypeError):
            user = None
    if user is None or user.status != UserStatus.ACTIVE:
        raise AppError(
            "authentication-required",
            "This session is no longer valid.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        )
    return user

def _default_primary_revoke(jti: str) -> None:
    """Primary fast-path revocation: add the jti to the in-memory cache.

    In production this would also push to a shared cache (e.g. Redis). It is
    injectable so tests can simulate a primary-invalidation failure (Req 2.6).
    """
    _revocation_cache.add(jti)

async def logout(
    session: AsyncSession,
    *,
    jti: str,
    expires_at: datetime,
    primary_revoke: Optional[Callable[[str], None]] = None,
) -> RevocationStatus:
    """Invalidate a session token on logout (Req 2.5, 2.6).

    Attempts the primary revocation step and records the ``jti`` as ``revoked``
    in the durable ``revoked_tokens`` table. If the primary step fails, the
    user's client session still ends and a ``retry_pending`` record is persisted
    so invalidation can be retried later (Req 2.6). Returns the recorded
    :class:`RevocationStatus`.
    """
    revoke = primary_revoke or _default_primary_revoke
    try:
        revoke(jti)
        record_status = RevocationStatus.REVOKED
    except Exception:

        record_status = RevocationStatus.RETRY_PENDING

    session.add(
        RevokedToken(jti=jti, status=record_status, expires_at=expires_at)
    )
    await session.flush()
    return record_status

def _create_reset_token(user_id: str, now: datetime) -> str:
    settings = get_settings()
    claims = {
        "sub": user_id,
        "type": _RESET_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + RESET_TOKEN_TTL).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def _decode_reset_token(token: str, now: datetime) -> str:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
    except JWTError as exc:
        raise AppError(
            "invalid-reset-token",
            "This password reset link is invalid.",
            status_code=http_status.HTTP_400_BAD_REQUEST,
        ) from exc

    if claims.get("type") != _RESET_TOKEN_TYPE:
        raise AppError(
            "invalid-reset-token",
            "This password reset link is invalid.",
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )
    exp = claims.get("exp")
    if exp is None or int(now.timestamp()) >= int(exp):
        raise AppError(
            "invalid-reset-token",
            "This password reset link has expired.",
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )
    subject = claims.get("sub")
    if not subject:
        raise AppError(
            "invalid-reset-token",
            "This password reset link is invalid.",
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )
    return str(subject)

async def request_password_reset(
    session: AsyncSession,
    *,
    email: str,
    mailer: Optional[Mailer] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Send a time-limited reset link to an active account (Req 2.8).

    Returns the issued reset token when a link is sent, or ``None`` when the
    email does not belong to an active account (no email is sent in that case,
    avoiding account enumeration). The endpoint responds identically either way.
    """
    current = now or _now_utc()
    sender = mailer or get_mailer()

    user = await session.scalar(select(User).where(User.email == email))
    if user is None or user.status != UserStatus.ACTIVE:
        return None

    reset_token = _create_reset_token(str(user.id), current)
    settings = get_settings()
    reset_link = f"{settings.api_v1_prefix}/auth/password-reset/confirm?token={reset_token}"
    sender.send(
        EmailMessage(
            to=email,
            subject="Reset your Care-Connect-EMR password",
            body=(
                "We received a request to reset your password. "
                f"Use this link within one hour to choose a new password: {reset_link}"
            ),
        )
    )
    return reset_token

async def confirm_password_reset(
    session: AsyncSession,
    *,
    token: str,
    new_password: str,
    now: Optional[datetime] = None,
) -> User:
    """Set a new password from a valid reset token (Req 2.8)."""
    current = now or _now_utc()
    user_id = _decode_reset_token(token, current)

    user: Optional[User] = None
    try:
        user = await session.get(User, uuid.UUID(user_id))
    except (ValueError, TypeError):
        user = None
    if user is None:
        raise AppError(
            "invalid-reset-token",
            "This password reset link is invalid.",
            status_code=http_status.HTTP_400_BAD_REQUEST,
        )

    user.password_hash = hash_password(new_password)
    await session.flush()
    return user
