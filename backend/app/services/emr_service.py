"""EMR_Service: patient medical history, vitals, diagnoses, and record views.

This module implements the clinical-record domain logic behind the EMR
endpoints (Requirements 9.1–9.5, 10.1). It is framework-light: every function
takes plain arguments plus an ``AsyncSession`` so it can be exercised directly
by property-based tests as well as wired into FastAPI routes.

Covered behaviour:

- **Vitals** (Req 9.1, 9.5): :func:`record_vitals` validates each numeric value
  to the inclusive 0–1000 range *before* encryption (Property 35), then stores
  the vitals record linked to the Patient and the Appointment. Values are
  persisted via :class:`~app.core.encryption.EncryptedType` (encrypted at rest).
- **Medical history** (Req 9.2): :func:`record_medical_history` stores a history
  entry (encrypted description + entry date) linked to the Patient.
- **Diagnosis** (Req 10.1): :func:`record_diagnosis` stores an encrypted
  free-text diagnosis linked to the Patient and the Appointment.
- **Record view** (Req 9.3, 9.4): :func:`get_patient_record` returns the
  Patient's history, vitals, diagnoses, and prescriptions, each ordered newest
  to oldest (reverse chronological — Property 34).

Every patient-data access is gated by
:func:`~app.services.rbac_service.authorize_patient_data_access` (row-level
scoping, Req 3.2–3.5) and recorded via
:func:`~app.services.rbac_service.record_patient_data_access` (audit, Req 13.5).

Functions ``flush`` their writes but do not ``commit``; the caller owns the
transaction boundary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_, datetime
from typing import List, Optional

from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models.appointment import Appointment
from app.models.clinical import (
    Diagnosis,
    MedicalHistory,
    Prescription,
    Vitals,
)
from app.models.user import User
from app.services.rbac_service import (
    authorize_patient_data_access,
    record_patient_data_access,
)

VITALS_MIN = 0.0
VITALS_MAX = 1000.0

_VITALS_FIELDS = ("blood_pressure", "heart_rate", "temperature", "weight")

@dataclass
class PatientRecord:
    """A Patient's full clinical record in reverse-chronological order (Req 9.3, 9.4)."""

    medical_history: List[MedicalHistory]
    vitals: List[Vitals]
    diagnoses: List[Diagnosis]
    prescriptions: List[Prescription]

def _validate_vitals_value(name: str, value: Optional[float]) -> Optional[str]:
    """Validate a single numeric vitals value and return its stored text form.

    Returns ``None`` for an absent value (the column is nullable). A value
    outside the inclusive 0–1000 range is rejected with an out-of-range error
    *before* any encryption/storage occurs (Req 9.5 — Property 35). The accepted
    value is stored as its canonical string form so that reading it back and
    parsing reproduces the original number (round-trip — Property 33).
    """
    if value is None:
        return None
    if value < VITALS_MIN or value > VITALS_MAX:
        raise AppError(
            "vitals-out-of-range",
            f"The {name} value must be between 0 and 1000.",
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            field=name,
        )
    return str(value)

async def _require_appointment_for_patient(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    patient_id: uuid.UUID,
) -> Appointment:
    """Load an Appointment and verify it belongs to ``patient_id``."""
    appointment = await session.get(Appointment, appointment_id)
    if appointment is None or appointment.patient_id != patient_id:
        raise AppError(
            "appointment-not-found",
            "No such appointment for this patient.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    return appointment

async def record_vitals(
    session: AsyncSession,
    *,
    actor: User,
    patient_id: uuid.UUID,
    appointment_id: uuid.UUID,
    blood_pressure: Optional[float] = None,
    heart_rate: Optional[float] = None,
    temperature: Optional[float] = None,
    weight: Optional[float] = None,
    recorded_at: Optional[datetime] = None,
) -> Vitals:
    """Record a Patient's vitals during/after an Appointment (Req 9.1, 9.5).

    Authorizes the access (Req 3.2–3.5), validates each provided numeric value
    to the inclusive 0–1000 range *before* encryption (Req 9.5 — Property 35),
    then stores the vitals record linked to the Patient and the Appointment
    (Property 33). The access is audited (Req 13.5).
    """
    await authorize_patient_data_access(session, user=actor, patient_id=patient_id)
    await _require_appointment_for_patient(
        session, appointment_id=appointment_id, patient_id=patient_id
    )

    values = {
        "blood_pressure": blood_pressure,
        "heart_rate": heart_rate,
        "temperature": temperature,
        "weight": weight,
    }
    stored = {
        name: _validate_vitals_value(name, value)
        for name, value in values.items()
    }

    vitals = Vitals(
        patient_id=patient_id,
        appointment_id=appointment_id,
        blood_pressure_enc=stored["blood_pressure"],
        heart_rate_enc=stored["heart_rate"],
        temperature_enc=stored["temperature"],
        weight_enc=stored["weight"],
    )
    if recorded_at is not None:
        vitals.recorded_at = recorded_at
    session.add(vitals)
    await session.flush()

    await record_patient_data_access(
        session,
        actor_user_id=actor.id,
        patient_id=patient_id,
        action="record_vitals",
    )
    return vitals

async def record_medical_history(
    session: AsyncSession,
    *,
    actor: User,
    patient_id: uuid.UUID,
    description: str,
    entry_date: date_,
) -> MedicalHistory:
    """Add a medical-history entry for a Patient (Req 9.2).

    Authorizes and audits the access, then stores the entry (encrypted
    description + entry date) linked to the Patient (Property 33).
    """
    await authorize_patient_data_access(session, user=actor, patient_id=patient_id)

    entry = MedicalHistory(
        patient_id=patient_id,
        description_enc=description,
        entry_date=entry_date,
    )
    session.add(entry)
    await session.flush()

    await record_patient_data_access(
        session,
        actor_user_id=actor.id,
        patient_id=patient_id,
        action="record_medical_history",
    )
    return entry

async def record_diagnosis(
    session: AsyncSession,
    *,
    actor: User,
    appointment_id: uuid.UUID,
    text: str,
    recorded_date: date_,
) -> Diagnosis:
    """Record a free-text diagnosis for an Appointment (Req 10.1).

    The diagnosis is linked to both the Patient (resolved from the Appointment)
    and the Appointment, and its free text is encrypted at rest. Authorizes and
    audits the access (Property 33).
    """
    appointment = await session.get(Appointment, appointment_id)
    if appointment is None:
        raise AppError(
            "appointment-not-found",
            "No such appointment.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    patient_id = appointment.patient_id
    await authorize_patient_data_access(
        session, user=actor, patient_id=patient_id, free_text=True
    )

    diagnosis = Diagnosis(
        patient_id=patient_id,
        appointment_id=appointment_id,
        text_enc=text,
        recorded_date=recorded_date,
    )
    session.add(diagnosis)
    await session.flush()

    await record_patient_data_access(
        session,
        actor_user_id=actor.id,
        patient_id=patient_id,
        action="record_diagnosis",
    )
    return diagnosis

async def get_patient_record(
    session: AsyncSession,
    *,
    actor: User,
    patient_id: uuid.UUID,
) -> PatientRecord:
    """Return a Patient's full clinical record, reverse-chronological (Req 9.3, 9.4).

    Authorizes the access (a Patient may view only their own record; a Doctor
    only a patient they have an appointment with — Req 3.2–3.5) and audits it
    (Req 13.5). The record includes consultation free-text (diagnoses), so an
    Admin request is denied. Each category is ordered by its timestamp from
    newest to oldest (Property 34).
    """
    await authorize_patient_data_access(
        session, user=actor, patient_id=patient_id, free_text=True
    )

    history = list(
        (
            await session.scalars(
                select(MedicalHistory)
                .where(MedicalHistory.patient_id == patient_id)
                .order_by(
                    MedicalHistory.entry_date.desc(),
                    MedicalHistory.created_at.desc(),
                )
            )
        ).all()
    )
    vitals = list(
        (
            await session.scalars(
                select(Vitals)
                .where(Vitals.patient_id == patient_id)
                .order_by(Vitals.recorded_at.desc())
            )
        ).all()
    )
    diagnoses = list(
        (
            await session.scalars(
                select(Diagnosis)
                .where(Diagnosis.patient_id == patient_id)
                .order_by(Diagnosis.recorded_date.desc())
            )
        ).all()
    )
    prescriptions = list(
        (
            await session.scalars(
                select(Prescription)
                .where(Prescription.patient_id == patient_id)
                .options(selectinload(Prescription.medications))
                .order_by(Prescription.issued_at.desc())
            )
        ).all()
    )

    await record_patient_data_access(
        session,
        actor_user_id=actor.id,
        patient_id=patient_id,
        action="view_record",
    )
    return PatientRecord(
        medical_history=history,
        vitals=vitals,
        diagnoses=diagnoses,
        prescriptions=prescriptions,
    )
