"""Email delivery outbox model (Req 12)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import EmailDeliveryStatus

if TYPE_CHECKING:
    from app.models.clinical import Prescription

class EmailDelivery(Base):
    """Tracks prescription-email delivery attempts and outcome (Req 12.3, 12.4)."""

    __tablename__ = "email_deliveries"

    id: Mapped[uuid.UUID] = uuid_pk()
    prescription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prescriptions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[EmailDeliveryStatus] = mapped_column(
        pg_enum(EmailDeliveryStatus, "email_delivery_status"),
        nullable=False,
        default=EmailDeliveryStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    prescription: Mapped["Prescription"] = relationship(
        back_populates="email_delivery"
    )
