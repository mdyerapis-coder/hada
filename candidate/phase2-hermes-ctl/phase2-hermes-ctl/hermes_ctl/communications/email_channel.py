"""Hermes CTL — Email transport (Phase 2, gated integration).

Implements the `Channel` seam for email via SMTP (send) + IMAP (receive),
using only the stdlib (smtplib / imaplib / email). Credentials are read from
the environment at call time and are NEVER stored on disk or in the repo
(governance: no secrets persisted).

Tested offline by monkeypatching smtplib.SMTP_SSL / imaplib.IMAP4_SSL.
"""

from __future__ import annotations

import email
import imaplib
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from hermes_ctl.communications.channels import Channel, Message


class EmailChannel(Channel):
    """SMTP/IMAP transport (Gmail-shaped). Creds from env, never stored."""

    name = "email"

    def __init__(
        self,
        user: str | None = None,
        password: str | None = None,
        *,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 465,
        imap_host: str = "imap.gmail.com",
        imap_port: int = 993,
    ) -> None:
        self._user = user
        self._password = password
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._imap_host = imap_host
        self._imap_port = imap_port

    def _creds(self) -> tuple[str, str]:
        user = self._user or os.environ.get("GMAIL_SMTP_USER")
        pw = self._password or os.environ.get("GMAIL_APP_PASSWORD")
        if not user or not pw:
            raise RuntimeError("GMAIL_SMTP_USER / GMAIL_APP_PASSWORD not set (inject at runtime; never stored)")
        return user, pw

    def send(self, message: Message) -> str:
        user, pw = self._creds()
        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = message.recipient
        msg["Subject"] = message.subject or "(no subject)"
        msg.set_content(message.body)
        # Gmail app passwords are 16 chars; spaces are tolerated by the server
        # but we strip them defensively.
        pw_clean = pw.replace(" ", "")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, context=context) as server:
            server.login(user, pw_clean)
            server.send_message(msg)
        message.id = f"email:{message.recipient}:{message.subject or ''}"
        return message.id or ""

    def received(self, *, limit: int = 10) -> list[Message]:
        user, pw = self._creds()
        pw_clean = pw.replace(" ", "")
        out: list[Message] = []
        with imaplib.IMAP4_SSL(self._imap_host, self._imap_port) as imap:
            imap.login(user, pw_clean)
            imap.select("INBOX")
            status, data = imap.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                return out
            ids = data[0].split()[-limit:]
            for num in ids:
                _, raw = imap.fetch(num, "(RFC822)")
                if not raw or not raw[0]:
                    continue
                parsed = email.message_from_bytes(bytes(raw[0][1]))
                body = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            body = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
                            break
                else:
                    payload = parsed.get_payload(decode=True)
                    body = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
                out.append(
                    Message(
                        channel="email",
                        sender=str(parsed.get("From", "")),
                        recipient=str(parsed.get("To", "")),
                        subject=str(parsed.get("Subject", "")),
                        body=body,
                    )
                )
        return out
