"""PDF_Generator: render a professional, branded prescription PDF.

Implements prescription PDF generation (Requirements 11.1–11.4):

- :func:`build_document` projects a stored prescription into a
  :class:`PrescriptionDocument` — the exact content that gets rendered: the
  clinic name and logo, the issuing Doctor's name and specialty, the Patient's
  name, the issuance date, and every medication entry with its name, dosage,
  frequency, and duration (Req 11.1). Because the document is built directly
  from the stored record, its content matches that record (Req 11.2 —
  Property 38).
- :func:`render_pdf` renders a :class:`PrescriptionDocument` into PDF bytes.
- :func:`generate_prescription_pdf` orchestrates loading + rendering and updates
  ``pdf_status``: ``generated`` on success, ``failed`` on error. On failure it
  raises :class:`PdfGenerationError` and the stored prescription record is
  retained for retry (Req 11.4 — Property 39).

Implementation note: the renderer uses ``fpdf2`` (pure Python, no native
dependencies) so PDF generation behaves identically on Windows (local/test) and
Linux (Render production). The design originally named WeasyPrint; fpdf2 was
chosen for portability and testability. ``fpdf2``'s core fonts are latin-1 only,
so non-latin glyphs (e.g. Bangla) are transliterated to a safe representation in
the rendered bytes; the structured :class:`PrescriptionDocument` and the stored
record always retain the original text. A bundled Bengali TTF can be added later
for full glyph fidelity in the PDF itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PdfStatus
from app.models.user import DoctorProfile
from app.services.prescription_service import get_prescription_with_medications

DEFAULT_CLINIC_NAME = "Care-Connect"

class PdfGenerationError(Exception):
    """Raised when rendering a prescription PDF fails (Req 11.4)."""

@dataclass(frozen=True)
class MedicationRow:
    """A single medication row as rendered on the PDF (Req 11.1)."""

    name: str
    dosage: str
    frequency: str
    duration: str

@dataclass
class PrescriptionDocument:
    """The full content rendered onto a prescription PDF (Req 11.1).

    Built directly from the stored prescription so that the document — and thus
    the PDF rendered from it — matches the stored record (Req 11.2).
    """

    clinic_name: str
    doctor_name: str
    doctor_specialty: str
    patient_name: str
    issued_date: str
    medications: List[MedicationRow] = field(default_factory=list)
    clinic_logo_path: Optional[str] = None

async def build_document(
    session: AsyncSession,
    prescription_id: uuid.UUID,
    *,
    clinic_name: str = DEFAULT_CLINIC_NAME,
    clinic_logo_path: Optional[str] = None,
) -> PrescriptionDocument:
    """Project a stored prescription into a :class:`PrescriptionDocument`.

    Resolves the issuing Doctor's specialty from their profile (falling back to
    a neutral label when no profile exists). The returned document carries every
    field required on the PDF, matching the stored record (Property 38).
    """
    prescription = await get_prescription_with_medications(session, prescription_id)

    profile = await session.get(DoctorProfile, prescription.doctor_id)

    if profile is None or profile.user_id != prescription.doctor_id:
        from sqlalchemy import select

        profile = await session.scalar(
            select(DoctorProfile).where(
                DoctorProfile.user_id == prescription.doctor_id
            )
        )
    specialty = profile.specialty if profile is not None else "General Practitioner"

    return PrescriptionDocument(
        clinic_name=clinic_name,
        doctor_name=prescription.doctor_name,
        doctor_specialty=specialty,
        patient_name=prescription.patient_name,
        issued_date=prescription.issued_at.strftime("%d/%m/%Y"),
        medications=[
            MedicationRow(
                name=med.name,
                dosage=med.dosage,
                frequency=med.frequency,
                duration=med.duration,
            )
            for med in prescription.medications
        ],
        clinic_logo_path=clinic_logo_path,
    )

def _safe(text: str) -> str:
    """Make text safe for fpdf2 core (latin-1) fonts without crashing.

    Non-latin-1 characters are replaced so rendering never raises; the original
    text is preserved in the document model and the stored record.
    """
    return text.encode("latin-1", "replace").decode("latin-1")

def render_pdf(document: PrescriptionDocument) -> bytes:
    """Render a :class:`PrescriptionDocument` into PDF bytes.

    Produces a clean, professional single-page prescription: a branded header,
    doctor/patient/date block, and a medication table. Raises
    :class:`PdfGenerationError` if the underlying renderer fails.
    """
    try:
        from fpdf import FPDF

        pdf = FPDF(format="A4", unit="mm")
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()

        if document.clinic_logo_path:
            try:
                pdf.image(document.clinic_logo_path, x=10, y=10, h=18)
            except Exception:

                pass

        pdf.set_xy(10, 12)
        pdf.set_text_color(13, 110, 116)
        pdf.set_font("Helvetica", "B", 22)
        pdf.cell(0, 10, text=_safe(document.clinic_name), new_x="LMARGIN", new_y="NEXT")

        pdf.set_text_color(90, 90, 90)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(
            0, 6, text="Telemedicine & EMR  -  Prescription",
            new_x="LMARGIN", new_y="NEXT",
        )

        pdf.set_draw_color(13, 110, 116)
        pdf.set_line_width(0.6)
        y = pdf.get_y() + 2
        pdf.line(10, y, 200, y)
        pdf.ln(8)

        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, text=_safe(f"Dr. {document.doctor_name}"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 6, text=_safe(document.doctor_specialty),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(95, 7, text=_safe(f"Patient: {document.patient_name}"))
        pdf.cell(0, 7, text=f"Date: {document.issued_date}",
                 new_x="LMARGIN", new_y="NEXT", align="R")
        pdf.ln(4)

        headers = ["Medication", "Dosage", "Frequency", "Duration"]
        widths = [70, 35, 45, 40]
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(13, 110, 116)
        pdf.set_text_color(255, 255, 255)
        for header, width in zip(headers, widths):
            pdf.cell(width, 9, text=header, border=0, fill=True, align="L")
        pdf.ln(9)

        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "", 10)
        fill = False
        for med in document.medications:
            pdf.set_fill_color(238, 246, 246)
            row = [med.name, med.dosage, med.frequency, med.duration]
            for value, width in zip(row, widths):
                pdf.cell(width, 8, text=_safe(value), border="B", fill=fill, align="L")
            pdf.ln(8)
            fill = not fill

        pdf.ln(12)
        pdf.set_text_color(150, 150, 150)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(
            0, 5,
            text="This prescription was generated electronically by Care-Connect.",
            new_x="LMARGIN", new_y="NEXT",
        )

        output = pdf.output()
        return bytes(output)
    except PdfGenerationError:
        raise
    except Exception as exc:
        raise PdfGenerationError(f"Failed to render prescription PDF: {exc}") from exc

async def generate_prescription_pdf(
    session: AsyncSession,
    prescription_id: uuid.UUID,
    *,
    clinic_name: str = DEFAULT_CLINIC_NAME,
    clinic_logo_path: Optional[str] = None,
    renderer: Callable[[PrescriptionDocument], bytes] = render_pdf,
) -> bytes:
    """Generate and return the PDF bytes for a stored prescription (Req 11.1–11.4).

    On success, sets ``pdf_status = generated`` and returns the PDF bytes. On
    failure, sets ``pdf_status = failed``, retains the stored prescription
    record (Property 39), and raises :class:`PdfGenerationError`. The ``renderer``
    is injectable so tests can simulate a rendering failure.
    """
    prescription = await get_prescription_with_medications(session, prescription_id)
    document = await build_document(
        session,
        prescription_id,
        clinic_name=clinic_name,
        clinic_logo_path=clinic_logo_path,
    )
    try:
        pdf_bytes = renderer(document)
    except Exception as exc:
        prescription.pdf_status = PdfStatus.FAILED
        await session.flush()
        raise PdfGenerationError(str(exc)) from exc

    prescription.pdf_status = PdfStatus.GENERATED
    await session.flush()
    return pdf_bytes
