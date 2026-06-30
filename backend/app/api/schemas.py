"""Pydantic request/response models for the Auth_Service endpoints.

These models enforce input validation at the API boundary:

- ``RegisterRequest`` validates the email format as ``local@domain.tld``
  (Req 1.4) and a minimum password length of 8 characters (Req 1.3). Pydantic
  raises a validation error identifying the offending field, which the global
  handler maps into the error envelope (Property 3).
- The remaining models shape login, logout, and password-reset payloads and
  responses.
"""

from __future__ import annotations

import re
import uuid
from datetime import date as date_, time
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

RegisterRole = Literal["patient", "doctor"]

MIN_PASSWORD_LENGTH = 8

class RegisterRequest(BaseModel):
    """Registration payload (Req 1.1, 1.3, 1.4, 1.5)."""

    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    full_name: str = Field(min_length=1)
    role: RegisterRole

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, value: str) -> str:
        if not EMAIL_PATTERN.match(value):
            raise ValueError("The email address is invalid.")
        return value.strip()

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A full name is required.")
        return value.strip()

class UserResponse(BaseModel):
    """Public view of a user account."""

    id: str
    email: str
    full_name: str
    role: str
    status: str

class RegisterResponse(BaseModel):
    """Result of a successful registration."""

    user: UserResponse

class LoginRequest(BaseModel):
    """Login payload (Req 2.1, 2.2)."""

    email: str
    password: str

class LoginResponse(BaseModel):
    """Result of a successful login: a bearer token and the user."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: str
    user: UserResponse

class PasswordResetRequest(BaseModel):
    """Request a time-limited reset link (Req 2.8)."""

    email: str

class PasswordResetConfirm(BaseModel):
    """Confirm a password reset with a token and new password (Req 2.8)."""

    token: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)

class MessageResponse(BaseModel):
    """A generic acknowledgement message."""

    message: str
    detail: Optional[str] = None

class SubmittedCredentials(BaseModel):
    """A pending applicant's submitted professional credentials (Req 4.1)."""

    specialty: str
    qualifications: Optional[str] = None
    consultation_fee_bdt: str

class PendingAccountResponse(BaseModel):
    """A pending account shown in the Admin approvals list (Req 4.1, 16.4)."""

    id: str
    full_name: str
    email: str
    role: str
    status: str
    submitted_credentials: Optional[SubmittedCredentials] = None

class PendingAccountsResponse(BaseModel):
    """The full set of pending accounts (Property 15)."""

    accounts: List[PendingAccountResponse]

class DoctorProfileRequest(BaseModel):
    """Save-profile payload: specialty, qualifications, fee in BDT (Req 5.1)."""

    specialty: str = Field(min_length=1)
    qualifications: Optional[str] = None
    consultation_fee_bdt: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

    @field_validator("specialty")
    @classmethod
    def _validate_specialty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A specialty is required.")
        return value.strip()

class DoctorProfileResponse(BaseModel):
    """Public view of a Doctor's profile."""

    specialty: str
    qualifications: Optional[str] = None
    consultation_fee_bdt: str

class SlotCreateRequest(BaseModel):
    """Create-slot payload: a date with start and end times (Req 5.2)."""

    date: date_
    start_time: time
    end_time: time

class SlotResponse(BaseModel):
    """Public view of an availability slot."""

    id: str
    date: str
    start_time: str
    end_time: str
    status: str

class DoctorSearchResult(BaseModel):
    """A single active Doctor returned from a specialty search (Req 6.1)."""

    id: str
    full_name: str
    specialty: str
    qualifications: Optional[str] = None
    consultation_fee_bdt: str

class DoctorSearchResponse(BaseModel):
    """The set of active Doctors matching a specialty search (Property 23)."""

    doctors: List[DoctorSearchResult]

class SlotsResponse(BaseModel):
    """A list of bookable availability slots (Req 6.2)."""

    slots: List[SlotResponse]

class BookAppointmentRequest(BaseModel):
    """Book-appointment payload: the slot the Patient wishes to claim (Req 6.3)."""

    slot_id: uuid.UUID

class RescheduleAppointmentRequest(BaseModel):
    """Reschedule payload: the new slot of the same Doctor (Req 7.3)."""

    slot_id: uuid.UUID

class AppointmentResponse(BaseModel):
    """Public view of an appointment."""

    id: str
    patient_id: str
    doctor_id: str
    slot_id: str
    status: str
    fee_bdt_at_booking: str
    start_time: str
    end_time: str

VITALS_MIN = 0.0
VITALS_MAX = 1000.0

class VitalsRequest(BaseModel):
    """Record-vitals payload: numeric measurements within 0–1000 (Req 9.1, 9.5)."""

    appointment_id: uuid.UUID
    blood_pressure: Optional[float] = Field(default=None, ge=VITALS_MIN, le=VITALS_MAX)
    heart_rate: Optional[float] = Field(default=None, ge=VITALS_MIN, le=VITALS_MAX)
    temperature: Optional[float] = Field(default=None, ge=VITALS_MIN, le=VITALS_MAX)
    weight: Optional[float] = Field(default=None, ge=VITALS_MIN, le=VITALS_MAX)

class VitalsResponse(BaseModel):
    """Public view of a stored vitals record."""

    id: str
    patient_id: str
    appointment_id: str
    blood_pressure: Optional[float] = None
    heart_rate: Optional[float] = None
    temperature: Optional[float] = None
    weight: Optional[float] = None
    recorded_at: str

class MedicalHistoryRequest(BaseModel):
    """Add-medical-history payload: a description and an entry date (Req 9.2)."""

    description: str = Field(min_length=1)
    entry_date: date_

class MedicalHistoryResponse(BaseModel):
    """Public view of a medical-history entry."""

    id: str
    patient_id: str
    description: str
    entry_date: str
    created_at: str

class DiagnosisRequest(BaseModel):
    """Record-diagnosis payload: free text and a recording date (Req 10.1)."""

    text: str = Field(min_length=1)
    recorded_date: date_

class DiagnosisResponse(BaseModel):
    """Public view of a diagnosis."""

    id: str
    patient_id: str
    appointment_id: str
    text: str
    recorded_date: str

class MedicationResponse(BaseModel):
    """Public view of a prescription medication line item."""

    id: str
    name: str
    dosage: str
    frequency: str
    duration: str

class MedicationRequest(BaseModel):
    """A medication line item supplied when creating a prescription (Req 10.4).

    All four fields are required and non-empty; the Prescription_Service
    re-validates so an invalid prescription is never stored (Property 36).
    """

    name: str = Field(min_length=1)
    dosage: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    duration: str = Field(min_length=1)

class PrescriptionCreateRequest(BaseModel):
    """Create-prescription payload: at least one medication entry (Req 10.2, 10.3)."""

    medications: List[MedicationRequest] = Field(min_length=1)

class PrescriptionResponse(BaseModel):
    """Public view of a prescription within a patient record."""

    id: str
    patient_id: str
    doctor_id: str
    appointment_id: str
    doctor_name: str
    patient_name: str
    issued_at: str
    pdf_status: str
    medications: List[MedicationResponse]

class PatientRecordResponse(BaseModel):
    """A Patient's full clinical record in reverse chronological order (Req 9.3, 9.4)."""

    medical_history: List[MedicalHistoryResponse]
    vitals: List[VitalsResponse]
    diagnoses: List[DiagnosisResponse]
    prescriptions: List[PrescriptionResponse]

class NotificationResponse(BaseModel):
    """A single in-app notification entry."""

    id: str
    type: str
    payload: Optional[dict] = None
    status: str
    created_at: str

class NotificationsResponse(BaseModel):
    """A user's in-app notification feed, newest first."""

    notifications: List[NotificationResponse]

class AppointmentSummary(BaseModel):
    """A compact appointment row for dashboards, with a join-control flag."""

    id: str
    doctor_id: str
    patient_id: str
    doctor_name: str
    patient_name: str
    start_time: str
    end_time: str
    status: str
    can_join: bool

class PatientDashboardResponse(BaseModel):
    """Patient dashboard payload (Req 14.1–14.4)."""

    upcoming_appointments: List[AppointmentSummary]
    recent_prescriptions: List[PrescriptionResponse]
    vitals: List[VitalsResponse]

class DoctorDashboardResponse(BaseModel):
    """Doctor dashboard payload (Req 15.1, 15.2, 15.4)."""

    today_appointments: List[AppointmentSummary]
    pending_today: int

class AdminDashboardResponse(BaseModel):
    """Admin dashboard counts (Req 16.1)."""

    total_patients: int
    active_doctors: int
    appointments_today: int

class AdminUsersResponse(BaseModel):
    """The full Admin user list (Req 16.2)."""

    users: List[UserResponse]
