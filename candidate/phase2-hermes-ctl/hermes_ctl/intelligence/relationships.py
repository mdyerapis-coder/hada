"""Hermes CTL — relationship management (Phase 3: Personal Intelligence).

Tracks relationships with contacts, their type, strength, contact frequency,
and context. Builds on the Directory (contacts) and MemoryStore for persistence.

Governance / safety (mirrors context.py, curation.py):
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_relationships()`` reads relationship facts from MemoryStore — read-only.
- ``update_relationship()`` and ``record_interaction()`` upsert to MemoryStore.
- Every field has a safe default — no crashes on empty or missing stores.
Models personal relationships and interaction history on top of the
MemoryStore knowledge graph and inbox store. Supports tracking relationship
types, logging interactions, and querying relationship context.

Governance / safety:
- Pure data model (no network, no LLM at module level).
- Wraps the existing knowledge graph (Node/Edge) for relationship structure.
- Interaction history stored as MemoryStore facts (tagged ``interaction``).
- Every operation has safe defaults — no crashes on empty stores.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RelationshipError(Exception):
    """Raised when relationship operations fail."""


# ---------------------------------------------------------------------------
# Data model (modern API — used by Relationships class)
# ---------------------------------------------------------------------------

RELATIONSHIP_TYPES = {
    "partner",
    "spouse",
    "child",
    "parent",
    "sibling",
    "family",
    "friend",
    "work",
    "colleague",
    "neighbour",
    "professional",
    "other",
}


@dataclass
class Interaction:
    """A single recorded interaction with a person."""

    person: str
    channel: str = ""  # "in-person" | "sms" | "email" | "telegram" | "call"
    summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "channel": self.channel,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Interaction":
        return cls(**d)


@dataclass
class Relationship:
    """A relationship with a person, stored as a knowledge graph edge."""

    person: str
    relation: str  # one of RELATIONSHIP_TYPES
    since: float | None = None
    notes: str = ""
    important_dates: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "relation": self.relation,
            "since": self.since,
            "notes": self.notes,
            "importantDates": dict(self.important_dates),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relationship":
        return cls(
            person=d.get("person", ""),
            relation=d.get("relation", d.get("relationship_type", "other")),
            since=d.get("since", None),
            notes=d.get("notes", ""),
            important_dates=d.get("important_dates", d.get("importantDates", {})),
        )


@dataclass
class RelationshipSnapshot:
    """Collection of all tracked relationships at a point in time."""

    recent_contacts: list[Interaction] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recentContacts": [r.to_dict() for r in self.recent_contacts],
            "relationships": [r.to_dict() for r in self.relationships],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RelationshipSnapshot":
        return cls(
            recent_contacts=[
                Interaction.from_dict(r) for r in d.get("recentContacts", [])
            ],
            relationships=[
                Relationship.from_dict(r) for r in d.get("relationships", [])
            ],
        )


# ---------------------------------------------------------------------------
# Free functions (legacy API)
# ---------------------------------------------------------------------------


def scan_relationships(store: Any) -> list[dict[str, Any]]:
    """Return all relationship facts from the memory store (read-only)."""
    try:
        return [fact.value for fact in store.search(tag="relationship")]
    except Exception:
        return []


def update_relationship(
    store: Any,
    person_id: str,
    *,
    name: str | None = None,
    relationship_type: str | None = None,
    strength: float | None = None,
    contact_count: int | None = None,
    last_contacted: float | None = None,
    channels: list[str] | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert a relationship record in the memory store."""
    try:
        raw = store.recall(f"rel:{person_id}")
    except Exception:
        raw = None
    if raw is None:
        raw = {}
    if name is not None:
        raw["name"] = name
    if relationship_type is not None:
        raw["relationship_type"] = relationship_type
    if strength is not None:
        raw["strength"] = strength
    if contact_count is not None:
        raw["contact_count"] = contact_count
    if last_contacted is not None:
        raw["last_contacted"] = last_contacted
    if channels is not None:
        raw["channels"] = channels
    if notes is not None:
        raw["notes"] = notes
    if tags is not None:
        raw["tags"] = tags
    raw.setdefault("relationship_type", "acquaintance")
    store.remember(f"rel:{person_id}", raw, tags={"relationship", f"person:{person_id}"})
    return raw


def record_interaction(
    store: Any,
    person_id: str,
    channel: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """Record a new interaction, update contact count and recency."""
    now = time.time()
    interaction = {"person": person_id, "channel": channel, "summary": summary, "timestamp": now}
    store.remember(
        f"interaction:{person_id}:{int(now)}:{random.randint(0, 9999)}",
        interaction,
        tags={"interaction", f"person:{person_id}"},
    )
    raw = update_relationship(
        store,
        person_id,
        channels=[channel] if channel else None,
        last_contacted=time.time(),
    )
    count = raw.get("contact_count", 0) + 1
    update_relationship(store, person_id, contact_count=count)
    return interaction


def _compute_strength(contact_count: int, last_contacted: float) -> float:
    """Compute a relationship strength score 0.0–1.0."""
    import math
    recency = max(0.0, min(1.0, 1.0 - (time.time() - last_contacted) / (30 * 24 * 3600)))
    freq = math.log1p(contact_count) / math.log1p(20)
    return round(min(1.0, max(0.0, 0.5 * recency + 0.5 * freq)), 4)


# ---------------------------------------------------------------------------
# Relationships manager (modern API used by tests)
# ---------------------------------------------------------------------------


class Relationships:
    """Manage personal relationships on top of MemoryStore."""

    def __init__(self, store: Any) -> None:
        self._store = store

    # ---- define / query relationships ----

    def add(
        self,
        person: str,
        relation: str,
        *,
        since: float | None = None,
        notes: str = "",
        important_dates: dict[str, str] | None = None,
    ) -> Relationship:
        if relation not in RELATIONSHIP_TYPES:
            raise RelationshipError(
                f"unknown relationship type '{relation}'; "
                f"valid: {sorted(RELATIONSHIP_TYPES)}"
            )
        rel = Relationship(
            person=person,
            relation=relation,
            since=since,
            notes=notes,
            important_dates=important_dates or {},
        )
        fact_id = f"rel:{person}"
        self._store.remember(
            fact_id,
            rel.to_dict(),
            tags={"relationship", f"person:{person}", relation},
        )
        return rel

    def get(self, person: str) -> Relationship | None:
        try:
            raw = self._store.recall(f"rel:{person}")
            if raw is None:
                return None
            if isinstance(raw, dict):
                return Relationship.from_dict(raw)
            return None
        except Exception:
            return None

    def list(self, *, relation: str | None = None) -> list[Relationship]:
        try:
            facts = self._store.search(tag="relationship")
        except Exception:
            return []
        out: list[Relationship] = []
        for f in facts:
            if relation is None or relation in (f.tags or set()):
                try:
                    out.append(Relationship.from_dict(f.value))
                except Exception:
                    continue
        out.sort(key=lambda r: r.person.lower())
        return out

    def remove(self, person: str) -> bool:
        try:
            self._store.forget(f"rel:{person}")
            return True
        except Exception:
            return False

    def log_interaction(
        self, person: str, *, channel: str = "", summary: str = ""
    ) -> Interaction:
        interaction = Interaction(person=person, channel=channel, summary=summary)
        key = f"interaction:{person}:{int(interaction.timestamp)}:{random.randint(0, 9999)}"
        self._store.remember(
            key,
            interaction.to_dict(),
            tags={"interaction", f"person:{person}"},
        )
        self.add(person, _guess_relation(person))
        return interaction

    def interactions_for(self, person: str, *, limit: int = 20) -> list[Interaction]:
        try:
            facts = self._store.search(tag="interaction")
        except Exception:
            return []
        out: list[Interaction] = []
        for f in facts:
            if f.value and f.value.get("person") == person:
                try:
                    out.append(Interaction.from_dict(f.value))
                except Exception:
                    continue
        out.sort(key=lambda x: x.timestamp, reverse=True)
        return out[:limit]

    def last_interaction(self, person: str) -> Interaction | None:
        items = self.interactions_for(person, limit=1)
        return items[0] if items else None

    def set_important_date(self, person: str, label: str, value: str) -> bool:
        rel = self.get(person)
        if rel is None:
            return False
        rel.important_dates[label] = value
        fact_id = f"rel:{person}"
        self._store.remember(fact_id, rel.to_dict(), tags={"relationship", f"person:{person}", rel.relation})
        return True


def _guess_relation(person: str) -> str:
    return "other"
