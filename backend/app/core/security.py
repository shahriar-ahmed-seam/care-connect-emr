"""Security primitives: password hashing and JWT session tokens.

This module provides the low-level, dependency-free security building blocks
used by the Auth_Service:

- **Password hashing** (Requirement 1.6): bcrypt salted one-way hashing via
  passlib's :class:`CryptContext`. ``hash_password`` always produces a fresh
  random salt, so the same plaintext hashes to different stored values, and
  ``verify_password`` checks a candidate against a stored hash. Plaintext is
  never stored.

- **JWT session tokens** (Requirements 2.1, 2.5, 2.7): stateless access tokens
  carrying ``sub`` (user id), ``role``, ``iat``, ``exp`` (= ``iat`` + 24h) and a
  unique ``jti`` used for server-side revocation on logout. Token decoding
  verifies the signature and enforces the 24-hour expiry boundary against an
  injectable ``now`` so the expiry rule is deterministically testable.

The JWT signing secret and algorithm are read from the application settings,
which source them from environment variables only (Requirement 21.3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__default_rounds=get_settings().bcrypt_rounds,
)

def hash_password(plain_password: str) -> str:
    """Return a bcrypt salted hash of ``plain_password`` (Requirement 1.6).

    Each call uses a fresh random salt, so two hashes of the same password
    differ. The plaintext is never persisted.
    """
    return _pwd_context.hash(plain_password)

def verify_password(plain_password: str, password_hash: str) -> bool:
    """Return ``True`` iff ``plain_password`` matches ``password_hash``.

    Returns ``False`` for malformed/unknown hash formats rather than raising,
    so authentication treats them as a failed credential check.
    """
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        return False

@dataclass(frozen=True)
class IssuedToken:
    """A freshly issued JWT and its salient claims."""

    token: str
    jti: str
    issued_at: datetime
    expires_at: datetime

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def create_access_token(
    *,
    subject: str,
    role: str,
    now: Optional[datetime] = None,
    expires_hours: Optional[int] = None,
) -> IssuedToken:
    """Create a signed JWT access token.

    The token carries ``sub``, ``role``, ``iat``, ``exp`` (= ``iat`` +
    ``expires_hours``, defaulting to the configured 24 hours per Req 2.7), and a
    unique ``jti`` for revocation (Req 2.5). ``now`` is injectable for testing
    the expiry boundary deterministically.
    """
    settings = get_settings()
    issued_at = now or _now_utc()
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    hours = expires_hours if expires_hours is not None else settings.jwt_expires_hours
    expires_at = issued_at + timedelta(hours=hours)
    jti = str(uuid.uuid4())

    claims: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(
        claims, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    return IssuedToken(
        token=token, jti=jti, issued_at=issued_at, expires_at=expires_at
    )

class TokenError(Exception):
    """Base class for token decoding failures."""

class TokenExpiredError(TokenError):
    """Raised when a token is presented at or after its ``exp`` (Req 2.7)."""

class TokenInvalidError(TokenError):
    """Raised when a token's signature or structure is invalid."""

def decode_access_token(
    token: str, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Verifies the signature, then enforces the 24-hour expiry boundary manually
    against ``now`` (defaulting to the current time). A token is valid strictly
    *before* ``exp`` and is treated as expired *at or after* ``exp`` — i.e.
    exactly at 24 hours it is expired (Req 2.7, Property 10).

    Raises :class:`TokenInvalidError` for a bad signature/structure and
    :class:`TokenExpiredError` once the token has expired.
    """
    settings = get_settings()
    try:

        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
    except JWTError as exc:
        raise TokenInvalidError(str(exc)) from exc

    exp = claims.get("exp")
    if exp is None:
        raise TokenInvalidError("Token is missing an expiry claim")

    current = now or _now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if int(current.timestamp()) >= int(exp):
        raise TokenExpiredError("Token has expired")

    return claims
