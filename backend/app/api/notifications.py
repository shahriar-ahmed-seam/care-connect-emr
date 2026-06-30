"""Notification routes: list and mark-read for the in-app feed (Req 17.3, 17.4).

- ``GET /notifications`` returns the current user's notifications, newest first.
- ``POST /notifications/{id}/read`` marks a notification read (idempotent).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.schemas import (
    NotificationResponse,
    NotificationsResponse,
)
from app.models.notification import Notification
from app.models.user import User
from app.services import inapp_notification_service

router = APIRouter(tags=["notifications"])

def _response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=str(notification.id),
        type=notification.type,
        payload=notification.payload,
        status=notification.status.value,
        created_at=notification.created_at.isoformat(),
    )

@router.get("/notifications", response_model=NotificationsResponse)
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationsResponse:
    """Return the current user's in-app notifications, newest first."""
    items = await inapp_notification_service.list_notifications(db, user_id=user.id)
    return NotificationsResponse(notifications=[_response(n) for n in items])

@router.post(
    "/notifications/{notification_id}/read", response_model=NotificationResponse
)
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationResponse:
    """Mark a notification as read (idempotent, Req 17.4)."""
    notification = await inapp_notification_service.mark_notification_read(
        db, notification_id=notification_id, user_id=user.id
    )
    return _response(notification)
