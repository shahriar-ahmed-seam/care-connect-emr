"""Enumerated value sets used across the schema.

These Python ``enum.Enum`` classes are mapped to native PostgreSQL ``ENUM``
types by SQLAlchemy. Centralizing them keeps role/status/state vocabularies
consistent between models, migrations, and service code.

Note: ``values_callable`` is used at the column definition site so the DB
stores the enum *value* string (e.g. ``"patient"``) rather than the Python
member *name*.
"""

from __future__ import annotations

import enum

class UserRole(str, enum.Enum):
    """The role assigned to a user account."""

    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"

class UserStatus(str, enum.Enum):
    """Account lifecycle status (doctors start ``pending``; Req 1.5)."""

    ACTIVE = "active"
    PENDING = "pending"
    REJECTED = "rejected"
    INACTIVE = "inactive"

class LanguagePref(str, enum.Enum):
    """User display-language preference (defaults to English when null)."""

    BN = "bn"
    EN = "en"

class SlotStatus(str, enum.Enum):
    """Availability-slot booking status."""

    AVAILABLE = "available"
    BOOKED = "booked"

class AppointmentStatus(str, enum.Enum):
    """Appointment lifecycle status."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"

class PdfStatus(str, enum.Enum):
    """Prescription PDF generation status (Req 11.4)."""

    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"

class EmailDeliveryStatus(str, enum.Enum):
    """Prescription email delivery status (Req 12.3, 12.4)."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"

class NotificationStatus(str, enum.Enum):
    """In-application notification read status (Req 17.3, 17.4)."""

    UNREAD = "unread"
    READ = "read"

class RevocationStatus(str, enum.Enum):
    """Status of a revoked session token (Req 2.5, 2.6).

    ``revoked`` marks a token whose invalidation succeeded during logout.
    ``retry_pending`` marks a token whose invalidation failed and must be
    retried (the client session is ended regardless; Req 2.6).
    """

    REVOKED = "revoked"
    RETRY_PENDING = "retry_pending"
