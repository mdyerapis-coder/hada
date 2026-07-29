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

import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RelationshipError(Exception):
    """Raised when relationship operations fail."""


# ---------------------------------------------------------------------------
# Data model (unified — supports both legacy free-function and modern API)
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
    """A relationship with a person.

    Supports both the modern API (person / relation) and the legacy API
    (person_id / relationship_type / strength / contact_count / …).
    """

    # Modern fields
    person: str = ""
    relation: str = ""  # one of RELATIONSHIP_TYPES
    since: float | None = None
    notes: str = ""
    important_dates: dict[str, str] = field(default_factory=dict)

    # Legacy fields (aliased from / to serialised dict)
    person_id: str = ""
    name: str = ""
    relationship_type: str = "acquaintance"
    strength: float = 0.0
    contact_count: int = 0
    last_contacted: float = 0.0
    channels: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Keep person_id and relationship_type in sync with modern fields
        if not self.person_id and self.person:
            self.person_id = self.person
        if not self.person and self.person_id:
            self.person = self.person_id
        # relation was explicitly provided → sync to relationship_type
        if self.relation and self.relationship_type == "acquaintance":
            self.relationship_type = self.relation
        # relationship_type was explicitly provided → sync to relation
        if self.relationship_type and not self.relation:
            self.relation = self.relationship_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "personId": self.person_id,
            "name": self.name,
            "relation": self.relation,
            "relationshipType": self.relationship_type,
            "strength": self.strength,
            "contactCount": self.contact_count,
            "lastContacted": self.last_contacted,
            "channels": list(self.channels),
            "tags": list(self.tags),
            "notes": self.notes,
            "since": self.since,
            "importantDates": dict(self.important_dates),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relationship":
        person_id = d.get("personId") or d.get("person_id") or d.get("person", "")
        return cls(
            person=person_id,
            person_id=person_id,
            name=d.get("name", ""),
            relation=d.get("relation", d.get("relationshipType",
                          d.get("relationship_type", "other"))),
            relationship_type=d.get("relationshipType",
                            d.get("relationship_type", "acquaintance")),
            since=d.get("since", None),
            notes=d.get("notes", ""),
            strength=float(d.get("strength", 0.0)),
            contact_count=int(d.get("contactCount", d.get("contact_count", 0))),
            last_contacted=float(d.get("lastContacted", d.get("last_contacted", 0.0))),
            channels=list(d.get("channels", [])),
            tags=list(d.get("tags", [])),
            important_dates=d.get("important_dates", d.get("importantDates", {})),
        )


@dataclass
class RelationshipSnapshot:
    """Collection of all tracked relationships at a point in time."""

    relationships: list[Relationship] = field(default_factory=list)
    recent_contacts: list[Interaction] = field(default_factory=list)
    total_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCount": self.total_count,
            "byType": dict(self.by_type),
            "relationships": [r.to_dict() for r in self.relationships],
            "recentContacts": [r.to_dict() for r in self.recent_contacts],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RelationshipSnapshot":
        rels = [Relationship.from_dict(r) for r in d.get("relationships", [])]
        return cls(
            relationships=rels,
            recent_contacts=[
                Interaction.from_dict(r) for r in d.get("recentContacts", [])
            ],
            total_count=d.get("totalCount", d.get("total_count", len(rels))),
            by_type=dict(d.get("byType", d.get("by_type", {}))),
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Free functions (legacy API — used by CLI)
# ---------------------------------------------------------------------------


def scan_relationships(store: Any) -> RelationshipSnapshot:
    """Return a RelationshipSnapshot from all relationship facts (read-only)."""
    try:
        facts = list(store.search(tag="relationship"))
    except Exception:
        facts = []

    rels: list[Relationship] = []
    contacts: list[Interaction] = []

    for f in facts:
        try:
            r = Relationship.from_dict(f.value)
            rels.append(r)
            # Build recent-contact list from relationships that have a timestamp
            if r.last_contacted > 0:
                contacts.append(
                    Interaction(
                        person=r.person_id,
                        channel="",
                        summary="",
                        timestamp=r.last_contacted,
                    )
                )
        except Exception:
            continue

    rels.sort(key=lambda x: x.person_id.lower())
    contacts.sort(key=lambda x: x.timestamp, reverse=True)

    by_type: dict[str, int] = {}
    for r in rels:
        t = r.relationship_type or "other"
        by_type[t] = by_type.get(t, 0) + 1

    return RelationshipSnapshot(
        relationships=rels,
        recent_contacts=contacts[:5],
        total_count=len(rels),
        by_type=by_type,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


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
) -> Relationship:
    """Upsert a relationship record in the memory store."""
    if not person_id:
        raise RelationshipError("person_id is required")
    # Gracefully handle missing facts
    try:
        raw = store.recall(f"rel:{person_id}")
    except Exception:
        raw = None
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
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
        existing = raw.get("channels", [])
        if isinstance(existing, list):
            merged = list(dict.fromkeys(existing + channels))  # deduplicate, preserve order
        else:
            merged = channels
        raw["channels"] = merged
    if notes is not None:
        raw["notes"] = notes
    if tags is not None:
        raw["tags"] = tags
    raw.setdefault("person_id", person_id)
    raw.setdefault("person", person_id)
    raw.setdefault("relationship_type", "acquaintance")
    # Auto-compute strength if contact_count and last_contacted are present
    cc = raw.get("contact_count", 0)
    lc = raw.get("last_contacted", 0)
    if lc > 0:
        raw["strength"] = _compute_strength(int(cc), float(lc))
    store.remember(f"rel:{person_id}", raw, tags={"relationship", f"person:{person_id}"})
    return Relationship.from_dict(raw)


def record_interaction(
    store: Any,
    person_id: str,
    *,
    name: str | None = None,
    channel: str = "",
    summary: str = "",
    relationship_type: str | None = None,
) -> Relationship:
    """Record a new interaction, update contact count and recency."""
    interaction = {
        "person": person_id,
        "channel": channel,
        "summary": summary,
        "timestamp": time.time(),
    }
    store.remember(
        f"interaction:{person_id}:{int(time.time())}",
        interaction,
        tags={"interaction", f"person:{person_id}"},
    )
    raw = update_relationship(
        store,
        person_id,
        name=name,
        relationship_type=relationship_type,
        channels=[channel] if channel else None,
        last_contacted=time.time(),
    )
    count = raw.contact_count + 1
    return update_relationship(store, person_id, contact_count=count)


def _compute_strength(contact_count: int, last_contacted: float) -> float:
    """Compute a relationship strength score 0.0–1.0."""
    import math
    recency = max(0.0, min(1.0, 1.0 - (time.time() - last_contacted) / (30 * 24 * 3600)))
    freq = math.log1p(contact_count) / math.log1p(20)
    return round(min(1.0, max(0.0, 0.5 * recency + 0.5 * freq)), 4)


# ---------------------------------------------------------------------------
# Relationships manager (modern API)
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
            person_id=person,
            relation=relation,
            relationship_type=relation,
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

    def interactions(
        self, person: str | None = None, *, limit: int = 20
    ) -> list[Interaction]:
        """Return all interactions, optionally filtered by person."""
        try:
            facts = self._store.search(tag="interaction")
        except Exception:
            return []
        out: list[Interaction] = []
        for f in facts:
            if f.value is None:
                continue
            if person is None or f.value.get("person") == person:
                try:
                    out.append(Interaction.from_dict(f.value))
                except Exception:
                    continue
        out.sort(key=lambda x: x.timestamp, reverse=True)
        return out[:limit]

    def log_interaction(
        self, person: str, *, channel: str = "", summary: str = ""
    ) -> Interaction:
        interaction = Interaction(person=person, channel=channel, summary=summary)
        key = f"interaction:{person}:{time.time_ns()}"
        self._store.remember(
            key,
            interaction.to_dict(),
            tags={"interaction", f"person:{person}"},
        )
        self.add(person, _guess_relation(person))
        return interaction

    def interactions_for(self, person: str, *, limit: int = 20) -> list[Interaction]:
        return self.interactions(person=person, limit=limit)

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
