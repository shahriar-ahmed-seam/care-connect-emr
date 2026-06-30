"""EMR routes: patient records, vitals, medical history, and diagnoses.

Wires the EMR_Service to the clinical-record endpoints (Requirements 9.1–9.5,
10.1):

- ``POST /patients/{id}/vitals`` records vitals (Doctor only; values validated
  to 0–1000 before encryption).
- ``POST /patients/{id}/history`` adds a medical-history entry (Doctor only).
- ``GET /patients/{id}/record`` returns the full record (history, vitals,
  diagnoses, prescriptions) in reverse chronological order. Accessible to the
  Patient (own record) and an authorized Doctor; row-level scoping is enforced
  by the service.
- ``POST /appointments/{id}/diagnosis`` records an encrypted free-text diagnosis
  linked to the Patient and the Appointment (Doctor only).

Write endpoints require Doctor permissions via ``require(...)``; the record-view
endpoint resolves the current user and lets the EMR_Service apply row-level
scoping (so both Patients and Doctors are handled correctly).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require
from app.api.schemas import (
    DiagnosisRequest,
    DiagnosisResponse,
    MedicalHistoryRequest,
    MedicalHistoryResponse,
    MedicationResponse,
    PatientRecordResponse,
    PrescriptionResponse,
    VitalsRequest,
    VitalsResponse,
)
from app.models.clinical import Diagnosis, MedicalHistory, Prescription, Vitals
from app.models.user import User
from app.services import emr_service
from app.services.rbac_service import Permission

router = APIRouter(tags=["emr"])

def _parse_value(stored: Optional[str]) -> Optional[float]:
    """Parse a decrypted vitals text value back to a float, or ``None``."""
    return float(stored) if stored is not None else None

def _vitals_response(vitals: Vitals) -> VitalsResponse:
    return VitalsResponse(
        id=str(vitals.id),
        patient_id=str(vitals.patient_id),
        appointment_id=str(vitals.appointment_id),
        blood_pressure=_parse_value(vitals.blood_pressure_enc),
        heart_rate=_parse_value(vitals.heart_rate_enc),
        temperature=_parse_value(vitals.temperature_enc),
        weight=_parse_value(vitals.weight_enc),
        recorded_at=vitals.recorded_at.isoformat(),
    )

def _history_response(entry: MedicalHistory) -> MedicalHistoryResponse:
    return MedicalHistoryResponse(
        id=str(entry.id),
        patient_id=str(entry.patient_id),
        description=entry.description_enc,
        entry_date=entry.entry_date.isoformat(),
        created_at=entry.created_at.isoformat(),
    )

def _diagnosis_response(diagnosis: Diagnosis) -> DiagnosisResponse:
    return DiagnosisResponse(
        id=str(diagnosis.id),
        patient_id=str(diagnosis.patient_id),
        appointment_id=str(diagnosis.appointment_id),
        text=diagnosis.text_enc,
        recorded_date=diagnosis.recorded_date.isoformat(),
    )

def _prescription_response(prescription: Prescription) -> PrescriptionResponse:
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
    "/patients/{patient_id}/vitals",
    response_model=VitalsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_vitals(
    patient_id: uuid.UUID,
    payload: VitalsRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require(Permission.EDIT_PATIENT_RECORDS)),
) -> VitalsResponse:
    """Record vitals for a Patient (Req 9.1, 9.5)."""
    vitals = await emr_service.record_vitals(
        db,
        actor=actor,
        patient_id=patient_id,
        appointment_id=payload.appointment_id,
        blood_pressure=payload.blood_pressure,
        heart_rate=payload.heart_rate,
        temperature=payload.temperature,
        weight=payload.weight,
    )
    return _vitals_response(vitals)

@router.post(
    "/patients/{patient_id}/history",
    response_model=MedicalHistoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_medical_history(
    patient_id: uuid.UUID,
    payload: MedicalHistoryRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require(Permission.EDIT_PATIENT_RECORDS)),
) -> MedicalHistoryResponse:
    """Add a medical-history entry for a Patient (Req 9.2)."""
    entry = await emr_service.record_medical_history(
        db,
        actor=actor,
        patient_id=patient_id,
        description=payload.description,
        entry_date=payload.entry_date,
    )
    return _history_response(entry)

@router.get(
    "/patients/{patient_id}/record",
    response_model=PatientRecordResponse,
)
async def get_patient_record(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> PatientRecordResponse:
    """Return a Patient's full record in reverse chronological order (Req 9.3, 9.4)."""
    record = await emr_service.get_patient_record(
        db, actor=actor, patient_id=patient_id
    )
    return PatientRecordResponse(
        medical_history=[_history_response(e) for e in record.medical_history],
        vitals=[_vitals_response(v) for v in record.vitals],
        diagnoses=[_diagnosis_response(d) for d in record.diagnoses],
        prescriptions=[_prescription_response(p) for p in record.prescriptions],
    )

@router.post(
    "/appointments/{appointment_id}/diagnosis",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_diagnosis(
    appointment_id: uuid.UUID,
    payload: DiagnosisRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require(Permission.RECORD_DIAGNOSIS)),
) -> DiagnosisResponse:
    """Record a free-text diagnosis for an Appointment (Req 10.1)."""
    diagnosis = await emr_service.record_diagnosis(
        db,
        actor=actor,
        appointment_id=appointment_id,
        text=payload.text,
        recorded_date=payload.recorded_date,
    )
    return _diagnosis_response(diagnosis)
