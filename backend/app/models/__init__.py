"""SQLAlchemy ORM models and the shared declarative base.

Importing this package registers every model with ``Base.metadata`` so that
Alembic and ``metadata.create_all`` see the complete schema.
"""

from app.models.appointment import Appointment, AvailabilitySlot
from app.models.audit import AuditLog, AuthAttempt, RevokedToken
from app.models.base import Base
from app.models.clinical import (
    Diagnosis,
    Medication,
    MedicalHistory,
    Prescription,
    Vitals,
)
from app.models.delivery import EmailDelivery
from app.models.enums import (
    AppointmentStatus,
    EmailDeliveryStatus,
    LanguagePref,
    NotificationStatus,
    PdfStatus,
    RevocationStatus,
    SlotStatus,
    UserRole,
    UserStatus,
)
from app.models.notification import Notification
from app.models.user import DoctorProfile, User

__all__ = [
    "Base",

    "User",
    "DoctorProfile",

    "AvailabilitySlot",
    "Appointment",

    "MedicalHistory",
    "Vitals",
    "Diagnosis",
    "Prescription",
    "Medication",

    "EmailDelivery",
    "Notification",

    "AuditLog",
    "AuthAttempt",
    "RevokedToken",

    "UserRole",
    "UserStatus",
    "LanguagePref",
    "SlotStatus",
    "AppointmentStatus",
    "PdfStatus",
    "EmailDeliveryStatus",
    "NotificationStatus",
    "RevocationStatus",
]
