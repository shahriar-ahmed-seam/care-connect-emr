"""Auth_Service HTTP routes: ``/auth/*``.

Wires the registration, login, logout, and password-reset flows to the
Auth_Service. Validation errors (bad email / short password) are produced by
the Pydantic request models and surfaced through the global error-envelope
handler (Req 1.3, 1.4); domain denials are raised as :class:`AppError`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.schemas import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
)
from app.core.errors import AppError
from app.core.security import TokenError, decode_access_token
from app.models.enums import UserRole
from app.models.user import User
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        status=user.status.value,
    )

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> RegisterResponse:
    """Register a Patient (active) or Doctor (pending) account (Req 1.1–1.5)."""
    user = await auth_service.register_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=UserRole(payload.role),
    )
    return RegisterResponse(user=_user_response(user))

@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    """Authenticate and issue a 24-hour session token (Req 2.1–2.4, 2.7)."""
    user, issued = await auth_service.authenticate(
        db, email=payload.email, password=payload.password
    )
    return LoginResponse(
        access_token=issued.token,
        expires_at=issued.expires_at.isoformat(),
        user=_user_response(user),
    )

@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Invalidate the current session token (Req 2.5, 2.6).

    The client session always ends. If token invalidation cannot be completed,
    a retry record is persisted and the response still reports success (Req 2.6).
    """
    header = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if not header or not header.lower().startswith("bearer "):
        raise AppError(
            "authentication-required",
            "Authentication is required to log out.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token = header[len("bearer ") :].strip()
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise AppError(
            "authentication-required",
            "Invalid authentication token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    jti = claims.get("jti")
    exp = claims.get("exp")
    expires_at = datetime.fromtimestamp(int(exp), tz=timezone.utc)
    await auth_service.logout(db, jti=str(jti), expires_at=expires_at)
    return MessageResponse(message="You have been logged out.")

@router.post("/password-reset/request", response_model=MessageResponse)
async def password_reset_request(
    payload: PasswordResetRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Send a time-limited reset link to an active account (Req 2.8).

    Responds identically whether or not the email matches an active account, to
    avoid disclosing which addresses are registered.
    """
    await auth_service.request_password_reset(db, email=payload.email)
    return MessageResponse(
        message="If that email is registered, a reset link has been sent."
    )

@router.post("/password-reset/confirm", response_model=MessageResponse)
async def password_reset_confirm(
    payload: PasswordResetConfirm, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """Set a new password from a valid reset token (Req 2.8)."""
    await auth_service.confirm_password_reset(
        db, token=payload.token, new_password=payload.new_password
    )
    return MessageResponse(message="Your password has been reset.")
