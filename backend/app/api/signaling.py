"""WebSocket signaling route: ``WS /ws/consultations/{appointment_id}``.

Implements the Signaling_Server channel (Requirements 8.1–8.8). On connect the
endpoint:

1. Authenticates the JWT (passed as a ``token`` query parameter, since browser
   ``WebSocket`` clients cannot set an ``Authorization`` header) and resolves
   the user via the Auth_Service.
2. Verifies the user is a **participant** of the Appointment — the Doctor or the
   Patient — and holds the consultation permission; a non-participant is denied
   with an authorization error and no signaling messages are ever relayed for
   them (Req 8.2).
3. Verifies the current time is within the **join window** (10 minutes before
   start through the end time); an attempt outside the window — notably a
   rejoin after the end time — is denied (Req 8.1, 8.7, 8.8).

Once admitted, the socket is registered in the in-memory room keyed by
``appointment_id``. The relay loop forwards only ``offer``/``answer``/
``ice-candidate`` messages to the *other* participant (Req 8.3) and never relays
media or any other type (Req 8.4). An ``end`` message closes the room for both
participants (Req 8.5); when sent by the Doctor for a scheduled Appointment it
also transitions the Appointment to ``completed`` (Req 8.6). A transient
disconnect simply removes the socket from the room so the participant may rejoin
before the end time (Req 8.7).

Media (audio/video) is exchanged peer-to-peer directly between the browsers and
never reaches this server.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.models.appointment import Appointment
from app.models.enums import AppointmentStatus
from app.services import auth_service, signaling_service
from app.services.rbac_service import Permission, role_has_permission

router = APIRouter(tags=["signaling"])

WS_CLOSE_AUTH_REQUIRED = 4401
WS_CLOSE_FORBIDDEN = 4403
WS_CLOSE_WINDOW_CLOSED = 4408
WS_CLOSE_ENDED = 4000

END_MESSAGE_TYPE = "end"

class _Denied(Exception):
    """Internal signal that the join was denied, carrying the close details."""

    def __init__(self, code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.error_code = error_code
        self.message = message

@router.websocket("/ws/consultations/{appointment_id}")
async def consultation_signaling(
    websocket: WebSocket, appointment_id: uuid.UUID
) -> None:
    """Join a consultation and relay WebRTC signaling (Req 8.1–8.8)."""
    token = websocket.query_params.get("token")
    manager = signaling_service.get_room_manager()

    await websocket.accept()

    session_factory = get_sessionmaker()
    try:
        async with session_factory() as session:
            if not token:
                raise _Denied(
                    WS_CLOSE_AUTH_REQUIRED,
                    "authentication-required",
                    "Authentication is required to join the consultation.",
                )
            try:
                user = await auth_service.resolve_current_user(session, token)
            except AppError as exc:
                raise _Denied(
                    WS_CLOSE_AUTH_REQUIRED, exc.code, exc.message
                ) from exc

            appointment = await session.get(Appointment, appointment_id)
            role = (
                signaling_service.participant_role(
                    doctor_id=appointment.doctor_id,
                    patient_id=appointment.patient_id,
                    user_id=user.id,
                )
                if appointment is not None
                else None
            )

            if appointment is None or role is None or not role_has_permission(
                user.role, Permission.CONDUCT_CONSULTATION
            ):
                raise _Denied(
                    WS_CLOSE_FORBIDDEN,
                    "authorization-error",
                    "You are not a participant of this consultation.",
                )

            if appointment.status != AppointmentStatus.SCHEDULED:
                raise _Denied(
                    WS_CLOSE_WINDOW_CLOSED,
                    "consultation-window-closed",
                    "The consultation has ended.",
                )

            if not signaling_service.within_join_window(
                start_time=appointment.start_time,
                end_time=appointment.end_time,
            ):
                raise _Denied(
                    WS_CLOSE_WINDOW_CLOSED,
                    "consultation-window-closed",
                    "The consultation has ended.",
                )

            user_id = user.id
    except _Denied as denied:
        await _close_with_error(
            websocket, denied.code, denied.error_code, denied.message
        )
        return

    manager.join(appointment_id, user_id, websocket)
    try:
        await _relay_loop(websocket, manager, appointment_id, user_id, role)
    except WebSocketDisconnect:

        manager.leave(appointment_id, user_id)

async def _relay_loop(
    websocket: WebSocket,
    manager: "signaling_service.RoomManager",
    appointment_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> None:
    """Receive messages from one participant and relay control messages only."""
    while True:
        message = await websocket.receive_json()
        message_type = (
            message.get("type") if isinstance(message, dict) else None
        )

        if message_type == END_MESSAGE_TYPE:
            await _handle_end(manager, appointment_id, user_id)
            return

        room = manager.get(appointment_id)
        if room is None:
            return

        await signaling_service.relay_message(
            room, sender_id=user_id, message=message
        )

async def _handle_end(
    manager: "signaling_service.RoomManager",
    appointment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Close the room for both participants and complete a doctor-ended appt."""

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        appointment = await session.get(Appointment, appointment_id)
        if appointment is not None:
            await signaling_service.end_consultation(
                session, appointment=appointment, ending_user_id=user_id
            )
            await session.commit()

    room = manager.get(appointment_id)
    if room is not None:
        peer = room.peer(user_id)
        if peer is not None:
            try:
                await peer.send_json({"type": "ended"})
            except Exception:
                pass
    await signaling_service.close_room(manager, appointment_id)

async def _close_with_error(
    websocket: WebSocket, code: int, error_code: str, message: str
) -> None:
    """Send a structured error envelope then close the socket (Req 8.2)."""
    try:
        await websocket.send_json(
            {"type": "error", "error": {"code": error_code, "message": message}}
        )
    except Exception:
        pass
    try:
        await websocket.close(code=code)
    except Exception:
        pass
