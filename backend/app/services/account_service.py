"""Account_Service: Admin doctor-approval and account-management operations.

Implements the Admin-facing account lifecycle behind the ``/admin/*`` endpoints
(Requirements 4.1–4.4, 16.3, 16.4). Like the rest of the service layer it is
framework-light: functions take an ``AsyncSession`` and plain arguments and
raise :class:`AppError` on failure, so they can be exercised directly by
property-based tests against a real database as well as wired into FastAPI
routes.

Covered behaviour:

- **Pending list** (Req 4.1, 16.4): :func:`list_pending_accounts` returns every
  account whose status is ``pending`` — with full name, email, and the
  applicant's submitted credentials (their Doctor profile, when present) — and
  no other accounts (Property 15).
- **Approval** (Req 4.2, 4.4): :func:`approve_doctor` transitions a pending
  Doctor account to ``active`` (which grants Doctor permissions, since the RBAC
  matrix keys off the Doctor role for an active account) and triggers an
  approval notification email via the Notification_Service.
- **Rejection** (Req 4.3): :func:`reject_doctor` transitions a pending Doctor
  account to ``rejected``; the Auth_Service then denies authentication for it.
- **Deactivation** (Req 16.3): :func:`deactivate_account` transitions any
  account to ``inactive``; the Auth_Service then denies authentication for it.

Functions ``flush`` their writes but do not ``commit`` — the caller (endpoint or
test) owns the transaction boundary.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models.enums import UserRole, UserStatus
from app.models.user import User
from app.services.notification_service import (
    DoctorApprovalNotification,
    NotificationService,
    get_notification_service,
)

async def list_pending_accounts(session: AsyncSession) -> List[User]:
    """Return all accounts with status ``pending`` (Req 4.1, 16.4 — Property 15).

    Results are ordered by creation time (oldest first) so the Admin reviews
    applications in arrival order. The applicant's Doctor profile (their
    submitted credentials) is eagerly loaded so the caller can render it without
    a lazy async access.
    """
    rows = await session.scalars(
        select(User)
        .where(User.status == UserStatus.PENDING)
        .options(selectinload(User.doctor_profile))
        .order_by(User.created_at.asc(), User.id.asc())
    )
    return list(rows.all())

async def _get_account(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(
            "account-not-found",
            "No account exists for that identifier.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    return user

async def approve_doctor(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    notifier: Optional[NotificationService] = None,
) -> User:
    """Approve a pending Doctor account (Req 4.2, 4.4 — Property 16).

    Transitions the account from ``pending`` to ``active``; because the RBAC
    permission matrix grants Doctor permissions to an *active* account with the
    Doctor role, activation is exactly what confers those permissions. After the
    status change is flushed, an approval notification email is dispatched to the
    Doctor's registered address via the Notification_Service.

    Rejects (without mutation) any account that is not a pending Doctor, so the
    operation cannot accidentally activate a non-doctor or re-process a settled
    account.
    """
    user = await _get_account(session, user_id)
    if user.role != UserRole.DOCTOR:
        raise AppError(
            "invalid-account-state",
            "Only Doctor accounts can be approved.",
            status_code=http_status.HTTP_409_CONFLICT,
        )
    if user.status != UserStatus.PENDING:
        raise AppError(
            "invalid-account-state",
            "Only a pending account can be approved.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    user.status = UserStatus.ACTIVE
    await session.flush()

    sender = notifier or get_notification_service()
    sender.send_doctor_approval(
        DoctorApprovalNotification(to=user.email, full_name=user.full_name)
    )
    return user

async def reject_doctor(
    session: AsyncSession, *, user_id: uuid.UUID
) -> User:
    """Reject a pending Doctor account (Req 4.3 — Property 16).

    Transitions the account from ``pending`` to ``rejected``; the Auth_Service
    subsequently denies authentication for a non-active account. Rejects
    (without mutation) any account that is not a pending Doctor.
    """
    user = await _get_account(session, user_id)
    if user.role != UserRole.DOCTOR:
        raise AppError(
            "invalid-account-state",
            "Only Doctor accounts can be rejected.",
            status_code=http_status.HTTP_409_CONFLICT,
        )
    if user.status != UserStatus.PENDING:
        raise AppError(
            "invalid-account-state",
            "Only a pending account can be rejected.",
            status_code=http_status.HTTP_409_CONFLICT,
        )

    user.status = UserStatus.REJECTED
    await session.flush()
    return user

async def deactivate_account(
    session: AsyncSession, *, user_id: uuid.UUID
) -> User:
    """Deactivate an account (Req 16.3 — Property 17).

    Transitions any account to ``inactive``; the Auth_Service then denies
    authentication for it. Idempotent in effect: deactivating an already
    inactive account leaves it inactive.
    """
    user = await _get_account(session, user_id)
    user.status = UserStatus.INACTIVE
    await session.flush()
    return user
