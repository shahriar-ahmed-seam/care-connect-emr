"""Video_Service & Signaling_Server domain logic.

The video consultation feature keeps **media peer-to-peer**: the backend only
brokers WebRTC connection-establishment messages (SDP offers/answers and ICE
candidates). Audio and video never traverse the server (Req 8.4).

This module deliberately separates *pure, synchronously-testable decision
logic* from the asynchronous WebSocket I/O so the correctness properties can be
exercised directly:

- :func:`within_join_window` — is the current time inside the join window
  (10 minutes before start through the end time)? (Req 8.1, 8.7, 8.8 —
  Property 29)
- :func:`participant_role` / :func:`is_participant` — does a user identify as a
  participant (Doctor/Patient) of an Appointment? Non-participants are denied
  (Req 8.2 — Property 30).
- :func:`is_control_message` — is a message a relayable connection-establishment
  control message (``offer``/``answer``/``ice-candidate``)? Media and any other
  type is never relayed (Req 8.3, 8.4 — Property 31).
- :func:`status_after_end` — what is the Appointment status after an ``end``
  action? A Doctor ending a *scheduled* Appointment completes it (Req 8.6 —
  Property 32).

The in-memory :class:`RoomManager` keys a :class:`ConsultationRoom` by
``appointment_id`` and tracks the (at most two) connected participants. It is
process-local; a single signaling worker holds the rooms. Relay and room
closure are async because they drive the underlying connection objects, but
they only act on decisions made by the pure helpers above.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.models.appointment import Appointment
from app.models.enums import AppointmentStatus

JOIN_WINDOW_LEAD = timedelta(minutes=10)

CONTROL_MESSAGE_TYPES: frozenset[str] = frozenset(
    {"offer", "answer", "ice-candidate"}
)

ROLE_DOCTOR = "doctor"
ROLE_PATIENT = "patient"

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def within_join_window(
    *, start_time: datetime, end_time: datetime, now: Optional[datetime] = None
) -> bool:
    """Return ``True`` iff ``now`` is inside the consultation join window.

    The window opens :data:`JOIN_WINDOW_LEAD` (10 minutes) before ``start_time``
    and closes at ``end_time`` (inclusive on both ends). A request at any time
    strictly before the window opens or strictly after ``end_time`` is outside
    the window and must be denied (Req 8.1, 8.7, 8.8 — Property 29).
    """
    current = now or _now_utc()
    window_open = start_time - JOIN_WINDOW_LEAD
    return window_open <= current <= end_time

def participant_role(
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[str]:
    """Return ``"doctor"``/``"patient"`` if ``user_id`` is a participant, else ``None``.

    A user who is neither the Doctor nor the Patient of the Appointment is not a
    participant and must be denied entry (Req 8.2 — Property 30).
    """
    if user_id == doctor_id:
        return ROLE_DOCTOR
    if user_id == patient_id:
        return ROLE_PATIENT
    return None

def is_participant(
    *,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Return ``True`` iff ``user_id`` is a participant of the Appointment."""
    return (
        participant_role(
            doctor_id=doctor_id, patient_id=patient_id, user_id=user_id
        )
        is not None
    )

def is_control_message(message_type: Any) -> bool:
    """Return ``True`` iff ``message_type`` is a relayable control message.

    Only ``offer``, ``answer``, and ``ice-candidate`` are connection-establishment
    control messages the server relays; media payloads and any other type are
    not relayed (Req 8.3, 8.4 — Property 31).
    """
    return message_type in CONTROL_MESSAGE_TYPES

def status_after_end(
    *, ending_role: Optional[str], current_status: AppointmentStatus
) -> AppointmentStatus:
    """Return the Appointment status after an ``end`` action (Req 8.6 — Property 32).

    When the **Doctor** ends a consultation for a **scheduled** Appointment, the
    Appointment transitions to ``completed``. In every other case (Patient ends,
    or the Appointment is not currently scheduled) the status is unchanged — the
    session still closes for both participants (Req 8.5), but no completion
    occurs.
    """
    if ending_role == ROLE_DOCTOR and current_status == AppointmentStatus.SCHEDULED:
        return AppointmentStatus.COMPLETED
    return current_status

class ConsultationRoom:
    """An in-memory consultation room keyed by ``appointment_id``.

    Holds at most two connected participants keyed by user id. Re-joining with
    the same user id replaces the prior connection, which supports reconnection
    before the end time (Req 8.7).
    """

    def __init__(self, appointment_id: uuid.UUID) -> None:
        self.appointment_id = appointment_id
        self.connections: Dict[uuid.UUID, Any] = {}

    def add(self, user_id: uuid.UUID, connection: Any) -> None:
        self.connections[user_id] = connection

    def remove(self, user_id: uuid.UUID) -> None:
        self.connections.pop(user_id, None)

    def peer(self, user_id: uuid.UUID) -> Optional[Any]:
        """Return the *other* participant's connection, if present."""
        for uid, conn in self.connections.items():
            if uid != user_id:
                return conn
        return None

    @property
    def is_empty(self) -> bool:
        return not self.connections

class RoomManager:
    """Process-local registry of active :class:`ConsultationRoom` instances."""

    def __init__(self) -> None:
        self._rooms: Dict[uuid.UUID, ConsultationRoom] = {}

    def join(
        self, appointment_id: uuid.UUID, user_id: uuid.UUID, connection: Any
    ) -> ConsultationRoom:
        """Register ``connection`` for ``user_id`` in the room, creating it if needed."""
        room = self._rooms.get(appointment_id)
        if room is None:
            room = ConsultationRoom(appointment_id)
            self._rooms[appointment_id] = room
        room.add(user_id, connection)
        return room

    def get(self, appointment_id: uuid.UUID) -> Optional[ConsultationRoom]:
        return self._rooms.get(appointment_id)

    def leave(self, appointment_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove ``user_id`` from the room; drop the room once empty."""
        room = self._rooms.get(appointment_id)
        if room is None:
            return
        room.remove(user_id)
        if room.is_empty:
            self._rooms.pop(appointment_id, None)

    def drop(self, appointment_id: uuid.UUID) -> None:
        """Forget the room entirely (used when the session is closed)."""
        self._rooms.pop(appointment_id, None)

_room_manager = RoomManager()

def get_room_manager() -> RoomManager:
    """Return the process-wide :class:`RoomManager` singleton."""
    return _room_manager

async def relay_message(
    room: ConsultationRoom, *, sender_id: uuid.UUID, message: Any
) -> bool:
    """Relay ``message`` from ``sender_id`` to the peer iff it is a control message.

    Returns ``True`` when the message was forwarded to the other participant.
    A non-control message (e.g. media or any unknown type) is never forwarded,
    and a control message is dropped silently when no peer is present
    (Req 8.3, 8.4 — Property 31).
    """
    message_type = message.get("type") if isinstance(message, dict) else None
    if not is_control_message(message_type):
        return False
    peer = room.peer(sender_id)
    if peer is None:
        return False
    await peer.send_json(message)
    return True

async def close_room(
    manager: RoomManager, appointment_id: uuid.UUID
) -> List[uuid.UUID]:
    """Close the consultation session for both participants (Req 8.5 — Property 32).

    Closes every connection in the room and drops the room from the registry.
    Returns the list of user ids whose connections were closed. Errors closing
    an individual connection are swallowed so one failure does not leave the
    other participant's connection or the room dangling.
    """
    room = manager.get(appointment_id)
    if room is None:
        return []
    closed = list(room.connections.keys())
    for connection in list(room.connections.values()):
        try:
            await connection.close()
        except Exception:
            pass
    manager.drop(appointment_id)
    return closed

async def end_consultation(
    session,
    *,
    appointment: Appointment,
    ending_user_id: uuid.UUID,
) -> AppointmentStatus:
    """Apply the Appointment status transition for an ``end`` action (Req 8.6).

    Resolves the ending participant's role and, when the Doctor ends a scheduled
    Appointment, transitions it to ``completed`` (Property 32). The write is
    flushed but not committed; the caller owns the transaction boundary. Returns
    the resulting Appointment status.
    """
    role = participant_role(
        doctor_id=appointment.doctor_id,
        patient_id=appointment.patient_id,
        user_id=ending_user_id,
    )
    new_status = status_after_end(
        ending_role=role, current_status=appointment.status
    )
    if new_status != appointment.status:
        appointment.status = new_status
        await session.flush()
    return appointment.status
