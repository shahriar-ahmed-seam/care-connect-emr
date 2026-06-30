"""Dashboard routes for patient, doctor, and admin (Req 14, 15, 16)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require
from app.api.schemas import (
    AdminDashboardResponse,
    AdminUsersResponse,
    AppointmentSummary,
    DoctorDashboardResponse,
    MedicationResponse,
    PatientDashboardResponse,
    PrescriptionResponse,
    UserResponse,
    VitalsResponse,
)
from app.models.appointment import Appointment
from app.models.user import User
from app.services import dashboard_service
from app.services.dashboard_service import can_join
from app.services.rbac_service import Permission

router = APIRouter(tags=["dashboard"])

def _now() -> datetime:
    return datetime.now(timezone.utc)

async def _summary(db: AsyncSession, appt: Appointment, now: datetime) -> AppointmentSummary:
    doctor = await db.get(User, appt.doctor_id)
    patient = await db.get(User, appt.patient_id)
    return AppointmentSummary(
        id=str(appt.id),
        doctor_id=str(appt.doctor_id),
        patient_id=str(appt.patient_id),
        doctor_name=doctor.full_name if doctor else "",
        patient_name=patient.full_name if patient else "",
        start_time=appt.start_time.isoformat(),
        end_time=appt.end_time.isoformat(),
        status=appt.status.value,
        can_join=can_join(appt, now),
    )

def _vitals_response(v) -> VitalsResponse:
    def parse(x):
        return float(x) if x is not None else None

    return VitalsResponse(
        id=str(v.id),
        patient_id=str(v.patient_id),
        appointment_id=str(v.appointment_id),
        blood_pressure=parse(v.blood_pressure_enc),
        heart_rate=parse(v.heart_rate_enc),
        temperature=parse(v.temperature_enc),
        weight=parse(v.weight_enc),
        recorded_at=v.recorded_at.isoformat(),
    )

def _prescription_response(p) -> PrescriptionResponse:
    return PrescriptionResponse(
        id=str(p.id),
        patient_id=str(p.patient_id),
        doctor_id=str(p.doctor_id),
        appointment_id=str(p.appointment_id),
        doctor_name=p.doctor_name,
        patient_name=p.patient_name,
        issued_at=p.issued_at.isoformat(),
        pdf_status=p.pdf_status.value,
        medications=[
            MedicationResponse(
                id=str(m.id), name=m.name, dosage=m.dosage,
                frequency=m.frequency, duration=m.duration,
            )
            for m in p.medications
        ],
    )

@router.get("/patient/dashboard", response_model=PatientDashboardResponse)
async def patient_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Permission.VIEW_OWN_RECORDS)),
) -> PatientDashboardResponse:
    """Patient dashboard: upcoming appointments, prescriptions, vitals (Req 14)."""
    now = _now()
    upcoming = await dashboard_service.get_patient_upcoming_appointments(
        db, patient_id=user.id, now=now
    )
    prescriptions = await dashboard_service.get_patient_recent_prescriptions(
        db, patient_id=user.id
    )
    vitals = await dashboard_service.get_patient_vitals(db, patient_id=user.id)
    return PatientDashboardResponse(
        upcoming_appointments=[await _summary(db, a, now) for a in upcoming],
        recent_prescriptions=[_prescription_response(p) for p in prescriptions],
        vitals=[_vitals_response(v) for v in vitals],
    )

@router.get("/doctor/dashboard", response_model=DoctorDashboardResponse)
async def doctor_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Permission.VIEW_PATIENT_RECORDS)),
) -> DoctorDashboardResponse:
    """Doctor dashboard: today's appointments and pending-today count (Req 15)."""
    now = _now()
    today = await dashboard_service.get_doctor_today_appointments(
        db, doctor_id=user.id, now=now
    )
    pending = await dashboard_service.count_doctor_pending_today(
        db, doctor_id=user.id, now=now
    )
    return DoctorDashboardResponse(
        today_appointments=[await _summary(db, a, now) for a in today],
        pending_today=pending,
    )

@router.get("/admin/dashboard", response_model=AdminDashboardResponse)
async def admin_dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Permission.VIEW_ADMIN_DASHBOARD)),
) -> AdminDashboardResponse:
    """Admin dashboard counts (Req 16.1)."""
    total_patients, active_doctors, appts_today = await dashboard_service.admin_counts(
        db, now=_now()
    )
    return AdminDashboardResponse(
        total_patients=total_patients,
        active_doctors=active_doctors,
        appointments_today=appts_today,
    )

@router.get("/admin/users", response_model=AdminUsersResponse)
async def admin_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Permission.MANAGE_USERS)),
) -> AdminUsersResponse:
    """The full Admin user list with name, email, role, and status (Req 16.2)."""
    users = await dashboard_service.list_all_users(db)
    return AdminUsersResponse(
        users=[
            UserResponse(
                id=str(u.id),
                email=u.email,
                full_name=u.full_name,
                role=u.role.value,
                status=u.status.value,
            )
            for u in users
        ]
    )
