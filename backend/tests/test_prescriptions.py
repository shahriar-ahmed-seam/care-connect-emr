"""Property and unit tests for prescriptions, PDF generation, and email (task 12).

- Property 36: Prescriptions require at least one fully specified medication
  (Req 10.2, 10.3, 10.4).
- Property 37: Stored prescriptions record provenance (Req 10.5).
- Property 38: Generated PDF content matches the stored prescription (Req 11.1, 11.2).
- Property 39: PDF generation failure retains the record (Req 11.4).
- Property 40: Prescription email body includes doctor and date (Req 12.2).
- Property 41: Email delivery retries are bounded and recorded (Req 12.3, 12.4).
- Unit (12.10): authorized PDF download (11.3) and email sent with PDF attached (12.1).

DB-backed tests run against PostgreSQL via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures with per-example rollback.
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
from app.models.clinical import Medication, Prescription
from app.models.delivery import EmailDelivery
from app.models.enums import (
    AppointmentStatus,
    EmailDeliveryStatus,
    PdfStatus,
    SlotStatus,
    UserRole,
    UserStatus,
)
from app.services import (
    auth_service,
    email_service,
    pdf_service,
    prescription_service,
    profile_service,
)
from app.services.mailer import CapturingMailer, EmailMessage, MailerError
from app.services.pdf_service import PdfGenerationError
from app.services.prescription_service import MedicationInput
from tests.strategies import full_names, valid_medications

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

async def _make_active_doctor(session, *, name="Dr. Rahman"):
    email = f"doc-{uuid.uuid4().hex}@example.com"
    doctor = await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name, role=UserRole.DOCTOR
    )
    doctor.status = UserStatus.ACTIVE
    await session.flush()
    await profile_service.save_doctor_profile(
        session,
        doctor_id=doctor.id,
        specialty="Cardiology",
        qualifications="MBBS, FCPS",
        consultation_fee_bdt=Decimal("800.00"),
    )
    return doctor

async def _make_patient(session, *, name="Karim Ahmed"):
    email = f"pat-{uuid.uuid4().hex}@example.com"
    return await auth_service.register_user(
        session, email=email, password=_PASSWORD, full_name=name, role=UserRole.PATIENT
    )

async def _make_appointment(session, *, doctor, patient):
    sdate = date_(2030, 1, 1)
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
        fee_bdt_at_booking=Decimal("800.00"),
        start_time=start,
        end_time=start + timedelta(minutes=30),
    )
    session.add(appointment)
    await session.flush()
    return appointment

def _inputs(meds):
    return [MedicationInput(**m) for m in meds]

@_db_required
@given(
    meds=valid_medications(),
    mode=st.sampled_from(["valid", "empty", "missing_field"]),
    missing_field=st.sampled_from(["name", "dosage", "frequency", "duration"]),
    blank=st.sampled_from(["", "   ", "\t"]),
)
def test_prescription_medication_validation(
    pg_loop, pg_sessionmaker, meds, mode, missing_field, blank
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appt = await _make_appointment(session, doctor=doctor, patient=patient)

                if mode == "valid":
                    rx = await prescription_service.create_prescription(
                        session, actor=doctor, appointment_id=appt.id,
                        medications=_inputs(meds),
                    )
                    stored = await prescription_service.get_prescription_with_medications(
                        session, rx.id
                    )
                    assert len(stored.medications) == len(meds)
                    return

                if mode == "empty":
                    bad = []
                    expected_code = "prescription-no-medications"
                else:
                    bad = [dict(m) for m in meds]
                    bad[0][missing_field] = blank
                    expected_code = "prescription-medication-incomplete"

                with pytest.raises(AppError) as exc:
                    await prescription_service.create_prescription(
                        session, actor=doctor, appointment_id=appt.id,
                        medications=_inputs(bad),
                    )
                assert exc.value.code == expected_code

                count = await session.scalar(
                    select(func.count()).select_from(Prescription)
                    .where(Prescription.appointment_id == appt.id)
                )
                assert count == 0
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(meds=valid_medications(), doctor_name=full_names, patient_name=full_names)
def test_prescription_records_provenance(
    pg_loop, pg_sessionmaker, meds, doctor_name, patient_name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=doctor_name)
                patient = await _make_patient(session, name=patient_name)
                appt = await _make_appointment(session, doctor=doctor, patient=patient)

                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=_inputs(meds),
                )
                stored = await prescription_service.get_prescription_with_medications(
                    session, rx.id
                )
                assert stored.doctor_name == doctor_name
                assert stored.patient_name == patient_name
                assert stored.issued_at is not None
                assert stored.pdf_status == PdfStatus.PENDING
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(meds=valid_medications(), doctor_name=full_names, patient_name=full_names)
def test_generated_pdf_matches_stored_prescription(
    pg_loop, pg_sessionmaker, meds, doctor_name, patient_name
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session, name=doctor_name)
                patient = await _make_patient(session, name=patient_name)
                appt = await _make_appointment(session, doctor=doctor, patient=patient)
                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=_inputs(meds),
                )
                stored = await prescription_service.get_prescription_with_medications(
                    session, rx.id
                )

                doc = await pdf_service.build_document(session, rx.id)

                assert doc.doctor_name == stored.doctor_name == doctor_name
                assert doc.patient_name == stored.patient_name == patient_name
                assert doc.doctor_specialty == "Cardiology"
                assert doc.clinic_name == pdf_service.DEFAULT_CLINIC_NAME
                assert doc.issued_date == stored.issued_at.strftime("%d/%m/%Y")
                assert len(doc.medications) == len(stored.medications)
                stored_meds = {
                    (m.name, m.dosage, m.frequency, m.duration)
                    for m in stored.medications
                }
                doc_meds = {
                    (m.name, m.dosage, m.frequency, m.duration)
                    for m in doc.medications
                }
                assert doc_meds == stored_meds

                pdf_bytes = pdf_service.render_pdf(doc)
                assert isinstance(pdf_bytes, bytes)
                assert pdf_bytes.startswith(b"%PDF")
                assert len(pdf_bytes) > 500
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
@given(meds=valid_medications())
def test_pdf_generation_failure_retains_record(
    pg_loop, pg_sessionmaker, meds
) -> None:
    def _failing_renderer(_document):
        raise RuntimeError("simulated rendering failure")

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appt = await _make_appointment(session, doctor=doctor, patient=patient)
                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=_inputs(meds),
                )

                with pytest.raises(PdfGenerationError):
                    await pdf_service.generate_prescription_pdf(
                        session, rx.id, renderer=_failing_renderer
                    )

                stored = await session.get(Prescription, rx.id)
                assert stored is not None
                assert stored.pdf_status == PdfStatus.FAILED
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@given(doctor_name=full_names, day=st.integers(1, 28), month=st.integers(1, 12))
def test_prescription_email_body_includes_doctor_and_date(
    doctor_name, day, month
) -> None:
    issued_date = f"{day:02d}/{month:02d}/2030"
    message = email_service.build_prescription_email(
        to="patient@example.com",
        doctor_name=doctor_name,
        issued_date=issued_date,
        pdf_bytes=b"%PDF-1.4 fake",
        prescription_id=uuid.uuid4(),
    )
    assert doctor_name in message.body
    assert issued_date in message.body
    assert message.attachment_bytes == b"%PDF-1.4 fake"

@_db_required
@given(meds=valid_medications(), succeeds=st.booleans())
def test_email_delivery_retries_bounded(
    pg_loop, pg_sessionmaker, meds, succeeds
) -> None:
    class _FailingMailer:
        def send(self, message: EmailMessage) -> None:
            raise MailerError("simulated send failure")

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appt = await _make_appointment(session, doctor=doctor, patient=patient)
                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=_inputs(meds),
                )

                mailer = CapturingMailer() if succeeds else _FailingMailer()
                delivery = await email_service.deliver_prescription_email(
                    session, rx.id, pdf_bytes=b"%PDF-1.4 fake", mailer=mailer
                )

                if succeeds:
                    assert delivery.status == EmailDeliveryStatus.SENT
                    assert delivery.attempts == 1
                else:
                    assert delivery.status == EmailDeliveryStatus.FAILED
                    assert delivery.attempts == email_service.MAX_DELIVERY_ATTEMPTS
                    assert delivery.attempts <= 3
                assert delivery.last_attempt_at is not None
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
def test_pdf_download_authorization(pg_loop, pg_sessionmaker) -> None:
    """Authorized requesters get the PDF; an unrelated patient is denied (Req 11.3)."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                other = await _make_patient(session, name="Other Patient")
                appt = await _make_appointment(session, doctor=doctor, patient=patient)
                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=[MedicationInput("Napa", "500mg", "TDS", "5 days")],
                )

                from app.services.rbac_service import authorize_patient_data_access

                await authorize_patient_data_access(
                    session, user=patient, patient_id=rx.patient_id, free_text=True
                )
                pdf_bytes = await pdf_service.generate_prescription_pdf(session, rx.id)
                assert pdf_bytes.startswith(b"%PDF")

                with pytest.raises(AppError) as exc:
                    await authorize_patient_data_access(
                        session, user=other, patient_id=rx.patient_id, free_text=True
                    )
                assert exc.value.code == "authorization-error"
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

@_db_required
def test_email_sent_with_pdf_attachment(pg_loop, pg_sessionmaker) -> None:
    """The prescription email is sent with the PDF attached (Req 12.1)."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                appt = await _make_appointment(session, doctor=doctor, patient=patient)
                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=[MedicationInput("Napa", "500mg", "TDS", "5 days")],
                )
                pdf_bytes = await pdf_service.generate_prescription_pdf(session, rx.id)

                mailer = CapturingMailer()
                delivery = await email_service.deliver_prescription_email(
                    session, rx.id, pdf_bytes=pdf_bytes, mailer=mailer
                )

                assert delivery.status == EmailDeliveryStatus.SENT
                assert len(mailer.sent) == 1
                sent = mailer.sent[0]
                assert sent.to == patient.email
                assert sent.attachment_bytes == pdf_bytes
                assert sent.attachment_filename == f"prescription-{rx.id}.pdf"
                assert doctor.full_name in sent.body
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
