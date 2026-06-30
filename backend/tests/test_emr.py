"""Property tests for EMR records, vitals, and diagnoses (tasks 11.3–11.5).

- Property 33: Patient clinical records round-trip and stay linked (Req 9.1, 9.2, 10.1).
- Property 34: Records are returned in reverse chronological order (Req 9.3, 9.4).
- Property 35: Out-of-range vitals are rejected (Req 9.5).

All run against a real PostgreSQL database via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures with per-example rollback for isolation.
Round-trip checks expire the session and reload from the database so the
encrypt-on-write / decrypt-on-read path is genuinely exercised.
"""

from __future__ import annotations

import os
import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import func, select

from app.core.errors import AppError
from app.models.appointment import Appointment, AvailabilitySlot
from app.models.clinical import Diagnosis, MedicalHistory, Prescription, Vitals
from app.models.enums import AppointmentStatus, PdfStatus, SlotStatus, UserRole, UserStatus
from app.services import auth_service, emr_service, profile_service
from tests.strategies import (
    out_of_range_vitals_values,
    slot_dates,
    unicode_text,
    valid_vitals_values,
)

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _make_active_doctor(session, *, name="Dr"):
    email = f"doc-{uuid.uuid4().hex}@example.com"
    doctor = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.DOCTOR,
    )
    doctor.status = UserStatus.ACTIVE
    await session.flush()
    await profile_service.save_doctor_profile(
        session,
        doctor_id=doctor.id,
        specialty="General",
        qualifications=None,
        consultation_fee_bdt=Decimal("500.00"),
    )
    return doctor

async def _make_patient(session, *, name="Pat"):
    email = f"pat-{uuid.uuid4().hex}@example.com"
    return await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name,
        role=UserRole.PATIENT,
    )

async def _make_appointment(session, *, doctor, patient, sdate=None):
    """Create a scheduled appointment (with its slot) linking doctor & patient."""
    sdate = sdate or date_(2030, 1, 1)
    slot = AvailabilitySlot(
        doctor_id=doctor.id,
        date=sdate,
        start_time=time(9, 0),
        end_time=time(9, 30),
        status=SlotStatus.BOOKED,
    )
    session.add(slot)
    await session.flush()
    start = datetime.combine(sdate, time(9, 0), tzinfo=timezone.utc)
    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor.id,
        slot_id=slot.id,
        status=AppointmentStatus.SCHEDULED,
        fee_bdt_at_booking=Decimal("500.00"),
        start_time=start,
        end_time=start + timedelta(minutes=30),
    )
    session.add(appointment)
    await session.flush()
    return appointment

@_db_required
@given(
    bp=valid_vitals_values,
    hr=valid_vitals_values,
    temp=valid_vitals_values,
    weight=valid_vitals_values,
    description=unicode_text,
    diagnosis_text=unicode_text,
    entry_date=slot_dates,
    recorded_date=slot_dates,
)
def test_clinical_records_round_trip_and_stay_linked(
    pg_loop, pg_sessionmaker, bp, hr, temp, weight, description,
    diagnosis_text, entry_date, recorded_date,
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appointment = await _make_appointment(
                    session, doctor=doctor, patient=patient
                )

                vitals = await emr_service.record_vitals(
                    session,
                    actor=doctor,
                    patient_id=patient.id,
                    appointment_id=appointment.id,
                    blood_pressure=bp,
                    heart_rate=hr,
                    temperature=temp,
                    weight=weight,
                )
                history = await emr_service.record_medical_history(
                    session,
                    actor=doctor,
                    patient_id=patient.id,
                    description=description,
                    entry_date=entry_date,
                )
                diagnosis = await emr_service.record_diagnosis(
                    session,
                    actor=doctor,
                    appointment_id=appointment.id,
                    text=diagnosis_text,
                    recorded_date=recorded_date,
                )

                vitals_id, history_id, diagnosis_id = (
                    vitals.id, history.id, diagnosis.id
                )
                patient_id = patient.id
                appointment_id = appointment.id

                session.expire_all()

                v = await session.get(Vitals, vitals_id)
                assert v.patient_id == patient_id
                assert v.appointment_id == appointment_id
                assert float(v.blood_pressure_enc) == bp
                assert float(v.heart_rate_enc) == hr
                assert float(v.temperature_enc) == temp
                assert float(v.weight_enc) == weight

                h = await session.get(MedicalHistory, history_id)
                assert h.patient_id == patient_id
                assert h.description_enc == description
                assert h.entry_date == entry_date

                d = await session.get(Diagnosis, diagnosis_id)
                assert d.patient_id == patient_id
                assert d.appointment_id == appointment_id
                assert d.text_enc == diagnosis_text
                assert d.recorded_date == recorded_date
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

def _is_non_increasing(values) -> bool:
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))

@_db_required
@given(
    history_offsets=st.lists(
        st.integers(min_value=0, max_value=2000), min_size=1, max_size=6, unique=True
    ),
    vitals_offsets=st.lists(
        st.integers(min_value=0, max_value=100000), min_size=1, max_size=6, unique=True
    ),
    diagnosis_offsets=st.lists(
        st.integers(min_value=0, max_value=2000), min_size=1, max_size=6, unique=True
    ),
    rx_offsets=st.lists(
        st.integers(min_value=0, max_value=100000), min_size=1, max_size=6, unique=True
    ),
)
def test_records_reverse_chronological(
    pg_loop, pg_sessionmaker, history_offsets, vitals_offsets,
    diagnosis_offsets, rx_offsets,
) -> None:
    base_date = date_(2025, 1, 1)
    base_dt = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appointment = await _make_appointment(
                    session, doctor=doctor, patient=patient
                )

                for off in history_offsets:
                    session.add(
                        MedicalHistory(
                            patient_id=patient.id,
                            description_enc="h",
                            entry_date=base_date + timedelta(days=off),
                        )
                    )
                for off in vitals_offsets:
                    session.add(
                        Vitals(
                            patient_id=patient.id,
                            appointment_id=appointment.id,
                            heart_rate_enc="70.0",
                            recorded_at=base_dt + timedelta(seconds=off),
                        )
                    )
                for off in diagnosis_offsets:
                    session.add(
                        Diagnosis(
                            patient_id=patient.id,
                            appointment_id=appointment.id,
                            text_enc="dx",
                            recorded_date=base_date + timedelta(days=off),
                        )
                    )

                for off in rx_offsets:
                    rx_appt = await _make_appointment(
                        session, doctor=doctor, patient=patient
                    )
                    session.add(
                        Prescription(
                            patient_id=patient.id,
                            doctor_id=doctor.id,
                            appointment_id=rx_appt.id,
                            doctor_name="Dr",
                            patient_name="Pat",
                            issued_at=base_dt + timedelta(seconds=off),
                            pdf_status=PdfStatus.PENDING,
                        )
                    )
                await session.flush()

                record = await emr_service.get_patient_record(
                    session, actor=doctor, patient_id=patient.id
                )

                assert _is_non_increasing([h.entry_date for h in record.medical_history])
                assert _is_non_increasing([v.recorded_at for v in record.vitals])
                assert _is_non_increasing([d.recorded_date for d in record.diagnoses])
                assert _is_non_increasing(
                    [p.issued_at for p in record.prescriptions]
                )
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(
    bad_value=out_of_range_vitals_values,
    field=st.sampled_from(
        ["blood_pressure", "heart_rate", "temperature", "weight"]
    ),
)
def test_out_of_range_vitals_rejected(
    pg_loop, pg_sessionmaker, bad_value, field
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appointment = await _make_appointment(
                    session, doctor=doctor, patient=patient
                )

                kwargs = {
                    "blood_pressure": None,
                    "heart_rate": None,
                    "temperature": None,
                    "weight": None,
                }
                kwargs[field] = bad_value

                with pytest.raises(AppError) as exc:
                    await emr_service.record_vitals(
                        session,
                        actor=doctor,
                        patient_id=patient.id,
                        appointment_id=appointment.id,
                        **kwargs,
                    )
                assert exc.value.code == "vitals-out-of-range"
                assert exc.value.field == field

                count = await session.scalar(
                    select(func.count())
                    .select_from(Vitals)
                    .where(Vitals.patient_id == patient.id)
                )
                assert count == 0
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
