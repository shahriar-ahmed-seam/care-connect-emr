"""Cross-cutting integration tests (task 24.1).

These exercise whole slices of the system end-to-end against a real PostgreSQL
database (via the module-scoped ``pg_sessionmaker``/``pg_loop`` fixtures that
create the schema from the ORM metadata):

- **Encryption at rest, end-to-end through PostgreSQL**: a clinical record is
  written via the ``EncryptedType`` column, the *raw* stored bytes are read back
  with plain SQL (bypassing the ORM decryptor) to confirm they are ciphertext,
  and the ORM read path returns the original plaintext (Req 13.1, 13.2).
- **Prescription → PDF → email pipeline**: a prescription is created, its PDF is
  generated, and the email is delivered through the outbox to a capturing mailer,
  asserting the attachment, body content, and status transitions (Req 11.1, 12.1,
  12.3).
"""

from __future__ import annotations

import os
import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.appointment import Appointment, AvailabilitySlot
from app.models.clinical import MedicalHistory
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
from app.services.mailer import CapturingMailer
from app.services.prescription_service import MedicationInput

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_PASSWORD = "password123"

def test_patient_data_encrypted_at_rest_through_postgres(
    pg_loop, pg_sessionmaker
) -> None:
    """A clinical note is stored as ciphertext yet reads back as plaintext."""
    secret = "রোগীর গোপন তথ্য — confidential note 12345"

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                patient = await auth_service.register_user(
                    session,
                    email=f"enc-{uuid.uuid4().hex}@example.com",
                    password=_PASSWORD,
                    full_name="Encryption Patient",
                    role=UserRole.PATIENT,
                )
                entry = MedicalHistory(
                    patient_id=patient.id,
                    description_enc=secret,
                    entry_date=date_(2030, 1, 1),
                )
                session.add(entry)
                await session.flush()
                entry_id = entry.id

                raw = await session.execute(
                    text("SELECT description_enc FROM medical_history WHERE id = :id"),
                    {"id": entry_id},
                )
                stored = raw.scalar_one()
                if isinstance(stored, memoryview):
                    stored = bytes(stored)
                assert isinstance(stored, (bytes, bytearray))
                assert secret.encode("utf-8") not in bytes(stored)

                session.expire(entry)
                reloaded = await session.get(MedicalHistory, entry_id)
                assert reloaded.description_enc == secret
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())

def test_prescription_pdf_email_pipeline(pg_loop, pg_sessionmaker) -> None:
    """Create a prescription, render the PDF, and deliver it via the outbox."""

    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await auth_service.register_user(
                    session,
                    email=f"doc-{uuid.uuid4().hex}@example.com",
                    password=_PASSWORD,
                    full_name="Dr. Integration",
                    role=UserRole.DOCTOR,
                )
                doctor.status = UserStatus.ACTIVE
                await session.flush()
                await profile_service.save_doctor_profile(
                    session,
                    doctor_id=doctor.id,
                    specialty="Medicine",
                    qualifications="MBBS",
                    consultation_fee_bdt=Decimal("600.00"),
                )
                patient = await auth_service.register_user(
                    session,
                    email=f"pat-{uuid.uuid4().hex}@example.com",
                    password=_PASSWORD,
                    full_name="Integration Patient",
                    role=UserRole.PATIENT,
                )

                slot = AvailabilitySlot(
                    doctor_id=doctor.id, date=date_(2030, 1, 1),
                    start_time=time(9, 0), end_time=time(9, 30),
                    status=SlotStatus.BOOKED,
                )
                session.add(slot)
                await session.flush()
                start = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
                appt = Appointment(
                    patient_id=patient.id, doctor_id=doctor.id, slot_id=slot.id,
                    status=AppointmentStatus.SCHEDULED,
                    fee_bdt_at_booking=Decimal("600.00"),
                    start_time=start, end_time=start + timedelta(minutes=30),
                )
                session.add(appt)
                await session.flush()

                rx = await prescription_service.create_prescription(
                    session, actor=doctor, appointment_id=appt.id,
                    medications=[MedicationInput("Napa", "500mg", "1+1+1", "5 days")],
                )

                pdf_bytes = await pdf_service.generate_prescription_pdf(session, rx.id)
                assert pdf_bytes.startswith(b"%PDF")

                stored = await prescription_service.get_prescription_with_medications(
                    session, rx.id
                )
                assert stored.pdf_status == PdfStatus.GENERATED

                mailer = CapturingMailer()
                delivery = await email_service.deliver_prescription_email(
                    session, rx.id, pdf_bytes=pdf_bytes, mailer=mailer
                )
                assert delivery.status == EmailDeliveryStatus.SENT
                assert len(mailer.sent) == 1
                sent = mailer.sent[0]
                assert sent.to == patient.email
                assert sent.attachment_bytes == pdf_bytes
                assert "Dr. Integration" in sent.body
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
