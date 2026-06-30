"""Property tests for the Video_Service & Signaling_Server (tasks 10.3–10.6).

- Property 29: Join is allowed exactly within the consultation window
  (Req 8.1, 8.7, 8.8) — pure logic, sampling times around start-10min and end.
- Property 30: Non-participants are denied and never relayed (Req 8.2) — pure
  logic plus a room-relay check that an outsider never receives a message.
- Property 31: Signaling relays only control messages to the peer
  (Req 8.3, 8.4) — pure relay logic over control and non-control message types.
- Property 32: Ending a consultation closes the session and completes
  doctor-ended appointments (Req 8.5, 8.6) — DB-backed status transition plus
  an in-memory room-closure check.

Properties 29–31 are pure and run without a database. Property 32 exercises the
real Appointment status transition against PostgreSQL via the module-scoped
``pg_sessionmaker``/``pg_loop`` fixtures with per-example rollback.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.models.appointment import Appointment, AvailabilitySlot
from app.models.enums import AppointmentStatus, SlotStatus, UserRole, UserStatus
from app.services import auth_service, profile_service, signaling_service
from app.services.signaling_service import (
    CONTROL_MESSAGE_TYPES,
    RoomManager,
    close_room,
    end_consultation,
    is_participant,
    participant_role,
    relay_message,
    status_after_end,
    within_join_window,
)

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_UTC = timezone.utc
_PASSWORD = "password123"

class _FakeConn:
    """A stand-in for a participant's WebSocket connection.

    Records every message it is sent and whether it was closed, so relay and
    room-closure behaviour can be asserted without a real socket.
    """

    def __init__(self) -> None:
        self.received: list = []
        self.closed = False

    async def send_json(self, message) -> None:
        self.received.append(message)

    async def close(self) -> None:
        self.closed = True

_NON_CONTROL_TYPES = st.one_of(
    st.sampled_from(["media", "audio", "video", "chat", "end", "ping", ""]),
    st.text(max_size=20).filter(lambda s: s not in CONTROL_MESSAGE_TYPES),
    st.none(),
)
_ANY_MESSAGE_TYPE = st.one_of(
    st.sampled_from(sorted(CONTROL_MESSAGE_TYPES)), _NON_CONTROL_TYPES
)

@given(
    duration_min=st.integers(min_value=1, max_value=240),
    offset_sec=st.integers(min_value=-1200, max_value=18000),
)
def test_join_allowed_exactly_within_window(duration_min, offset_sec) -> None:
    start = datetime(2027, 1, 1, 12, 0, tzinfo=_UTC)
    end = start + timedelta(minutes=duration_min)
    now = start + timedelta(seconds=offset_sec)

    expected = (start - timedelta(minutes=10)) <= now <= end
    assert (
        within_join_window(start_time=start, end_time=end, now=now) == expected
    )

@given(seed=st.integers(min_value=0, max_value=10_000), msg_type=st.sampled_from(sorted(CONTROL_MESSAGE_TYPES)))
def test_non_participants_denied_and_never_relayed(seed, msg_type) -> None:
    doctor_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    outsider_id = uuid.uuid4()

    assert participant_role(
        doctor_id=doctor_id, patient_id=patient_id, user_id=outsider_id
    ) is None
    assert not is_participant(
        doctor_id=doctor_id, patient_id=patient_id, user_id=outsider_id
    )

    assert participant_role(
        doctor_id=doctor_id, patient_id=patient_id, user_id=doctor_id
    ) == "doctor"
    assert participant_role(
        doctor_id=doctor_id, patient_id=patient_id, user_id=patient_id
    ) == "patient"

    manager = RoomManager()
    appt_id = uuid.uuid4()
    doctor_conn = _FakeConn()
    patient_conn = _FakeConn()
    outsider_conn = _FakeConn()
    room = manager.join(appt_id, doctor_id, doctor_conn)
    manager.join(appt_id, patient_id, patient_conn)

    message = {"type": msg_type, "payload": seed}
    relayed = asyncio.run(
        relay_message(room, sender_id=doctor_id, message=message)
    )
    assert relayed is True
    assert patient_conn.received == [message]
    assert outsider_conn.received == []

@given(msg_type=_ANY_MESSAGE_TYPE, payload=st.integers())
def test_signaling_relays_only_control_messages(msg_type, payload) -> None:
    manager = RoomManager()
    appt_id = uuid.uuid4()
    sender_id = uuid.uuid4()
    peer_id = uuid.uuid4()
    sender_conn = _FakeConn()
    peer_conn = _FakeConn()
    room = manager.join(appt_id, sender_id, sender_conn)
    manager.join(appt_id, peer_id, peer_conn)

    message = {"type": msg_type, "payload": payload}
    relayed = asyncio.run(
        relay_message(room, sender_id=sender_id, message=message)
    )

    should_relay = msg_type in CONTROL_MESSAGE_TYPES
    assert relayed is should_relay

    assert peer_conn.received == ([message] if should_relay else [])

    assert sender_conn.received == []

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

@_db_required
@given(
    initial_status=st.sampled_from(list(AppointmentStatus)),
    ender=st.sampled_from(["doctor", "patient"]),
)
def test_ending_closes_session_and_completes_doctor_ended(
    pg_loop, pg_sessionmaker, initial_status, ender
) -> None:
    async def scenario() -> None:
        async with pg_sessionmaker() as session:
            try:
                doctor = await _make_active_doctor(session)
                patient = await _make_patient(session)
                start = datetime(2027, 1, 1, 12, 0, tzinfo=_UTC)
                slot = AvailabilitySlot(
                    doctor_id=doctor.id,
                    date=date_(2027, 1, 1),
                    start_time=time(12, 0),
                    end_time=time(12, 30),
                    status=SlotStatus.BOOKED,
                )
                session.add(slot)
                await session.flush()
                appointment = Appointment(
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    slot_id=slot.id,
                    status=initial_status,
                    fee_bdt_at_booking=Decimal("500.00"),
                    start_time=start,
                    end_time=start + timedelta(minutes=30),
                )
                session.add(appointment)
                await session.flush()

                ending_user_id = (
                    doctor.id if ender == "doctor" else patient.id
                )
                ending_role = ender

                expected_status = status_after_end(
                    ending_role=ending_role, current_status=initial_status
                )
                result_status = await end_consultation(
                    session,
                    appointment=appointment,
                    ending_user_id=ending_user_id,
                )
                assert result_status == expected_status
                await session.refresh(appointment)
                assert appointment.status == expected_status

                if ender == "doctor" and initial_status == AppointmentStatus.SCHEDULED:
                    assert appointment.status == AppointmentStatus.COMPLETED
                else:
                    assert appointment.status == initial_status

                manager = RoomManager()
                doctor_conn = _FakeConn()
                patient_conn = _FakeConn()
                manager.join(appointment.id, doctor.id, doctor_conn)
                manager.join(appointment.id, patient.id, patient_conn)
                closed = await close_room(manager, appointment.id)
                assert set(closed) == {doctor.id, patient.id}
                assert doctor_conn.closed and patient_conn.closed
                assert manager.get(appointment.id) is None
            finally:
                await session.rollback()

    pg_loop.run_until_complete(scenario())
