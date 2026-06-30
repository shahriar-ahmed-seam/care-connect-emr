"""Minimal mailer abstraction used by the Auth_Service.

The production Email_Service (SMTP delivery, the DB-backed outbox and retry
worker) is built in a later task. For authentication flows that need to send a
message now — notably the time-limited password-reset link (Requirement 2.8) —
this module defines a tiny :class:`Mailer` protocol plus an in-memory
:class:`CapturingMailer` default.

``CapturingMailer`` records sent messages in memory instead of dialling SMTP,
which keeps local/dev runs side-effect free and lets tests assert on what was
sent. Service functions accept an injectable mailer so tests can supply their
own capturing instance; production wiring will substitute a real SMTP-backed
implementation that satisfies the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable

class MailerError(Exception):
    """Raised when an outbound message cannot be delivered."""

@dataclass(frozen=True)
class EmailMessage:
    """A simple outbound email message, optionally carrying one attachment.

    ``attachment_bytes``/``attachment_filename`` support delivering a generated
    prescription PDF as an attachment (Requirement 12.1).
    """

    to: str
    subject: str
    body: str
    attachment_bytes: Optional[bytes] = None
    attachment_filename: Optional[str] = None
    attachment_mime: str = "application/pdf"

@runtime_checkable
class Mailer(Protocol):
    """Anything capable of sending an :class:`EmailMessage`.

    Implementations raise :class:`MailerError` (or any exception) when delivery
    fails; the email outbox treats a raised exception as a failed attempt.
    """

    def send(self, message: EmailMessage) -> None:
        ...

@dataclass
class CapturingMailer:
    """An in-memory mailer that records sent messages for inspection."""

    sent: List[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def clear(self) -> None:
        self.sent.clear()

class SMTPMailer:
    """Production mailer that delivers via SMTP using the standard library.

    Configured from application settings (host, port, credentials, from-address)
    which are sourced exclusively from environment variables. Raises
    :class:`MailerError` on any delivery failure so the outbox can retry.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        from_email: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._use_tls = use_tls

    def send(self, message: EmailMessage) -> None:
        import smtplib
        from email.message import EmailMessage as MimeMessage

        mime = MimeMessage()
        mime["From"] = self._from_email
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.body)
        if message.attachment_bytes is not None:
            maintype, _, subtype = message.attachment_mime.partition("/")
            mime.add_attachment(
                message.attachment_bytes,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=message.attachment_filename or "attachment",
            )

        try:
            with smtplib.SMTP(self._host, self._port, timeout=30) as smtp:
                if self._use_tls:
                    smtp.starttls()
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.send_message(mime)
        except Exception as exc:
            raise MailerError(f"SMTP delivery failed: {exc}") from exc

_default_mailer = CapturingMailer()

def get_mailer() -> Mailer:
    """Return the process-wide mailer.

    Uses an :class:`SMTPMailer` when SMTP settings are configured (production),
    otherwise the side-effect-free :class:`CapturingMailer` (local/dev/test).
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.smtp_host and settings.smtp_from_email:
        return SMTPMailer(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_email=settings.smtp_from_email,
        )
    return _default_mailer
