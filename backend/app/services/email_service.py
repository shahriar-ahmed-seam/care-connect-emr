"""Email_Service: DB-backed outbox and bounded-retry delivery for prescriptions.

Implements prescription email delivery (Requirements 12.1–12.4):

- :func:`enqueue_prescription_email` creates (idempotently) an
  :class:`~app.models.delivery.EmailDelivery` outbox row for a prescription,
  starting in the ``pending`` state. The unique constraint on
  ``prescription_id`` keeps enqueueing idempotent.
- :func:`build_prescription_email` composes the message: the Patient is the
  recipient, the PDF is attached (Req 12.1), and the body includes the issuing
  Doctor's name and the issuance date (Req 12.2 — Property 40).
- :func:`deliver_prescription_email` performs delivery with bounded retries: it
  attempts to send at most :data:`MAX_DELIVERY_ATTEMPTS` (3) times; the first
  success records ``sent``, and exhausting all attempts records ``failed``
  (Req 12.3, 12.4 — Property 41). The mailer and a clock are injectable for
  testing.

Functions ``flush`` their writes but do not ``commit``; the caller owns the
transaction boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.delivery import EmailDelivery
from app.models.enums import EmailDeliveryStatus
from app.models.user import User
from app.services.mailer import EmailMessage, Mailer, get_mailer
from app.services.prescription_service import get_prescription_with_medications

MAX_DELIVERY_ATTEMPTS = 3

async def enqueue_prescription_email(
    session: AsyncSession, prescription_id: uuid.UUID
) -> EmailDelivery:
    """Create (or return the existing) outbox row for a prescription email.

    Idempotent: a prescription has at most one delivery row (unique
    ``prescription_id``). New rows start ``pending`` with zero attempts.
    """
    existing = await session.scalar(
        select(EmailDelivery).where(
            EmailDelivery.prescription_id == prescription_id
        )
    )
    if existing is not None:
        return existing

    delivery = EmailDelivery(
        prescription_id=prescription_id,
        status=EmailDeliveryStatus.PENDING,
        attempts=0,
    )
    session.add(delivery)
    await session.flush()
    return delivery

def build_prescription_email(
    *,
    to: str,
    doctor_name: str,
    issued_date: str,
    pdf_bytes: bytes,
    prescription_id: uuid.UUID,
) -> EmailMessage:
    """Compose the prescription email (Req 12.1, 12.2 — Property 40).

    The body includes the issuing Doctor's name and the issuance date, and the
    generated PDF is attached.
    """
    body = (
        "Dear patient,\n\n"
        "Please find attached your prescription from "
        f"Dr. {doctor_name}, issued on {issued_date}.\n\n"
        "You can also download it any time from your Care-Connect dashboard.\n\n"
        "Warm regards,\n"
        "Care-Connect"
    )
    return EmailMessage(
        to=to,
        subject=f"Your Care-Connect prescription ({issued_date})",
        body=body,
        attachment_bytes=pdf_bytes,
        attachment_filename=f"prescription-{prescription_id}.pdf",
        attachment_mime="application/pdf",
    )

async def deliver_prescription_email(
    session: AsyncSession,
    prescription_id: uuid.UUID,
    *,
    pdf_bytes: bytes,
    mailer: Optional[Mailer] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> EmailDelivery:
    """Deliver a prescription email with bounded retries (Req 12.1–12.4).

    Attempts delivery up to :data:`MAX_DELIVERY_ATTEMPTS` times. The first
    successful send sets the delivery status to ``sent``; if every attempt
    fails, the status is set to ``failed`` (Property 41). ``attempts`` records
    the number of attempts made (never exceeding the maximum), and
    ``last_attempt_at`` records the time of the final attempt.
    """
    mailer = mailer if mailer is not None else get_mailer()
    clock = now if now is not None else (lambda: datetime.now(timezone.utc))

    prescription = await get_prescription_with_medications(session, prescription_id)
    patient = await session.get(User, prescription.patient_id)
    if patient is None:
        raise AppError(
            "patient-not-found",
            "No such patient.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    delivery = await enqueue_prescription_email(session, prescription_id)

    if delivery.status == EmailDeliveryStatus.SENT:
        return delivery

    message = build_prescription_email(
        to=patient.email,
        doctor_name=prescription.doctor_name,
        issued_date=prescription.issued_at.strftime("%d/%m/%Y"),
        pdf_bytes=pdf_bytes,
        prescription_id=prescription_id,
    )

    while delivery.attempts < MAX_DELIVERY_ATTEMPTS:
        delivery.attempts += 1
        delivery.last_attempt_at = clock()
        try:
            mailer.send(message)
        except Exception:

            if delivery.attempts >= MAX_DELIVERY_ATTEMPTS:
                delivery.status = EmailDeliveryStatus.FAILED
            await session.flush()
            continue
        else:
            delivery.status = EmailDeliveryStatus.SENT
            await session.flush()
            return delivery

    await session.flush()
    return delivery
