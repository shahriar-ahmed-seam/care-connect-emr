"""Shared declarative base and common column helpers for ORM models.

All models inherit from :class:`Base`. A single declarative registry lets
Alembic discover the full schema via ``Base.metadata`` for migrations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    """Declarative base shared by every Care-Connect-EMR ORM model."""

def uuid_pk() -> Mapped[uuid.UUID]:
    """Return a UUID primary-key column with a server/client default."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

def created_at_column() -> Mapped[datetime]:
    """Return a ``created_at`` timestamptz column defaulting to now()."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

def pg_enum(enum_cls, name: str):
    """Build a PostgreSQL native ENUM column type from a Python enum.

    ``values_callable`` ensures the DB stores each member's ``value`` (e.g.
    ``"patient"``) rather than its Python member name, keeping the persisted
    vocabulary aligned with service code and the design's documented values.
    """
    from sqlalchemy import Enum as SAEnum

    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
    )
