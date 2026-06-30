"""User account and doctor-profile models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, pg_enum, uuid_pk
from app.models.enums import LanguagePref, UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.appointment import AvailabilitySlot, Appointment
    from app.models.clinical import MedicalHistory, Prescription
    from app.models.notification import Notification

class User(Base):
    """A user account of any role (Patient, Doctor, or Admin).

    Email is a case-insensitive ``citext`` column with a UNIQUE constraint so
    duplicate registrations are rejected at the DB level (Req 1.2). Passwords
    are stored only as salted hashes (Req 1.6).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), nullable=False
    )
    language_pref: Mapped[Optional[LanguagePref]] = mapped_column(
        pg_enum(LanguagePref, "language_pref"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    doctor_profile: Mapped[Optional["DoctorProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    appointments_as_patient: Mapped[List["Appointment"]] = relationship(
        back_populates="patient", foreign_keys="Appointment.patient_id"
    )
    appointments_as_doctor: Mapped[List["Appointment"]] = relationship(
        back_populates="doctor", foreign_keys="Appointment.doctor_id"
    )
    slots: Mapped[List["AvailabilitySlot"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )
    medical_history: Mapped[List["MedicalHistory"]] = relationship(
        back_populates="patient"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="user"
    )

class DoctorProfile(Base):
    """Doctor-specific profile: specialty, qualifications, and fee (Req 5.1)."""

    __tablename__ = "doctor_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    specialty: Mapped[str] = mapped_column(Text, nullable=False)
    qualifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consultation_fee_bdt: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="doctor_profile")
