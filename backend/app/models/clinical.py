"""Clinical record models: medical history, vitals, diagnoses, prescriptions.

Sensitive free-text and measurement fields are stored encrypted at rest using
:class:`~app.core.encryption.EncryptedType` (the ``_enc`` columns), satisfying
Requirement 13.1. Service code reads/writes plaintext; storage holds only
AES-256-GCM ciphertext.
"""

from __future__ import annotations

import uuid
from datetime import date as date_, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedType
from app.models.base import Base, created_at_column, pg_enum, uuid_pk
from app.models.enums import PdfStatus

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.delivery import EmailDelivery
    from app.models.user import User

class MedicalHistory(Base):
    """A patient medical-history entry; description encrypted at rest (Req 9.2)."""

    __tablename__ = "medical_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description_enc: Mapped[str] = mapped_column(EncryptedType, nullable=False)
    entry_date: Mapped[date_] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    patient: Mapped["User"] = relationship(back_populates="medical_history")

class Vitals(Base):
    """Vitals captured during/after an appointment; values encrypted (Req 9.1).

    Numeric values are validated to the 0–1000 range (Req 9.5) by the service
    layer before encryption; they are persisted as encrypted text blobs.
    """

    __tablename__ = "vitals"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blood_pressure_enc: Mapped[Optional[str]] = mapped_column(
        EncryptedType, nullable=True
    )
    heart_rate_enc: Mapped[Optional[str]] = mapped_column(EncryptedType, nullable=True)
    temperature_enc: Mapped[Optional[str]] = mapped_column(
        EncryptedType, nullable=True
    )
    weight_enc: Mapped[Optional[str]] = mapped_column(EncryptedType, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    patient: Mapped["User"] = relationship()
    appointment: Mapped["Appointment"] = relationship(back_populates="vitals")

class Diagnosis(Base):
    """A consultation diagnosis; free-text encrypted, Admin-restricted (Req 3.5, 10.1)."""

    __tablename__ = "diagnoses"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text_enc: Mapped[str] = mapped_column(EncryptedType, nullable=False)
    recorded_date: Mapped[date_] = mapped_column(Date, nullable=False)

    patient: Mapped["User"] = relationship()
    appointment: Mapped["Appointment"] = relationship(back_populates="diagnoses")

class Prescription(Base):
    """A prescription with provenance (Req 10.5) and PDF status (Req 11.4)."""

    __tablename__ = "prescriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    doctor_name: Mapped[str] = mapped_column(Text, nullable=False)
    patient_name: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    pdf_status: Mapped[PdfStatus] = mapped_column(
        pg_enum(PdfStatus, "pdf_status"),
        nullable=False,
        default=PdfStatus.PENDING,
    )

    patient: Mapped["User"] = relationship(foreign_keys=[patient_id])
    doctor: Mapped["User"] = relationship(foreign_keys=[doctor_id])
    appointment: Mapped["Appointment"] = relationship(back_populates="prescription")
    medications: Mapped[List["Medication"]] = relationship(
        back_populates="prescription", cascade="all, delete-orphan"
    )
    email_delivery: Mapped[Optional["EmailDelivery"]] = relationship(
        back_populates="prescription", uselist=False, cascade="all, delete-orphan"
    )

class Medication(Base):
    """A medication line item belonging to a prescription (Req 10.2–10.4)."""

    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = uuid_pk()
    prescription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prescriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dosage: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    duration: Mapped[str] = mapped_column(Text, nullable=False)

    prescription: Mapped["Prescription"] = relationship(back_populates="medications")
