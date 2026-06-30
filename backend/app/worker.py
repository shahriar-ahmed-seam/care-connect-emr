"""Background worker: appointment reminders and the email outbox.

This module is the deployable background process (a separate Render service)
that runs two scheduled jobs:

- **Reminders** (Req 17.1, 17.2): periodically dispatches 24-hour and 1-hour
  appointment reminders via :func:`app.services.reminder_service.dispatch_due_reminders`.
- **Email outbox** (Req 12.3, 12.4): periodically retries any pending/failed
  prescription email deliveries via :func:`process_pending_email_deliveries`,
  regenerating the PDF and attempting delivery with bounded retries.

The job *logic* lives in the service layer and is unit-tested there; this module
only wires the schedule. Run it with ``python -m app.worker``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.models.delivery import EmailDelivery
from app.models.enums import EmailDeliveryStatus
from app.services import email_service, pdf_service, reminder_service

logger = logging.getLogger("careconnect.worker")

REMINDER_INTERVAL_SECONDS = 5 * 60
OUTBOX_INTERVAL_SECONDS = 2 * 60

async def process_pending_email_deliveries(session: AsyncSession) -> List[str]:
    """Attempt delivery for outbox rows not yet sent (Req 12.3, 12.4).

    Finds ``EmailDelivery`` rows still ``pending`` and re-attempts them by
    regenerating the prescription PDF and delivering with bounded retries.
    Returns the prescription ids processed.
    """
    pending = (
        await session.scalars(
            select(EmailDelivery).where(
                EmailDelivery.status == EmailDeliveryStatus.PENDING
            )
        )
    ).all()

    processed: List[str] = []
    for delivery in pending:
        try:
            pdf_bytes = await pdf_service.generate_prescription_pdf(
                session, delivery.prescription_id
            )
            await email_service.deliver_prescription_email(
                session, delivery.prescription_id, pdf_bytes=pdf_bytes
            )
            processed.append(str(delivery.prescription_id))
        except Exception:
            logger.exception(
                "Failed to process email delivery for prescription %s",
                delivery.prescription_id,
            )
    return processed

async def _run_reminders_job() -> None:
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            dispatched = await reminder_service.dispatch_due_reminders(
                session, now=datetime.now(timezone.utc)
            )
            await session.commit()
            if dispatched:
                logger.info("Dispatched %d appointment reminder(s)", len(dispatched))
        except Exception:
            await session.rollback()
            logger.exception("Reminder job failed")

async def _run_outbox_job() -> None:
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            processed = await process_pending_email_deliveries(session)
            await session.commit()
            if processed:
                logger.info("Processed %d outbox email(s)", len(processed))
        except Exception:
            await session.rollback()
            logger.exception("Outbox job failed")

def build_scheduler():
    """Build and configure the APScheduler instance with both jobs."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_reminders_job,
        "interval",
        seconds=REMINDER_INTERVAL_SECONDS,
        id="appointment_reminders",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_outbox_job,
        "interval",
        seconds=OUTBOX_INTERVAL_SECONDS,
        id="email_outbox",
        max_instances=1,
        coalesce=True,
    )
    return scheduler

def main() -> None:
    """Run the worker until interrupted."""
    logging.basicConfig(level=logging.INFO)
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Care-Connect worker started (reminders + email outbox).")
    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker shutting down.")
        scheduler.shutdown()

if __name__ == "__main__":
    main()
