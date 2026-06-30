"""Prescription_Service: create prescriptions with validation and provenance.

Implements prescription creation behind the ``POST /appointments/{id}/prescription``
endpoint (Requirements 10.2–10.5):

- A prescription must contain **at least one** medication entry (Req 10.3), and
  **every** entry must specify a name, dosage, frequency, and duration (Req 10.4).
  Validation runs *before* anything is stored, so an invalid prescription is
  rejected and nothing is persisted (Property 36). The error identifies the
  offending field (or the empty-list condition).
- A stored prescription records its provenance: the issuing Doctor's name, the
  Patient's name, and the issuance timestamp (Req 10.5 — Property 37). New
  prescriptions start with ``pdf_status = pending`` (Req 11.4); the PDF is
  rendered by :mod:`app.services.pdf_service`.

Access is gated by :func:`~app.services.rbac_service.authorize_patient_data_access`
(a Doctor may prescribe only for a patient they have an appointment with) and is
audited via :func:`~app.services.rbac_service.record_patient_data_access`
(Req 13.5).

Functions ``flush`` their writes but do not ``commit``; the caller owns the
transaction boundary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List, Sequence

from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models.appointment import Appointment
from app.models.clinical import Medication, Prescription
from app.models.enums import PdfStatus
from app.models.user import User
from app.services.rbac_service import (
    authorize_patient_data_access,
    record_patient_data_access,
)

REQUIRED_MEDICATION_FIELDS = ("name", "dosage", "frequency", "duration")

@dataclass
class MedicationInput:
    """A single medication line item supplied when creating a prescription.

    Fields are plain strings so that incomplete entries (empty/whitespace
    values) can be represented and rejected by validation (Req 10.4).
    """

    name: str = ""
    dosage: str = ""
    frequency: str = ""
    duration: str = ""

def _validate_medications(medications: Sequence[MedicationInput]) -> None:
    """Validate the medication list, raising before any storage occurs.

    Rejects an empty list (Req 10.3) and any entry missing one of the required
    fields (Req 10.4), identifying the offending field. This is the exact
    predicate Property 36 checks: a prescription is acceptable iff it has at
    least one entry and every entry specifies all four fields.
    """
    if len(medications) < 1:
        raise AppError(
            "prescription-no-medications",
            "A prescription requires at least one medication entry.",
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            field="medications",
        )
    for index, medication in enumerate(medications):
        for field_name in REQUIRED_MEDICATION_FIELDS:
            value = getattr(medication, field_name, "")
            if value is None or not str(value).strip():
                raise AppError(
                    "prescription-medication-incomplete",
                    f"Medication entry {index + 1} is missing its {field_name}.",
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    field=field_name,
                )

async def create_prescription(
    session: AsyncSession,
    *,
    actor: User,
    appointment_id: uuid.UUID,
    medications: Sequence[MedicationInput],
) -> Prescription:
    """Create a prescription for an Appointment (Req 10.2–10.5).

    Validates the medication list *before* storing anything (Property 36),
    authorizes the access (the issuing Doctor must have a relationship with the
    patient), records provenance (issuing Doctor name, Patient name, issuance
    timestamp — Property 37), and persists the prescription with
    ``pdf_status = pending`` plus its medication line items. The access is
    audited (Req 13.5).
    """

    _validate_medications(medications)

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

    patient = await session.get(User, patient_id)
    if patient is None:
        raise AppError(
            "patient-not-found",
            "No such patient.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    prescription = Prescription(
        patient_id=patient_id,
        doctor_id=actor.id,
        appointment_id=appointment_id,
        doctor_name=actor.full_name,
        patient_name=patient.full_name,
        pdf_status=PdfStatus.PENDING,
    )
    session.add(prescription)
    await session.flush()

    for medication in medications:
        session.add(
            Medication(
                prescription_id=prescription.id,
                name=medication.name.strip(),
                dosage=medication.dosage.strip(),
                frequency=medication.frequency.strip(),
                duration=medication.duration.strip(),
            )
        )
    await session.flush()

    await record_patient_data_access(
        session,
        actor_user_id=actor.id,
        patient_id=patient_id,
        action="create_prescription",
    )
    return prescription

async def get_prescription_with_medications(
    session: AsyncSession, prescription_id: uuid.UUID
) -> Prescription:
    """Load a prescription with its medications eagerly loaded, or raise 404."""
    prescription = await session.scalar(
        select(Prescription)
        .where(Prescription.id == prescription_id)
        .options(selectinload(Prescription.medications))
    )
    if prescription is None:
        raise AppError(
            "prescription-not-found",
            "No such prescription.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )
    return prescription
