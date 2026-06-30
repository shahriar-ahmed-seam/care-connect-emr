"""Availability slot and appointment models."""

from __future__ import annotations

import uuid
from datetime import date as date_, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    Time,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, pg_enum, uuid_pk
from app.models.enums import AppointmentStatus, SlotStatus

if TYPE_CHECKING:
    from app.models.clinical import Diagnosis, Prescription, Vitals
    from app.models.user import User

class AvailabilitySlot(Base):
    """A bookable time slot offered by a Doctor.

    A DB-level CHECK enforces ``start_time < end_time`` (Req 5.3). Non-overlap
    per doctor is enforced in the application layer (Req 5.4).
    """

    __tablename__ = "availability_slots"
    __table_args__ = (
        CheckConstraint(
            "start_time < end_time", name="ck_availability_slot_start_before_end"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[SlotStatus] = mapped_column(
        pg_enum(SlotStatus, "slot_status"),
        nullable=False,
        default=SlotStatus.AVAILABLE,
    )

    doctor: Mapped["User"] = relationship(
        back_populates="slots", foreign_keys=[doctor_id]
    )
    appointment: Mapped[Optional["Appointment"]] = relationship(
        back_populates="slot", uselist=False
    )

class Appointment(Base):
    """A scheduled consultation between a Patient and a Doctor.

    Records the consultation fee at booking time (Req 6.6) so later fee changes
    do not retroactively alter booked appointments.
    """

    __tablename__ = "appointments"

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
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("availability_slots.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"),
        nullable=False,
        default=AppointmentStatus.SCHEDULED,
    )
    fee_bdt_at_booking: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    patient: Mapped["User"] = relationship(
        back_populates="appointments_as_patient", foreign_keys=[patient_id]
    )
    doctor: Mapped["User"] = relationship(
        back_populates="appointments_as_doctor", foreign_keys=[doctor_id]
    )
    slot: Mapped["AvailabilitySlot"] = relationship(back_populates="appointment")
    vitals: Mapped[List["Vitals"]] = relationship(back_populates="appointment")
    diagnoses: Mapped[List["Diagnosis"]] = relationship(back_populates="appointment")
    prescription: Mapped[Optional["Prescription"]] = relationship(
        back_populates="appointment", uselist=False
    )
