"""Shared FastAPI dependencies for the API layer.

- ``get_db`` yields a request-scoped ``AsyncSession`` and commits on success or
  rolls back on error, so route handlers do not manage transactions directly.
- ``get_current_user`` extracts the Bearer token, resolves the authenticated
  user via the Auth_Service, and rejects missing/invalid/expired/revoked tokens
  with a 401 authentication-required error (Req 2.5, 2.7, 3.6).

Tests override ``get_db`` to bind handlers to a transactional test session.
"""

from __future__ import annotations

from typing import AsyncIterator, Callable, Coroutine, Optional

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.models.user import User
from app.services import auth_service, rbac_service
from app.services.rbac_service import Permission

async def get_db() -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped async session with commit/rollback handling."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

def _extract_bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if not header or not header.lower().startswith("bearer "):
        raise AppError(
            "authentication-required",
            "Authentication is required to access this resource.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token = header[len("bearer ") :].strip()
    if not token:
        raise AppError(
            "authentication-required",
            "Authentication is required to access this resource.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return token

async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Resolve and return the authenticated user, or raise 401 (Req 3.6)."""
    token = _extract_bearer_token(request)
    return await auth_service.resolve_current_user(db, token)

async def get_optional_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Return the authenticated user if a valid token is present, else None."""
    header = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if not header:
        return None
    return await get_current_user(request, db)

def require(
    permission: Permission,
) -> Callable[[User], Coroutine[None, None, User]]:
    """Build a FastAPI dependency enforcing ``permission`` (Req 3.1, 3.6).

    The returned dependency first resolves the current user via
    :func:`get_current_user` — which raises ``401 authentication-required`` for
    a missing, invalid, expired, or revoked token (Req 3.6) — and then checks
    the RBAC permission matrix. If the user's role does not grant ``permission``
    it raises ``403 authorization-error`` (Req 3.1). On success it returns the
    authenticated :class:`User` so handlers can use it directly.

    Usage::

        @router.post("/doctors/me/slots")
        async def create_slot(user: User = Depends(require(Permission.MANAGE_OWN_SLOTS))):
            ...
    """

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        rbac_service.assert_permission(user.role, permission)
        return user

    return _dependency
