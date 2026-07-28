"""Hermes CTL — relationship management (Phase 3: Personal Intelligence).

<<<<<<< HEAD
Tracks relationships with contacts, their type, strength, contact frequency,
and context. Builds on the Directory (contacts) and MemoryStore for persistence.

Governance / safety (mirrors context.py, curation.py):
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_relationships()`` reads relationship facts from MemoryStore — read-only.
- ``update_relationship()`` and ``record_interaction()`` upsert to MemoryStore.
- Every field has a safe default — no crashes on empty or missing stores.
=======
Models personal relationships and interaction history on top of the
MemoryStore knowledge graph and inbox store. Supports tracking relationship
types, logging interactions, and querying relationship context.

Governance / safety:
- Pure data model (no network, no LLM at module level).
- Wraps the existing knowledge graph (Node/Edge) for relationship structure.
- Interaction history stored as MemoryStore facts (tagged ``interaction``).
- Every operation has safe defaults — no crashes on empty stores.
>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


<<<<<<< HEAD
=======
# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
class RelationshipError(Exception):
    """Raised when relationship operations fail."""


# ---------------------------------------------------------------------------
<<<<<<< HEAD
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
=======
# Data models
# ---------------------------------------------------------------------------


# Standard relationship types
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

# Relationship direction labels
DIRECTION_LABELS = {
    "partner": "partner",
    "spouse": "spouse",
    "child": "parent",
    "parent": "child",
    "sibling": "sibling",
    "family": "family",
    "friend": "friend",
    "work": "colleague",
    "colleague": "colleague",
    "neighbour": "neighbour",
    "professional": "client",
    "other": "other",
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
>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relationship":
        return cls(
<<<<<<< HEAD
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
=======
            person=d["person"],
            relation=d["relation"],
            since=d.get("since"),
            notes=d.get("notes", ""),
            important_dates=d.get("importantDates", d.get("important_dates", {})),
>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
        )


# ---------------------------------------------------------------------------
<<<<<<< HEAD
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
=======
# RelationshipStore
# ---------------------------------------------------------------------------


class Relationships:
    """Manage personal relationships on top of MemoryStore.

    Uses the knowledge graph (Node -> person, Edge -> relationship) plus
    interaction history stored as tagged facts.
    """

    _interaction_counter: int = 0

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
        """Register or update a relationship with *person*.

        Creates a knowledge-graph Node for the person (if not present) and
        an Edge from the user node ``@me`` to the person with the given relation.
        """
        if relation not in RELATIONSHIP_TYPES:
            raise RelationshipError(
                f"unknown relationship type '{relation}'; "
                f"valid: {', '.join(sorted(RELATIONSHIP_TYPES))}"
            )

        rel = Relationship(
            person=person,
            relation=relation,
            since=since,
            notes=notes,
            important_dates=important_dates or {},
        )

        try:
            # Ensure person node exists
            try:
                self._store.recall(f"person:{person}")
            except Exception:
                self._store.add_node(f"person:{person}", kind="person", props={"name": person})

            # Ensure @me node exists
            try:
                self._store.recall("person:@me")
            except Exception:
                self._store.add_node("person:@me", kind="person", props={"name": "me"})

            # Relate @me -> person
            self._store.relate("person:@me", relation, f"person:{person}")

            # Store the relationship metadata as a fact
            self._store.remember(
                f"rel:{person}",
                rel.to_dict(),
                tags={"relationship", relation, f"person:{person}"},
            )
        except Exception as exc:
            raise RelationshipError(f"failed to add relationship: {exc}") from exc

        return rel

    def get(self, person: str) -> Relationship | None:
        """Look up a relationship by person name."""
        try:
            raw = self._store.recall(f"rel:{person}")
            return Relationship.from_dict(raw)
        except Exception:
            return None

    def list(self, *, relation: str | None = None) -> list[Relationship]:
        """List all relationships, optionally filtered by type."""
        try:
            facts = self._store.search(tag="relationship")
        except Exception:
            return []
        out: list[Relationship] = []
        for f in facts:
            if relation is None or relation in f.tags:
                try:
                    out.append(Relationship.from_dict(f.value))
                except Exception:
                    continue
        out.sort(key=lambda r: r.person.lower())
        return out

    def remove(self, person: str) -> bool:
        """Remove a relationship and its metadata."""
        try:
            self._store.forget(f"rel:{person}")
            return True
        except Exception:
            return False

    # ---- interactions ----

    def log_interaction(
        self,
        person: str,
        *,
        channel: str = "",
        summary: str = "",
    ) -> Interaction:
        """Record an interaction with *person*."""
        interaction = Interaction(
            person=person,
            channel=channel,
            summary=summary,
            timestamp=time.time(),
        )
        self.__class__._interaction_counter += 1
        fact_id = f"interact:{person}:{int(interaction.timestamp)}:{self.__class__._interaction_counter}"
        try:
            self._store.remember(
                fact_id,
                interaction.to_dict(),
                tags={"interaction", f"person:{person}", channel} if channel else {"interaction", f"person:{person}"},
            )
        except Exception as exc:
            raise RelationshipError(f"failed to log interaction: {exc}") from exc
        return interaction

    def interactions(
        self,
        person: str | None = None,
        *,
        limit: int = 10,
    ) -> list[Interaction]:
        """List recent interactions, optionally filtered by person."""
        try:
            facts = self._store.search(tag="interaction")
        except Exception:
            return []
        out: list[Interaction] = []
        for f in facts:
            try:
                interaction = Interaction.from_dict(f.value)
                if person is None or interaction.person == person:
                    out.append(interaction)
            except Exception:
                continue
        out.sort(key=lambda i: i.timestamp, reverse=True)
        return out[:limit]

    def last_interaction(self, person: str) -> Interaction | None:
        """Get the most recent interaction with *person*."""
        items = self.interactions(person, limit=1)
        return items[0] if items else None

    # ---- important dates ----

    def set_important_date(self, person: str, label: str, date: str) -> bool:
        """Set an important date (e.g. birthday=1990-06-15) for a person."""
        rel = self.get(person)
        if rel is None:
            return False
        rel.important_dates[label] = date
        try:
            self._store.remember(f"rel:{person}", rel.to_dict(), tags={"relationship", rel.relation, f"person:{person}"})
        except Exception:
            return False
        return True

    def upcoming_dates(self, *, within_days: float = 30) -> list[dict[str, Any]]:
        """Find upcoming important dates (birthdays, anniversaries) within the window."""
        now = time.gmtime()
        current_year = now.tm_year
        results: list[dict[str, Any]] = []

        for rel in self.list():
            for label, date_str in rel.important_dates.items():
                # Parse YYYY-MM-DD or MM-DD
                parts = date_str.split("-")
                if len(parts) == 3:
                    _, month, day = parts
                elif len(parts) == 2:
                    month, day = parts
                else:
                    continue
                try:
                    month_int = int(month)
                    day_int = int(day)
                except ValueError:
                    continue

                # Check this year's date
                import calendar

                target_day = min(day_int, calendar.monthrange(current_year, month_int)[1])
                target = time.strptime(f"{current_year}-{month_int:02d}-{target_day:02d}", "%Y-%m-%d")
                target_ts = time.mktime(target)
                now_ts = time.time()

                days_until = (target_ts - now_ts) / 86400.0
                if 0 <= days_until <= within_days:
                    results.append({
                        "person": rel.person,
                        "label": label,
                        "date": date_str,
                        "daysUntil": round(days_until),
                    })

        results.sort(key=lambda r: r["daysUntil"])
        return results
>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
