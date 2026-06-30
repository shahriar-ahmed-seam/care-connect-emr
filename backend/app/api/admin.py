"""Admin account-management routes: ``/admin/*``.

Wires the Admin doctor-approval and account-management flows to the
Account_Service (Requirements 4.1–4.4, 16.3, 16.4). Every route requires an
Admin: the pending list and approve/reject actions require the
``APPROVE_DOCTORS`` permission, and deactivation requires ``MANAGE_USERS``. The
``require(permission)`` dependency returns ``401`` for missing/invalid tokens
and ``403`` when the role lacks the permission.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require
from app.api.schemas import (
    MessageResponse,
    PendingAccountResponse,
    PendingAccountsResponse,
    SubmittedCredentials,
)
from app.models.user import User
from app.services import account_service
from app.services.rbac_service import Permission

router = APIRouter(prefix="/admin", tags=["admin"])

def _credentials(user: User) -> SubmittedCredentials | None:
    profile = user.doctor_profile
    if profile is None:
        return None
    return SubmittedCredentials(
        specialty=profile.specialty,
        qualifications=profile.qualifications,
        consultation_fee_bdt=str(profile.consultation_fee_bdt),
    )

def _pending_response(user: User) -> PendingAccountResponse:
    return PendingAccountResponse(
        id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        role=user.role.value,
        status=user.status.value,
        submitted_credentials=_credentials(user),
    )

@router.get("/accounts/pending", response_model=PendingAccountsResponse)
async def list_pending_accounts(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require(Permission.APPROVE_DOCTORS)),
) -> PendingAccountsResponse:
    """List all pending accounts with name, email, and credentials (Req 4.1, 16.4)."""
    accounts = await account_service.list_pending_accounts(db)
    return PendingAccountsResponse(
        accounts=[_pending_response(u) for u in accounts]
    )

@router.post("/doctors/{user_id}/approve", response_model=MessageResponse)
async def approve_doctor(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require(Permission.APPROVE_DOCTORS)),
) -> MessageResponse:
    """Approve a pending Doctor: activate and send approval email (Req 4.2, 4.4)."""
    user = await account_service.approve_doctor(db, user_id=user_id)
    return MessageResponse(
        message="Doctor account approved.",
        detail=f"{user.full_name} is now active.",
    )

@router.post("/doctors/{user_id}/reject", response_model=MessageResponse)
async def reject_doctor(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require(Permission.APPROVE_DOCTORS)),
) -> MessageResponse:
    """Reject a pending Doctor: deny authentication going forward (Req 4.3)."""
    await account_service.reject_doctor(db, user_id=user_id)
    return MessageResponse(message="Doctor account rejected.")

@router.post("/accounts/{user_id}/deactivate", response_model=MessageResponse)
async def deactivate_account(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require(Permission.MANAGE_USERS)),
) -> MessageResponse:
    """Deactivate an account: deny authentication going forward (Req 16.3)."""
    await account_service.deactivate_account(db, user_id=user_id)
    return MessageResponse(message="Account deactivated.")
