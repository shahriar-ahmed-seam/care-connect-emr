"""In-app notification persistence (Requirements 17.3, 17.4).

This module manages the ``notifications`` table that backs the in-application
notification feed shown on each user's dashboard:

- :func:`create_notification` writes a new notification for a user. Per Req 17.3
  every generated notification starts ``unread`` (Property 45).
- :func:`mark_notification_read` sets a notification's status to ``read`` and is
  idempotent — marking an already-read notification leaves it ``read``
  (Req 17.4 — Property 46).
- :func:`list_notifications` returns a user's notifications, newest first.
- :func:`reminder_already_sent` supports the reminders scheduler's de-duplication.

Functions ``flush`` their writes but do not ``commit``; the caller owns the
transaction boundary.
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional

from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import NotificationStatus
from app.models.notification import Notification

REMINDER_TYPE = "appointment_reminder"

async def create_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    payload: Optional[dict[str, Any]] = None,
) -> Notification:
    """Create an unread in-app notification for a user (Req 17.3 — Property 45)."""
    notification = Notification(
        user_id=user_id,
        type=type,
        payload=payload,
        status=NotificationStatus.UNREAD,
    )
    session.add(notification)
    await session.flush()
    return notification

async def list_notifications(
    session: AsyncSession, *, user_id: uuid.UUID
) -> List[Notification]:
    """Return a user's notifications, newest first."""
    return list(
        (
            await session.scalars(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc())
            )
        ).all()
    )

async def mark_notification_read(
    session: AsyncSession, *, notification_id: uuid.UUID, user_id: uuid.UUID
) -> Notification:
    """Mark a notification read, idempotently (Req 17.4 — Property 46).

    Setting an already-read notification to read leaves it ``read``. A
    notification belonging to another user is not found (fail-closed).
    """
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise AppError(
            "notification-not-found",
            "No such notification.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    notification.status = NotificationStatus.READ
    await session.flush()
    return notification

async def reminder_already_sent(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    appointment_id: uuid.UUID,
    kind: str,
) -> bool:
    """Return True if a reminder of ``kind`` was already created for this user.

    Used by the reminders scheduler to avoid sending duplicate reminders when
    its tick window overlaps a previous run.
    """
    rows = await session.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == REMINDER_TYPE,
        )
    )
    target = str(appointment_id)
    for row in rows:
        payload = row.payload or {}
        if payload.get("appointment_id") == target and payload.get("kind") == kind:
            return True
    return False
