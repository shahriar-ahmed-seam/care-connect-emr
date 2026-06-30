"""Prescription routes: creation, branded PDF download.

Wires the Prescription_Service, PDF_Generator, and Email_Service to the
prescription endpoints (Requirements 10.2–10.5, 11.1–11.4, 12.1):

- ``POST /appointments/{id}/prescription`` creates a prescription (Doctor only;
  at least one fully specified medication), renders its PDF, and enqueues the
  prescription email for delivery by the outbox worker.
- ``GET /prescriptions/{id}/pdf`` returns the branded prescription PDF for an
  authorized requester (the owning Patient or an authorized Doctor).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require
from app.api.schemas import PrescriptionCreateRequest, PrescriptionResponse, MedicationResponse
from app.models.user import User
from app.services import email_service, pdf_service, prescription_service
from app.services.pdf_service import PdfGenerationError
from app.services.prescription_service import MedicationInput
from app.services.rbac_service import Permission, authorize_patient_data_access

router = APIRouter(tags=["prescriptions"])

def _prescription_response(prescription) -> PrescriptionResponse:
    return PrescriptionResponse(
        id=str(prescription.id),
        patient_id=str(prescription.patient_id),
        doctor_id=str(prescription.doctor_id),
        appointment_id=str(prescription.appointment_id),
        doctor_name=prescription.doctor_name,
        patient_name=prescription.patient_name,
        issued_at=prescription.issued_at.isoformat(),
        pdf_status=prescription.pdf_status.value,
        medications=[
            MedicationResponse(
                id=str(med.id),
                name=med.name,
                dosage=med.dosage,
                frequency=med.frequency,
                duration=med.duration,
            )
            for med in prescription.medications
        ],
    )

@router.post(
    "/appointments/{appointment_id}/prescription",
    response_model=PrescriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prescription(
    appointment_id: uuid.UUID,
    payload: PrescriptionCreateRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require(Permission.CREATE_PRESCRIPTION)),
) -> PrescriptionResponse:
    """Create a prescription, render its PDF, and enqueue its email (Req 10.2–12.1)."""
    prescription = await prescription_service.create_prescription(
        db,
        actor=actor,
        appointment_id=appointment_id,
        medications=[
            MedicationInput(
                name=m.name, dosage=m.dosage, frequency=m.frequency, duration=m.duration
            )
            for m in payload.medications
        ],
    )

    try:
        await pdf_service.generate_prescription_pdf(db, prescription.id)
        await email_service.enqueue_prescription_email(db, prescription.id)
    except PdfGenerationError:

        pass

    prescription = await prescription_service.get_prescription_with_medications(
        db, prescription.id
    )
    return _prescription_response(prescription)

@router.get("/prescriptions/{prescription_id}/pdf")
async def download_prescription_pdf(
    prescription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Response:
    """Return the branded prescription PDF for an authorized requester (Req 11.3)."""
    prescription = await prescription_service.get_prescription_with_medications(
        db, prescription_id
    )

    await authorize_patient_data_access(
        db, user=actor, patient_id=prescription.patient_id, free_text=True
    )

    pdf_bytes = await pdf_service.generate_prescription_pdf(db, prescription_id)
    filename = f"prescription-{prescription_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
