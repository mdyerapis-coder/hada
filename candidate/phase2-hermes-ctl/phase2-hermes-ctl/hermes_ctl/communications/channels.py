"""Hermes CTL — Communications subsystem (Phase 2).

Defines the channel abstraction + a local, offline-testable transport. Real
transports (Email/SMTP, SMS, Telegram) are NOT implemented here — they require
network + credentials and are explicitly out of scope for the foundation per
the governance boundary (no secrets/infra in foundation modules).

Instead we ship:
  - `Message`: a content-addressed, typed message record.
  - `Channel` (ABC): the seam every real transport implements.
  - `LocalChannel`: an in-memory channel for verification + local dev.

This makes the Communications surface real and testable now, and gives a
clean interface for gated, later-added network transports.
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """A typed, content-hashable message."""

    channel: str
    sender: str
    recipient: str
    body: str
    subject: str | None = None
    created_at: float = field(default_factory=time.time)
    id: str | None = None

    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "channel": self.channel,
                "sender": self.sender,
                "recipient": self.recipient,
                "body": self.body,
                "subject": self.subject,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def with_id(self) -> "Message":
        if self.id is None:
            self.id = self.content_hash()
        return self


class Channel(ABC):
    """Transport seam. Real adapters (Email/SMS/Telegram) implement send()."""

    name = "abstract"

    @abstractmethod
    def send(self, message: Message) -> str:
        """Deliver the message; return a delivery id."""

    @abstractmethod
    def received(self) -> list[Message]:
        """Return messages received on this channel (for polling)."""


class LocalChannel(Channel):
    """In-memory channel — offline-testable, no network/credentials."""

    name = "local"

    def __init__(self) -> None:
        self._outbox: list[Message] = []
        self._inbox: list[Message] = []

    def send(self, message: Message) -> str:
        message = message.with_id()
        self._outbox.append(message)
        # local echo: also deliver into the recipient's inbox
        self._inbox.append(
            Message(
                channel=message.channel,
                sender=message.sender,
                recipient=message.recipient,
                body=message.body,
                subject=message.subject,
                created_at=message.created_at,
                id=message.id,
            )
        )
        return message.id or ""

    def received(self) -> list[Message]:
        return list(self._inbox)

    def outbox(self) -> list[Message]:
        return list(self._outbox)


class Directory:
    """Contact directory backed by MemoryStore."""

    def __init__(self, store: Any) -> None:
        from hermes_ctl.memory.store import MemoryStore

        if not isinstance(store, MemoryStore):
            raise TypeError("Directory requires a MemoryStore")
        self._store = store

    _ID = "communications.contacts"

    def add_contact(self, handle: str, **fields: Any) -> dict[str, Any]:
        try:
            contacts = dict(self._store.recall(self._ID))
        except Exception:
            contacts = {}
        contacts[handle] = fields
        self._store.remember(self._ID, contacts, tags=["communications", "contacts"])
        return contacts[handle]

    def get_contact(self, handle: str) -> dict[str, Any] | None:
        try:
            return self._store.recall(self._ID).get(handle)
        except Exception:
            return None

    def all_contacts(self) -> dict[str, Any]:
        try:
            return dict(self._store.recall(self._ID))
        except Exception:
            return {}
