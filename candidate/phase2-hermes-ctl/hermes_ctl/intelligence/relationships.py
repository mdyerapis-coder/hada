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
# Data model — unified Relationship
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
    """A relationship with a person — unified dataclass.

    Supports both the rich API (person_id, name, relationship_type, strength,
    contact_count, last_contacted, channels, tags, notes) and the simple
    Relationships-class API (person, relation, since, notes, important_dates).
    """

    # Rich API fields
    person_id: str = ""
    name: str = ""
    relationship_type: str = "acquaintance"
    strength: float = 0.0
    contact_count: int = 0
    last_contacted: float = 0.0
    channels: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    # Simple API fields (used by Relationships class)
    person: str = ""
    relation: str = "other"
    since: float | None = None
    important_dates: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            # CamelCase (rich API)
            "personId": self.person_id,
            "person_id": self.person_id,
            "name": self.name,
            "relationshipType": self.relationship_type,
            "relationship_type": self.relationship_type,
            "strength": self.strength,
            "contactCount": self.contact_count,
            "contact_count": self.contact_count,
            "lastContacted": self.last_contacted,
            "last_contacted": self.last_contacted,
            "channels": list(self.channels),
            "tags": list(self.tags),
            "notes": self.notes,
            # Simple API
            "person": self.person if self.person else (self.person_id or self.name),
            "relation": self.relation if self.relation != "other" else (self.relationship_type if self.relationship_type != "acquaintance" else "other"),
            "since": self.since,
            "importantDates": dict(self.important_dates),
            "important_dates": dict(self.important_dates),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relationship":
        return cls(
            person_id=d.get("person_id", d.get("personId", "")),
            name=d.get("name", ""),
            relationship_type=d.get("relationship_type", d.get("relationshipType", "acquaintance")),
            strength=d.get("strength", 0.0),
            contact_count=d.get("contact_count", d.get("contactCount", 0)),
            last_contacted=d.get("last_contacted", d.get("lastContacted", 0.0)),
            channels=d.get("channels", d.get("channel", [])),
            tags=d.get("tags", []),
            notes=d.get("notes", ""),
            person=d.get("person", ""),
            relation=d.get("relation", d.get("relationship_type", d.get("relationshipType", "other"))),
            since=d.get("since", None),
            important_dates=d.get("important_dates", d.get("importantDates", {})),
        )


@dataclass
class RelationshipSnapshot:
    """Collection of all tracked relationships at a point in time."""

    total_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    recent_contacts: list[Relationship] = field(default_factory=list)
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
        return cls(
            total_count=d.get("totalCount", d.get("total_count", 0)),
            by_type=d.get("byType", d.get("by_type", {})),
            relationships=[Relationship.from_dict(r) for r in d.get("relationships", [])],
            recent_contacts=[Relationship.from_dict(r) for r in d.get("recentContacts", d.get("recent_contacts", []))],
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Free functions (legacy API)
# ---------------------------------------------------------------------------


def scan_relationships(store: Any) -> RelationshipSnapshot:
    """Return all relationship facts as a RelationshipSnapshot (read-only)."""
    try:
        facts = store.search(tag="relationship")
    except Exception:
        return RelationshipSnapshot()
    rels: list[Relationship] = []
    for fact in facts:
        try:
            if isinstance(fact.value, dict):
                rels.append(Relationship.from_dict(fact.value))
        except Exception:
            continue
    by_type: dict[str, int] = {}
    for r in rels:
        by_type[r.relationship_type] = by_type.get(r.relationship_type, 0) + 1
    recent = sorted(rels, key=lambda r: r.last_contacted, reverse=True)[:5]
    return RelationshipSnapshot(
        total_count=len(rels),
        by_type=by_type,
        relationships=rels,
        recent_contacts=recent,
        timestamp="",
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
    # Load existing
    try:
        existing = store.recall(f"rel:{person_id}")
    except Exception:
        existing = None
    if existing and isinstance(existing, dict):
        rel = Relationship.from_dict(existing)
    else:
        rel = Relationship(person_id=person_id, name=name or "")
    # Apply updates
    if name is not None:
        rel.name = name
    if relationship_type is not None:
        rel.relationship_type = relationship_type
    if strength is not None:
        rel.strength = strength
    if contact_count is not None:
        rel.contact_count = contact_count
    if last_contacted is not None:
        rel.last_contacted = last_contacted
    if channels is not None:
        existing_channels = set(rel.channels)
        existing_channels.update(channels)
        rel.channels = sorted(existing_channels)
    if notes is not None:
        rel.notes = notes
    if tags is not None:
        existing_tags = set(rel.tags)
        existing_tags.update(tags)
        rel.tags = sorted(existing_tags)
    # Persist
    store.remember(
        f"rel:{person_id}",
        rel.to_dict(),
        tags={"relationship", f"person:{person_id}"},
    )
    return rel


def record_interaction(
    store: Any,
    person_id: str,
    *,
    name: str = "",
    channel: str = "",
    summary: str = "",
    relationship_type: str | None = None,
) -> Relationship:
    """Record a new interaction, update contact count and recency."""
    interaction: dict[str, Any] = {
        "person": person_id,
        "channel": channel or "",
        "summary": summary or "",
        "timestamp": time.time(),
    }
    store.remember(
        f"interaction:{person_id}:{time.time_ns()}",
        interaction,
        tags={"interaction", f"person:{person_id}"},
    )
    rel = update_relationship(
        store,
        person_id,
        name=name or None,
        relationship_type=relationship_type,
        channels=[channel] if channel else None,
        last_contacted=time.time(),
    )
    rel.contact_count += 1
    rel.strength = _compute_strength(rel.contact_count, rel.last_contacted)
    store.remember(
        f"rel:{person_id}",
        rel.to_dict(),
        tags={"relationship", f"person:{person_id}"},
    )
    return rel


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
            relation=relation,
            since=since,
            notes=notes,
            important_dates=important_dates or {},
        )
        fact_id = f"rel:{person}"
        # Ensure graph nodes exist
        self._store.add_node(f"person:{person}", kind="person", props={"name": person})
        if not self._store._nodes.get("person:@me"):
            self._store.add_node("person:@me", kind="person", props={"name": "Me"})
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

    # ---- interactions ----

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

    def interactions(
        self, *, person: str | None = None, limit: int = 20
    ) -> list[Interaction]:
        """Return interactions, optionally filtered by person, sorted by time descending."""
        try:
            facts = self._store.search(tag="interaction")
        except Exception:
            return []
        out: list[Interaction] = []
        for f in facts:
            if person and f.value and f.value.get("person") != person:
                continue
            try:
                out.append(Interaction.from_dict(f.value))
            except Exception:
                continue
        out.sort(key=lambda x: x.timestamp, reverse=True)
        return out[:limit]

    def interactions_for(self, person: str, *, limit: int = 20) -> list[Interaction]:
        """Return interactions for a specific person."""
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
        self._store.remember(
            fact_id,
            rel.to_dict(),
            tags={"relationship", f"person:{person}", rel.relation},
        )
        return True


def _guess_relation(person: str) -> str:
    return "other"
