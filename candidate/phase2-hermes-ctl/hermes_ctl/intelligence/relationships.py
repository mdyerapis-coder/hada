"""Hermes CTL — relationship management (Phase 3: Personal Intelligence).

Tracks relationships with contacts, their type, strength, contact frequency,
and context. Builds on the Directory (contacts) and MemoryStore for persistence.

Governance / safety (mirrors context.py, curation.py):
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_relationships()`` reads relationship facts from MemoryStore — read-only.
- ``update_relationship()`` and ``record_interaction()`` upsert to MemoryStore.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class RelationshipError(Exception):
    """Raised when relationship operations fail."""


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------


@dataclass
class Relationship:
    """A relationship record for one person/contact.

    All fields have safe defaults so consumers never crash on missing data.
    """

    person_id: str = ""
    """Unique identifier for this person (handle or contact key)."""

    name: str = ""
    """Display name of the person."""

    relationship_type: str = "acquaintance"
    """Category: family, partner, friend, colleague, acquaintance, service, other."""

    strength: float = 0.0
    """Relationship strength 0.0–1.0 (derived from contact frequency + recency)."""

    contact_count: int = 0
    """How many times we've interacted (messages received)."""

    last_contacted: float = 0.0
    """Unix timestamp of the most recent interaction."""

    channels: list[str] = field(default_factory=list)
    """Channels used for contact (e.g. ['telegram', 'sms', 'email'])."""

    notes: str = ""
    """Free-text notes about this person/relationship."""

    tags: list[str] = field(default_factory=list)
    """Extra tags for grouping (e.g. ['doctor', 'school', 'neighbour'])."""

    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "personId": self.person_id,
            "name": self.name,
            "relationshipType": self.relationship_type,
            "strength": self.strength,
            "contactCount": self.contact_count,
            "lastContacted": self.last_contacted,
            "channels": list(self.channels),
            "notes": self.notes,
            "tags": list(self.tags),
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relationship":
        return cls(
            person_id=d.get("personId", d.get("person_id", "")),
            name=d.get("name", ""),
            relationship_type=d.get("relationshipType", d.get("relationship_type", "acquaintance")),
            strength=d.get("strength", 0.0),
            contact_count=d.get("contactCount", d.get("contact_count", 0)),
            last_contacted=d.get("lastContacted", d.get("last_contacted", 0.0)),
            channels=list(d.get("channels", [])),
            notes=d.get("notes", ""),
            tags=list(d.get("tags", [])),
            updated_at=d.get("updatedAt", d.get("updated_at", time.time())),
        )


@dataclass
class RelationshipSnapshot:
    """Collection of all tracked relationships at a point in time."""

    relationships: list[Relationship] = field(default_factory=list)
    total_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    recent_contacts: list[Relationship] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCount": self.total_count,
            "byType": dict(self.by_type),
            "recentContacts": [r.to_dict() for r in self.recent_contacts],
            "relationships": [r.to_dict() for r in self.relationships],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RelationshipSnapshot":
        return cls(
            total_count=d.get("totalCount", d.get("total_count", 0)),
            by_type=dict(d.get("byType", d.get("by_type", {}))),
            recent_contacts=[Relationship.from_dict(r) for r in d.get("recentContacts", d.get("recent_contacts", []))],
            relationships=[Relationship.from_dict(r) for r in d.get("relationships", [])],
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan (read-only collection)
# ---------------------------------------------------------------------------


def scan_relationships(
    *,
    store: Any = None,
) -> RelationshipSnapshot:
    """Read all relationship records from MemoryStore. Read-only.

    Args:
        store: A MemoryStore instance (or anything with search() that returns
               Fact-like objects).

    Returns:
        A populated ``RelationshipSnapshot`` with totals and type breakdown.
        Every field has a safe default.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if store is None:
        return RelationshipSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="relationship"))
    except Exception:
        return RelationshipSnapshot(timestamp=ts)

    relationships: list[Relationship] = []
    by_type: dict[str, int] = {}

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        rel = Relationship.from_dict(val)
        if rel.person_id:
            # fact.id is "relationship:<person_id>" — strip prefix
            fid = getattr(fact, "id", "")
            if fid and fid.startswith("relationship:"):
                rel.person_id = fid[len("relationship:"):]
            else:
                rel.person_id = fid or rel.person_id
            relationships.append(rel)
            t = rel.relationship_type
            by_type[t] = by_type.get(t, 0) + 1

    # Sort by last_contacted descending for "recent" list
    relationships.sort(key=lambda r: r.last_contacted, reverse=True)

    return RelationshipSnapshot(
        relationships=relationships,
        total_count=len(relationships),
        by_type=by_type,
        recent_contacts=relationships[:5],
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Persistence / updates
# ---------------------------------------------------------------------------


def update_relationship(
    store: Any,
    person_id: str,
    *,
    name: str = "",
    relationship_type: str | None = None,
    strength: float | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
    channels: list[str] | None = None,
) -> Relationship:
    """Create or update a relationship record for a person.

    Args:
        store: A MemoryStore instance.
        person_id: Unique identifier (handle or contact key).
        name: Display name.
        relationship_type: One of (family, partner, friend, colleague, etc.).
        strength: Override the relationship strength (0.0–1.0).
        notes: Free-text notes.
        tags: Extra grouping tags.
        channels: Contact channels used.

    Returns:
        The updated ``Relationship``.

    Raises:
        RelationshipError: if persistence fails.
    """
    if not person_id:
        raise RelationshipError("person_id is required")

    fact_id = f"relationship:{person_id}"

    # Load existing if present
    existing: Relationship | None = None
    try:
        val = store.recall(fact_id)
        if val:
            existing = Relationship.from_dict(val)
    except Exception:
        pass

    now = time.time()
    if existing:
        rel = Relationship(
            person_id=person_id,
            name=name or existing.name,
            relationship_type=relationship_type if relationship_type is not None else existing.relationship_type,
            strength=strength if strength is not None else existing.strength,
            contact_count=existing.contact_count,
            last_contacted=existing.last_contacted,
            channels=channels or existing.channels,
            notes=notes if notes is not None else existing.notes,
            tags=tags or existing.tags,
            updated_at=now,
        )
    else:
        rel = Relationship(
            person_id=person_id,
            name=name,
            relationship_type=relationship_type or "acquaintance",
            strength=strength if strength is not None else 0.0,
            channels=channels or [],
            notes=notes or "",
            tags=tags or [],
            updated_at=now,
        )

    try:
        store.remember(fact_id, rel.to_dict(), tags={"relationship"})
    except Exception as exc:
        raise RelationshipError(f"failed to persist relationship: {exc}") from exc

    return rel


def record_interaction(
    store: Any,
    person_id: str,
    *,
    name: str = "",
    channel: str = "",
    relationship_type: str | None = None,
) -> Relationship:
    """Record an interaction with a person — updates contact count + recency.

    This is called automatically when messages arrive in the inbox. It
    increments the contact count and updates last_contacted to now.

    Args:
        store: A MemoryStore instance.
        person_id: Unique identifier.
        name: Display name (used only on first creation).
        channel: Which channel the interaction came on (telegram, sms, email).
        relationship_type: Override type if needed.

    Returns:
        The updated ``Relationship``.
    """
    fact_id = f"relationship:{person_id}"
    now = time.time()

    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if val:
        rel = Relationship.from_dict(val)
        rel.contact_count += 1
        rel.last_contacted = now
        rel.updated_at = now
        if channel and channel not in rel.channels:
            rel.channels.append(channel)
        if name and not rel.name:
            rel.name = name
        if relationship_type is not None:
            rel.relationship_type = relationship_type
        # Recalculate strength
        rel.strength = _compute_strength(rel.contact_count, rel.last_contacted)
    else:
        rel = Relationship(
            person_id=person_id,
            name=name,
            relationship_type=relationship_type or "acquaintance",
            strength=0.1,  # initial interaction
            contact_count=1,
            last_contacted=now,
            channels=[channel] if channel else [],
            updated_at=now,
        )

    try:
        store.remember(fact_id, rel.to_dict(), tags={"relationship"})
    except Exception as exc:
        raise RelationshipError(f"failed to record interaction: {exc}") from exc

    return rel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_strength(contact_count: int, last_contacted: float) -> float:
    """Compute a relationship strength score (0.0–1.0) based on interaction history.

    Uses two factors:
    - Frequency bonus: more contacts = stronger, with diminishing returns.
    - Recency bonus: contacts within the last week get a boost.

    Returns a value clamped to [0.0, 1.0].
    """
    now = time.time()

    # Frequency: logarithmic scale, capped at ~10 contacts = 0.8
    freq = min(contact_count / 10.0, 1.0) * 0.8

    # Recency: contacts within 7 days get up to 0.2 bonus
    days_since = (now - last_contacted) / 86400.0 if last_contacted else 365
    recency = max(0.0, 0.2 - (days_since / 35.0))  # decays over ~7 days
    recency = max(0.0, recency)

    return min(freq + recency, 1.0)
