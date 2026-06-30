"""In-application notification model (Req 17.3, 17.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, pg_enum, uuid_pk
from app.models.enums import NotificationStatus

if TYPE_CHECKING:
    from app.models.user import User

class Notification(Base):
    """An in-app notification entry shown on a user's dashboard.

    Created ``unread`` (Req 17.3) and transitioned to ``read`` when the user
    marks it read (Req 17.4). The flexible ``payload`` JSONB carries
    type-specific data (e.g. appointment id, doctor name).
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"),
        nullable=False,
        default=NotificationStatus.UNREAD,
    )
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped["User"] = relationship(back_populates="notifications")
