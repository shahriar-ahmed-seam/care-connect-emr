"""Audit-log and authentication-attempt models.

``audit_logs`` records every patient-data access (Req 13.5). ``auth_attempts``
backs the per-email failed-attempt lockout window (Req 2.4): 5 failures within
15 minutes locks authentication for 15 minutes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, pg_enum, uuid_pk
from app.models.enums import RevocationStatus

class AuditLog(Base):
    """An audit entry for a patient-data access event (Req 13.5)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()

class AuthAttempt(Base):
    """A single authentication attempt used for lockout accounting (Req 2.4).

    Each row records an attempt for an email with its success flag and time.
    The lockout logic counts failures for an email within the trailing
    15-minute window.
    """

    __tablename__ = "auth_attempts"
    __table_args__ = (
        Index("ix_auth_attempts_email_attempted", "email", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, index=True)
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

class RevokedToken(Base):
    """A session token that has been invalidated via logout (Req 2.5, 2.6).

    Logout records the token's unique ``jti`` here so that any subsequent
    request presenting the same token is rejected as unauthenticated
    (Property 9). ``expires_at`` lets a cleanup job prune rows once the token
    would have expired anyway. ``status`` distinguishes a successful revocation
    from one whose primary invalidation failed and is awaiting retry (Req 2.6).
    """

    __tablename__ = "revoked_tokens"
    __table_args__ = (
        Index("ix_revoked_tokens_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    jti: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    status: Mapped[RevocationStatus] = mapped_column(
        pg_enum(RevocationStatus, "revocation_status"),
        nullable=False,
        default=RevocationStatus.REVOKED,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
