"""RBAC_Service: permission matrix, row-level scoping, and access auditing.

This module implements the authorization domain logic that sits between an
authenticated request and the patient-data it touches. It is framework-light:
the pure permission matrix and the async scoping/audit helpers take plain
arguments (and, where needed, an ``AsyncSession``) so they can be exercised
directly by property-based tests as well as wired into FastAPI dependencies.

Covered behaviour:

- **Permission matrix** (Req 3.1): a static mapping from :class:`UserRole` to the
  set of :class:`Permission` values that role is granted. ``role_has_permission``
  returns ``True`` *iff* the matrix grants the permission to the role
  (Property 11). The matrix is the single source of truth for the
  ``require(permission)`` dependency in :mod:`app.api.deps`.

- **Row-level data scoping** (Req 3.2–3.5):
  - Patients may access only their own data (Property 12).
  - Doctors may access a patient's records *iff* they have a scheduled or
    completed appointment with that patient (Property 13).
  - Admins manage accounts/schedules but are denied the clinical free-text
    content of consultation notes/diagnoses (Property 14).

- **Patient-data access auditing** (Req 13.5): ``record_patient_data_access``
  writes an :class:`~app.models.audit.AuditLog` entry (actor id, patient id,
  action, timestamp) at the patient-data service boundary (Property 44).

The design treats authorization as *fail-closed*: any role/relationship the
matrix or scoping rules do not explicitly grant is denied with an
``authorization-error`` (HTTP 403).
"""

from __future__ import annotations

import enum
import uuid
from typing import Optional

from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.appointment import Appointment
from app.models.audit import AuditLog
from app.models.enums import AppointmentStatus, UserRole
from app.models.user import User

class Permission(str, enum.Enum):
    """A discrete capability that a role may or may not be granted (Req 3.1)."""

    VIEW_OWN_PROFILE = "view_own_profile"
    EDIT_OWN_PROFILE = "edit_own_profile"

    VIEW_OWN_RECORDS = "view_own_records"
    BOOK_APPOINTMENT = "book_appointment"
    CANCEL_OWN_APPOINTMENT = "cancel_own_appointment"
    RESCHEDULE_OWN_APPOINTMENT = "reschedule_own_appointment"

    MANAGE_OWN_SLOTS = "manage_own_slots"
    MANAGE_DOCTOR_PROFILE = "manage_doctor_profile"
    VIEW_PATIENT_RECORDS = "view_patient_records"
    EDIT_PATIENT_RECORDS = "edit_patient_records"
    RECORD_DIAGNOSIS = "record_diagnosis"
    CREATE_PRESCRIPTION = "create_prescription"

    CONDUCT_CONSULTATION = "conduct_consultation"

    VIEW_CONSULTATION_FREETEXT = "view_consultation_freetext"

    MANAGE_USERS = "manage_users"
    MANAGE_SCHEDULES = "manage_schedules"
    APPROVE_DOCTORS = "approve_doctors"
    VIEW_ADMIN_DASHBOARD = "view_admin_dashboard"

PERMISSION_MATRIX: dict[UserRole, frozenset[Permission]] = {
    UserRole.PATIENT: frozenset(
        {
            Permission.VIEW_OWN_PROFILE,
            Permission.EDIT_OWN_PROFILE,
            Permission.VIEW_OWN_RECORDS,
            Permission.BOOK_APPOINTMENT,
            Permission.CANCEL_OWN_APPOINTMENT,
            Permission.RESCHEDULE_OWN_APPOINTMENT,
            Permission.CONDUCT_CONSULTATION,
            Permission.VIEW_CONSULTATION_FREETEXT,
        }
    ),
    UserRole.DOCTOR: frozenset(
        {
            Permission.VIEW_OWN_PROFILE,
            Permission.EDIT_OWN_PROFILE,
            Permission.MANAGE_OWN_SLOTS,
            Permission.MANAGE_DOCTOR_PROFILE,
            Permission.VIEW_PATIENT_RECORDS,
            Permission.EDIT_PATIENT_RECORDS,
            Permission.RECORD_DIAGNOSIS,
            Permission.CREATE_PRESCRIPTION,
            Permission.CONDUCT_CONSULTATION,
            Permission.VIEW_CONSULTATION_FREETEXT,
        }
    ),
    UserRole.ADMIN: frozenset(
        {
            Permission.VIEW_OWN_PROFILE,
            Permission.EDIT_OWN_PROFILE,
            Permission.MANAGE_USERS,
            Permission.MANAGE_SCHEDULES,
            Permission.APPROVE_DOCTORS,
            Permission.VIEW_ADMIN_DASHBOARD,

        }
    ),
}

def role_has_permission(role: UserRole, permission: Permission) -> bool:
    """Return ``True`` iff the matrix grants ``permission`` to ``role`` (Req 3.1).

    This is the exact predicate Property 11 checks: an action is permitted if
    and only if the role's permission set contains the required permission.
    Unknown roles map to the empty set and are denied (fail-closed).
    """
    return permission in PERMISSION_MATRIX.get(role, frozenset())

def _authorization_error(message: str) -> AppError:
    return AppError(
        "authorization-error",
        message,
        status_code=http_status.HTTP_403_FORBIDDEN,
    )

def assert_permission(role: UserRole, permission: Permission) -> None:
    """Raise an ``authorization-error`` if ``role`` lacks ``permission`` (Req 3.1)."""
    if not role_has_permission(role, permission):
        raise _authorization_error(
            "You do not have permission to perform this action."
        )

def patient_owns(user: User, patient_id: uuid.UUID) -> bool:
    """Return ``True`` iff ``user`` is the patient identified by ``patient_id``."""
    return user.role == UserRole.PATIENT and user.id == patient_id

async def doctor_has_patient_relationship(
    session: AsyncSession,
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
) -> bool:
    """Return ``True`` iff a scheduled/completed appointment links them (Req 3.4).

    A Doctor may view/edit a Patient's medical records exactly when there exists
    at least one appointment between the two whose status is ``scheduled`` or
    ``completed``. Cancelled appointments do not establish access. This is the
    iff condition checked by Property 13.
    """
    existing = await session.scalar(
        select(Appointment.id).where(
            Appointment.doctor_id == doctor_id,
            Appointment.patient_id == patient_id,
            Appointment.status.in_(
                (AppointmentStatus.SCHEDULED, AppointmentStatus.COMPLETED)
            ),
        )
    )
    return existing is not None

async def authorize_patient_data_access(
    session: AsyncSession,
    *,
    user: User,
    patient_id: uuid.UUID,
    free_text: bool = False,
) -> None:
    """Enforce row-level scoping for a patient-data access (Req 3.2–3.5).

    Fail-closed authorization for a request by ``user`` to touch the records of
    the patient identified by ``patient_id``:

    - **Patient**: permitted only for their own data; viewing another patient's
      data raises an ``authorization-error`` (Req 3.2, 3.3 — Property 12).
    - **Doctor**: permitted iff a scheduled/completed appointment exists between
      the doctor and the patient (Req 3.4 — Property 13).
    - **Admin**: account/schedule management is permitted, but the clinical
      free-text content of consultation notes/diagnoses is denied; an admin
      request with ``free_text=True`` raises an ``authorization-error``
      (Req 3.5 — Property 14).

    Any other case is denied.
    """
    if user.role == UserRole.PATIENT:
        if user.id != patient_id:
            raise _authorization_error(
                "You may only access your own medical data."
            )
        return

    if user.role == UserRole.DOCTOR:
        if not role_has_permission(user.role, Permission.VIEW_PATIENT_RECORDS):
            raise _authorization_error(
                "You do not have permission to access patient records."
            )
        allowed = await doctor_has_patient_relationship(
            session, doctor_id=user.id, patient_id=patient_id
        )
        if not allowed:
            raise _authorization_error(
                "You may only access records of patients you have an "
                "appointment with."
            )
        return

    if user.role == UserRole.ADMIN:
        if free_text:
            raise _authorization_error(
                "Admins may not access the clinical free-text content of "
                "consultation notes."
            )
        return

    raise _authorization_error("You do not have permission to access this data.")

async def record_patient_data_access(
    session: AsyncSession,
    *,
    actor_user_id: Optional[uuid.UUID],
    patient_id: Optional[uuid.UUID],
    action: str,
) -> AuditLog:
    """Write an audit entry for a patient-data access (Req 13.5 — Property 44).

    Records the accessing user identifier (``actor_user_id``), the affected
    patient identifier (``patient_id``), the ``action`` performed, and the
    timestamp (set by the DB default on ``created_at``). Called at the
    patient-data service boundary so every read/write of patient data is
    audited. The write is flushed but not committed — the caller owns the
    transaction boundary.
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        patient_id=patient_id,
        action=action,
    )
    session.add(entry)
    await session.flush()
    return entry
