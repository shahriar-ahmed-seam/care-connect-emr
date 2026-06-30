"""initial schema

Creates the full Care-Connect-EMR schema: users, doctor_profiles,
availability_slots, appointments, medical_history, vitals, diagnoses,
prescriptions, medications, email_deliveries, notifications, audit_logs, and
auth_attempts — with the citext extension, native ENUM types, foreign keys,
indexes for common lookups, the case-insensitive UNIQUE email constraint
(Req 1.2/1.4), and the availability_slots ``start_time < end_time`` CHECK
(Req 5.3).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = postgresql.ENUM(
    "patient", "doctor", "admin", name="user_role", create_type=False
)
user_status = postgresql.ENUM(
    "active", "pending", "rejected", "inactive", name="user_status", create_type=False
)
language_pref = postgresql.ENUM("bn", "en", name="language_pref", create_type=False)
slot_status = postgresql.ENUM(
    "available", "booked", name="slot_status", create_type=False
)
appointment_status = postgresql.ENUM(
    "scheduled", "cancelled", "completed", name="appointment_status", create_type=False
)
pdf_status = postgresql.ENUM(
    "pending", "generated", "failed", name="pdf_status", create_type=False
)
email_delivery_status = postgresql.ENUM(
    "pending", "sent", "failed", name="email_delivery_status", create_type=False
)
notification_status = postgresql.ENUM(
    "unread", "read", name="notification_status", create_type=False
)

_ALL_ENUMS = [
    user_role,
    user_status,
    language_pref,
    slot_status,
    appointment_status,
    pdf_status,
    email_delivery_status,
    notification_status,
]

def upgrade() -> None:
    bind = op.get_bind()

    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column("language_pref", language_pref, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "doctor_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialty", sa.Text(), nullable=False),
        sa.Column("qualifications", sa.Text(), nullable=True),
        sa.Column("consultation_fee_bdt", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_doctor_profiles_user_id", "doctor_profiles", ["user_id"], unique=True
    )

    op.create_table(
        "availability_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("status", slot_status, nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "start_time < end_time", name="ck_availability_slot_start_before_end"
        ),
    )
    op.create_index(
        "ix_availability_slots_doctor_id", "availability_slots", ["doctor_id"]
    )

    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", appointment_status, nullable=False),
        sa.Column("fee_bdt_at_booking", sa.Numeric(10, 2), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doctor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["slot_id"], ["availability_slots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    op.create_index("ix_appointments_doctor_id", "appointments", ["doctor_id"])
    op.create_index(
        "ix_appointments_slot_id", "appointments", ["slot_id"], unique=True
    )

    op.create_table(
        "medical_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description_enc", sa.LargeBinary(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_medical_history_patient_id", "medical_history", ["patient_id"]
    )

    op.create_table(
        "vitals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blood_pressure_enc", sa.LargeBinary(), nullable=True),
        sa.Column("heart_rate_enc", sa.LargeBinary(), nullable=True),
        sa.Column("temperature_enc", sa.LargeBinary(), nullable=True),
        sa.Column("weight_enc", sa.LargeBinary(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vitals_patient_id", "vitals", ["patient_id"])
    op.create_index("ix_vitals_appointment_id", "vitals", ["appointment_id"])

    op.create_table(
        "diagnoses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text_enc", sa.LargeBinary(), nullable=False),
        sa.Column("recorded_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_diagnoses_patient_id", "diagnoses", ["patient_id"])
    op.create_index("ix_diagnoses_appointment_id", "diagnoses", ["appointment_id"])

    op.create_table(
        "prescriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_name", sa.Text(), nullable=False),
        sa.Column("patient_name", sa.Text(), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("pdf_status", pdf_status, nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doctor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id"])
    op.create_index("ix_prescriptions_doctor_id", "prescriptions", ["doctor_id"])
    op.create_index(
        "ix_prescriptions_appointment_id",
        "prescriptions",
        ["appointment_id"],
        unique=True,
    )

    op.create_table(
        "medications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("dosage", sa.Text(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("duration", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_medications_prescription_id", "medications", ["prescription_id"]
    )

    op.create_table(
        "email_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prescription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", email_delivery_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_deliveries_prescription_id",
        "email_deliveries",
        ["prescription_id"],
        unique=True,
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("status", notification_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index(
        "ix_audit_logs_patient_created", "audit_logs", ["patient_id", "created_at"]
    )

    op.create_table(
        "auth_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_attempts_email", "auth_attempts", ["email"])
    op.create_index(
        "ix_auth_attempts_email_attempted",
        "auth_attempts",
        ["email", "attempted_at"],
    )

def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_auth_attempts_email_attempted", table_name="auth_attempts")
    op.drop_index("ix_auth_attempts_email", table_name="auth_attempts")
    op.drop_table("auth_attempts")

    op.drop_index("ix_audit_logs_patient_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(
        "ix_email_deliveries_prescription_id", table_name="email_deliveries"
    )
    op.drop_table("email_deliveries")

    op.drop_index("ix_medications_prescription_id", table_name="medications")
    op.drop_table("medications")

    op.drop_index("ix_prescriptions_appointment_id", table_name="prescriptions")
    op.drop_index("ix_prescriptions_doctor_id", table_name="prescriptions")
    op.drop_index("ix_prescriptions_patient_id", table_name="prescriptions")
    op.drop_table("prescriptions")

    op.drop_index("ix_diagnoses_appointment_id", table_name="diagnoses")
    op.drop_index("ix_diagnoses_patient_id", table_name="diagnoses")
    op.drop_table("diagnoses")

    op.drop_index("ix_vitals_appointment_id", table_name="vitals")
    op.drop_index("ix_vitals_patient_id", table_name="vitals")
    op.drop_table("vitals")

    op.drop_index("ix_medical_history_patient_id", table_name="medical_history")
    op.drop_table("medical_history")

    op.drop_index("ix_appointments_slot_id", table_name="appointments")
    op.drop_index("ix_appointments_doctor_id", table_name="appointments")
    op.drop_index("ix_appointments_patient_id", table_name="appointments")
    op.drop_table("appointments")

    op.drop_index(
        "ix_availability_slots_doctor_id", table_name="availability_slots"
    )
    op.drop_table("availability_slots")

    op.drop_index("ix_doctor_profiles_user_id", table_name="doctor_profiles")
    op.drop_table("doctor_profiles")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
