"""Integration test for the signaling handshake (task 10.7).

Two WebSocket clients (a Doctor and a Patient) connect to
``WS /api/v1/ws/consultations/{appointment_id}`` and exchange a full
offer/answer/ICE handshake through the Signaling_Server. The test asserts that:

- control messages (``offer``/``answer``/``ice-candidate``) are relayed to the
  *other* participant (Req 8.3), and
- a media payload sent through the signaling channel is **never** relayed — it
  is dropped, so no audio/video traverses the server (Req 8.4).

The whole scenario — DB setup, the ASGI application, and both WebSocket clients
— runs on a single event loop (the module-scoped ``pg_loop``). This is
deliberate: the consultation relay forwards a message received on one
connection to the *other* connection's send channel, so both connections and
the app must share one loop. A tiny in-loop ASGI WebSocket client harness
(:class:`_ASGIWebSocketClient`) drives the app directly via the ASGI protocol,
which is simpler and more faithful than a threaded test client for a
two-party relay.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date as date_, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.appointment import Appointment, AvailabilitySlot
from app.models.enums import AppointmentStatus, SlotStatus, UserRole, UserStatus
from app.services import auth_service, profile_service

_DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
_db_required = pytest.mark.skipif(
    not _DB_URL, reason="No TEST_DATABASE_URL/DATABASE_URL configured"
)

_UTC = timezone.utc
_PASSWORD = "password123"

class _ClientClosed(Exception):
    """Raised when the server closes the WebSocket from the client's view."""

_ACTIVE_TASKS: list = []

class _ASGIWebSocketClient:
    """Minimal in-loop ASGI WebSocket client.

    Drives a FastAPI/Starlette app over the raw ASGI WebSocket protocol on the
    *current* event loop, exchanging messages through two queues. Because it
    shares the app's loop, server-to-server relay (one connection forwarding to
    the other) works correctly — unlike a threaded test client that isolates
    each connection on its own loop.
    """

    def __init__(self, app, path: str, *, query: str = "") -> None:
        self._app = app
        self._scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query.encode("ascii"),
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        import asyncio

        self._to_app: "asyncio.Queue" = asyncio.Queue()
        self._from_app: "asyncio.Queue" = asyncio.Queue()
        self._task = None

    async def _receive(self):
        return await self._to_app.get()

    async def _send(self, message) -> None:
        await self._from_app.put(message)

    async def connect(self):
        import asyncio

        await self._to_app.put({"type": "websocket.connect"})
        self._task = asyncio.ensure_future(
            self._app(self._scope, self._receive, self._send)
        )
        _ACTIVE_TASKS.append((self._scope["query_string"], self._task))
        message = await self._from_app.get()
        if message["type"] != "websocket.accept":
            raise AssertionError(f"expected accept, got {message!r}")
        return self

    async def send_json(self, data) -> None:
        await self._to_app.put(
            {"type": "websocket.receive", "text": json.dumps(data)}
        )

    async def receive_json(self):
        import asyncio

        try:
            message = await asyncio.wait_for(self._from_app.get(), timeout=20)
        except asyncio.TimeoutError:

            for label, task in list(_ACTIVE_TASKS):
                if task.done() and task.exception() is not None:
                    raise AssertionError(
                        f"signaling app task {label} failed"
                    ) from task.exception()
            raise AssertionError(
                "timed out waiting for a relayed message (no server error)"
            )
        if message["type"] == "websocket.close":
            raise _ClientClosed(message.get("code"))
        text = message.get("text")
        if text is None and message.get("bytes") is not None:
            text = message["bytes"].decode("utf-8")
        return json.loads(text)

    async def close(self) -> None:
        await self._to_app.put(
            {"type": "websocket.disconnect", "code": 1000}
        )
        if self._task is not None:
            try:
                await self._task
            except Exception:
                pass

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
def test_signaling_handshake_no_media_traverses_server(
    pg_loop, pg_sessionmaker, monkeypatch
) -> None:
    from sqlalchemy import delete

    from app.api import signaling as signaling_module
    from app.core.security import create_access_token
    from app.main import app
    from app.models.user import DoctorProfile, User

    monkeypatch.setattr(
        signaling_module, "get_sessionmaker", lambda: pg_sessionmaker
    )
    _ACTIVE_TASKS.clear()

    state: dict = {}

    async def scenario() -> None:

        async with pg_sessionmaker() as session:
            doctor = await _make_active_doctor(session)
            patient = await _make_patient(session)
            now = datetime.now(_UTC)
            slot = AvailabilitySlot(
                doctor_id=doctor.id,
                date=date_(now.year, now.month, now.day),
                start_time=time(0, 0),
                end_time=time(23, 59),
                status=SlotStatus.BOOKED,
            )
            session.add(slot)
            await session.flush()
            appointment = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                slot_id=slot.id,
                status=AppointmentStatus.SCHEDULED,
                fee_bdt_at_booking=Decimal("500.00"),
                start_time=now,
                end_time=now + timedelta(minutes=30),
            )
            session.add(appointment)
            await session.flush()
            state.update(
                doctor_id=doctor.id,
                patient_id=patient.id,
                appointment_id=appointment.id,
                slot_id=slot.id,
            )
            await session.commit()

        doctor_token = create_access_token(
            subject=str(state["doctor_id"]), role="doctor"
        ).token
        patient_token = create_access_token(
            subject=str(state["patient_id"]), role="patient"
        ).token
        path = f"/api/v1/ws/consultations/{state['appointment_id']}"

        doc_ws = _ASGIWebSocketClient(app, path, query=f"token={doctor_token}")
        pat_ws = _ASGIWebSocketClient(app, path, query=f"token={patient_token}")
        await doc_ws.connect()
        await pat_ws.connect()
        try:

            await pat_ws.send_json({"type": "offer", "sdp": "OFFER_SDP"})
            received = await doc_ws.receive_json()
            assert received["type"] == "offer"
            assert received["sdp"] == "OFFER_SDP"

            await doc_ws.send_json({"type": "answer", "sdp": "ANSWER_SDP"})
            received = await pat_ws.receive_json()
            assert received["type"] == "answer"
            assert received["sdp"] == "ANSWER_SDP"

            await pat_ws.send_json(
                {"type": "ice-candidate", "candidate": "CAND_FROM_PATIENT"}
            )
            received = await doc_ws.receive_json()
            assert received["type"] == "ice-candidate"
            assert received["candidate"] == "CAND_FROM_PATIENT"

            await doc_ws.send_json(
                {"type": "ice-candidate", "candidate": "CAND_FROM_DOCTOR"}
            )
            received = await pat_ws.receive_json()
            assert received["type"] == "ice-candidate"
            assert received["candidate"] == "CAND_FROM_DOCTOR"

            await pat_ws.send_json(
                {"type": "media", "data": "FAKE_VIDEO_FRAME_BYTES"}
            )
            await pat_ws.send_json({"type": "offer", "sdp": "OFFER_SDP_2"})
            nxt = await doc_ws.receive_json()
            assert nxt["type"] == "offer"
            assert nxt["sdp"] == "OFFER_SDP_2"
            assert nxt.get("data") != "FAKE_VIDEO_FRAME_BYTES"
        finally:
            await doc_ws.close()
            await pat_ws.close()

        async with pg_sessionmaker() as session:
            await session.execute(
                delete(Appointment).where(
                    Appointment.id == state["appointment_id"]
                )
            )
            await session.execute(
                delete(AvailabilitySlot).where(
                    AvailabilitySlot.id == state["slot_id"]
                )
            )
            await session.execute(
                delete(DoctorProfile).where(
                    DoctorProfile.user_id == state["doctor_id"]
                )
            )
            await session.execute(
                delete(User).where(
                    User.id.in_([state["doctor_id"], state["patient_id"]])
                )
            )
            await session.commit()

    try:
        pg_loop.run_until_complete(scenario())
    finally:
        monkeypatch.undo()
