"""Relationship management for Hermes CTL.

This module preserves both public Phase 3 surfaces:

* snapshot/update/record free functions used by ``hermesctl relationship``; and
* the ``Relationships`` graph facade used by CRM and personal intelligence.

All operations are local and deterministic. Persistence errors fail visibly on
writes; read-only queries return safe empty values.
"""

from __future__ import annotations

import calendar
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from hermes_ctl.memory.store import MemoryError as StoreMemoryError


class RelationshipError(Exception):
    """Raised when relationship operations fail."""


RELATIONSHIP_TYPES = {
    "acquaintance",
    "child",
    "colleague",
    "family",
    "friend",
    "neighbour",
    "other",
    "parent",
    "partner",
    "professional",
    "service",
    "sibling",
    "spouse",
    "work",
}

_interaction_counter = 0


def _next_interaction_id(person: str) -> str:
    """Return a process-unique interaction id even when clocks repeat."""
    global _interaction_counter
    _interaction_counter += 1
    return f"interaction:{person}:{time.time_ns()}:{_interaction_counter}"


@dataclass
class Interaction:
    """A single recorded interaction with a person."""

    person: str
    channel: str = ""
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
    def from_dict(cls, data: dict[str, Any]) -> "Interaction":
        return cls(
            person=str(data.get("person", "")),
            channel=str(data.get("channel", "")),
            summary=str(data.get("summary", "")),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass(init=False)
class Relationship:
    """Compatibility model for relationship records and graph metadata.

    ``person``/``relation`` are aliases for the historical
    ``person_id``/``relationship_type`` fields. Keeping one model prevents the
    CLI and graph facade from silently drifting into incompatible contracts.
    """

    person_id: str
    name: str
    relationship_type: str
    strength: float
    contact_count: int
    last_contacted: float
    channels: list[str]
    notes: str
    tags: list[str]
    updated_at: float
    since: float | None
    important_dates: dict[str, str]

    def __init__(
        self,
        person: str = "",
        relation: str = "acquaintance",
        since: float | None = None,
        notes: str = "",
        important_dates: dict[str, str] | None = None,
        *,
        person_id: str | None = None,
        name: str = "",
        relationship_type: str | None = None,
        strength: float = 0.0,
        contact_count: int = 0,
        last_contacted: float = 0.0,
        channels: list[str] | None = None,
        tags: list[str] | None = None,
        updated_at: float | None = None,
    ) -> None:
        self.person_id = person if person_id is None else person_id
        self.name = name or self.person_id
        self.relationship_type = (
            relation if relationship_type is None else relationship_type
        )
        self.strength = float(strength)
        self.contact_count = int(contact_count)
        self.last_contacted = float(last_contacted)
        self.channels = list(channels or [])
        self.notes = notes
        self.tags = list(tags or [])
        self.updated_at = time.time() if updated_at is None else float(updated_at)
        self.since = since
        self.important_dates = dict(important_dates or {})

    @property
    def person(self) -> str:
        return self.person_id

    @person.setter
    def person(self, value: str) -> None:
        self.person_id = value

    @property
    def relation(self) -> str:
        return self.relationship_type

    @relation.setter
    def relation(self, value: str) -> None:
        self.relationship_type = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "personId": self.person_id,
            "person": self.person_id,
            "name": self.name,
            "relationshipType": self.relationship_type,
            "relation": self.relationship_type,
            "strength": self.strength,
            "contactCount": self.contact_count,
            "lastContacted": self.last_contacted,
            "channels": list(self.channels),
            "notes": self.notes,
            "tags": list(self.tags),
            "updatedAt": self.updated_at,
            "since": self.since,
            "importantDates": dict(self.important_dates),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relationship":
        return cls(
            person_id=str(
                data.get("personId", data.get("person_id", data.get("person", "")))
            ),
            name=str(data.get("name", "")),
            relationship_type=str(
                data.get(
                    "relationshipType",
                    data.get("relationship_type", data.get("relation", "acquaintance")),
                )
            ),
            strength=float(data.get("strength", 0.0)),
            contact_count=int(data.get("contactCount", data.get("contact_count", 0))),
            last_contacted=float(
                data.get("lastContacted", data.get("last_contacted", 0.0))
            ),
            channels=list(data.get("channels", [])),
            notes=str(data.get("notes", "")),
            tags=list(data.get("tags", [])),
            updated_at=float(data.get("updatedAt", data.get("updated_at", time.time()))),
            since=data.get("since"),
            important_dates=dict(
                data.get("importantDates", data.get("important_dates", {}))
            ),
        )


class RelationshipSnapshot(list[dict[str, Any]]):
    """Legacy list result with modern aggregate snapshot attributes."""

    def __init__(
        self,
        recent_contacts: Iterable[Interaction | Relationship] | None = None,
        relationships: list[Relationship] | None = None,
        *,
        total_count: int = 0,
        by_type: dict[str, int] | None = None,
        timestamp: str = "",
    ) -> None:
        self.relationships = list(relationships or [])
        self.total_count = total_count
        self.by_type = dict(by_type or {})
        self.recent_contacts = list(recent_contacts or [])
        self.timestamp = timestamp
        super().__init__(
            [dict(RelationshipResult(item)) for item in self.relationships]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalCount": self.total_count,
            "byType": dict(self.by_type),
            "recentContacts": [item.to_dict() for item in self.recent_contacts],
            "relationships": [item.to_dict() for item in self.relationships],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationshipSnapshot":
        return cls(
            relationships=[
                Relationship.from_dict(item) for item in data.get("relationships", [])
            ],
            total_count=int(data.get("totalCount", data.get("total_count", 0))),
            by_type=dict(data.get("byType", data.get("by_type", {}))),
            recent_contacts=[
                Interaction.from_dict(item)
                if "channel" in item or "summary" in item
                else Relationship.from_dict(item)
                for item in data.get("recentContacts", data.get("recent_contacts", []))
            ],
            timestamp=str(data.get("timestamp", "")),
        )


class RelationshipResult(dict[str, Any]):
    """Historical mapping return with modern relationship attributes."""

    def __init__(self, relationship: Relationship) -> None:
        self.relationship = relationship
        super().__init__(
            person_id=relationship.person_id,
            name=relationship.name,
            relationship_type=relationship.relationship_type,
            strength=relationship.strength,
            contact_count=relationship.contact_count,
            last_contacted=relationship.last_contacted,
            channels=list(relationship.channels),
            notes=relationship.notes,
            tags=list(relationship.tags),
            updated_at=relationship.updated_at,
            since=relationship.since,
            important_dates=dict(relationship.important_dates),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.relationship, name)


class InteractionResult(dict[str, Any]):
    """Historical interaction mapping with modern relationship attributes."""

    def __init__(self, interaction: Interaction, relationship: Relationship) -> None:
        self.relationship = relationship
        super().__init__(interaction.to_dict())

    def __getattr__(self, name: str) -> Any:
        return getattr(self.relationship, name)


def _recall_if_present(store: Any, key: str) -> Any:
    has_fact = getattr(store, "has_fact", None)
    if callable(has_fact) and not has_fact(key):
        return None
    try:
        return store.recall(key)
    except StoreMemoryError:
        return None


def _fact_key_and_value(store: Any, person_id: str) -> tuple[str, Any]:
    """Return the existing relationship key/value, preferring the canonical key."""
    for key in (f"rel:{person_id}", f"relationship:{person_id}"):
        value = _recall_if_present(store, key)
        if value is not None:
            return key, value
    return f"rel:{person_id}", None


def _persist_relationship(store: Any, key: str, relationship: Relationship) -> None:
    tags = {
        "relationship",
        f"person:{relationship.person_id}",
        relationship.relationship_type,
        *relationship.tags,
    }
    try:
        store.remember(key, relationship.to_dict(), tags=tags)
    except Exception as exc:
        raise RelationshipError(f"failed to persist relationship: {exc}") from exc


def _store_transaction(store: Any) -> Any:
    transaction = getattr(store, "transaction", None)
    return transaction() if callable(transaction) else nullcontext()


def _persist_canonical_relationship(store: Any, relationship: Relationship) -> None:
    """Write one canonical fact and remove any historical duplicate."""
    canonical = f"rel:{relationship.person_id}"
    legacy = f"relationship:{relationship.person_id}"
    _persist_relationship(store, canonical, relationship)
    if _recall_if_present(store, legacy) is None:
        return
    try:
        store.forget(legacy)
    except Exception as exc:
        raise RelationshipError(f"failed to remove legacy relationship: {exc}") from exc


def _sync_relationship_graph(store: Any, relationship: Relationship) -> None:
    person = relationship.person_id
    store.add_node(
        f"person:{person}",
        kind="person",
        props={"name": relationship.name or person},
    )
    store.add_node("person:@me", kind="person", props={"name": "me"})
    store.set_relation(
        "person:@me", relationship.relationship_type, f"person:{person}"
    )


def scan_relationships(store: Any = None) -> RelationshipSnapshot:
    """Read all relationship records and return aggregate snapshot data."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if store is None:
        return RelationshipSnapshot(timestamp=timestamp)
    try:
        facts = list(store.search(tag="relationship"))
    except Exception:
        return RelationshipSnapshot(timestamp=timestamp)

    by_person: dict[str, Relationship] = {}
    # Legacy facts are consumed first so the canonical rel:* fact always wins.
    facts.sort(
        key=lambda fact: str(getattr(fact, "id", "")).startswith("rel:")
    )
    for fact in facts:
        value = fact.value if hasattr(fact, "value") else None
        if not isinstance(value, dict):
            continue
        try:
            relationship = Relationship.from_dict(value)
        except (TypeError, ValueError):
            continue
        if not relationship.person_id:
            fact_id = str(getattr(fact, "id", ""))
            for prefix in ("rel:", "relationship:"):
                if fact_id.startswith(prefix):
                    relationship.person_id = fact_id[len(prefix) :]
                    break
        if relationship.person_id:
            by_person[relationship.person_id] = relationship

    relationships = sorted(
        by_person.values(), key=lambda item: item.last_contacted, reverse=True
    )
    by_type: dict[str, int] = {}
    for relationship in relationships:
        kind = relationship.relationship_type
        by_type[kind] = by_type.get(kind, 0) + 1
    return RelationshipSnapshot(
        relationships=relationships,
        total_count=len(relationships),
        by_type=by_type,
        recent_contacts=relationships[:5],
        timestamp=timestamp,
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
) -> RelationshipResult:
    """Create or update a relationship without discarding omitted fields."""
    if not person_id:
        raise RelationshipError("person_id is required")
    with _store_transaction(store):
        _, raw = _fact_key_and_value(store, person_id)
        relationship = (
            Relationship.from_dict(raw)
            if isinstance(raw, dict)
            else Relationship(person_id=person_id)
        )
        relationship.person_id = person_id
        if name is not None and name:
            relationship.name = name
        if relationship_type is not None:
            relationship.relationship_type = relationship_type
        if strength is not None:
            relationship.strength = strength
        if contact_count is not None:
            relationship.contact_count = contact_count
        if last_contacted is not None:
            relationship.last_contacted = last_contacted
        if channels is not None:
            relationship.channels = list(dict.fromkeys(channels))
        if notes is not None:
            relationship.notes = notes
        if tags is not None:
            relationship.tags = list(dict.fromkeys(tags))
        relationship.updated_at = time.time()
        _sync_relationship_graph(store, relationship)
        _persist_canonical_relationship(store, relationship)
    return RelationshipResult(relationship)


def _compute_strength(contact_count: int, last_contacted: float) -> float:
    """Preserve the historical linear frequency/recency strength contract."""
    frequency = min(max(0, contact_count) / 10.0, 1.0) * 0.8
    days_since = (
        (time.time() - last_contacted) / 86400.0 if last_contacted else 365.0
    )
    recency = max(0.0, 0.2 - (days_since / 35.0))
    return min(frequency + recency, 1.0)


def record_interaction(
    store: Any,
    person_id: str,
    channel: str = "",
    summary: str = "",
    *,
    name: str = "",
    relationship_type: str | None = None,
) -> InteractionResult:
    """Record an interaction and preserve accumulated relationship metadata."""
    if not person_id:
        raise RelationshipError("person_id is required")
    with _store_transaction(store):
        _, raw = _fact_key_and_value(store, person_id)
        is_new = not isinstance(raw, dict)
        relationship = (
            Relationship.from_dict(raw)
            if isinstance(raw, dict)
            else Relationship(person_id=person_id, name=name)
        )
        relationship.person_id = person_id
        if name and not relationship.name:
            relationship.name = name
        if relationship_type is not None:
            relationship.relationship_type = relationship_type
        relationship.contact_count += 1
        relationship.last_contacted = time.time()
        relationship.updated_at = relationship.last_contacted
        if channel and channel not in relationship.channels:
            relationship.channels.append(channel)
        relationship.strength = (
            0.1
            if is_new
            else _compute_strength(
                relationship.contact_count, relationship.last_contacted
            )
        )
        _sync_relationship_graph(store, relationship)
        _persist_canonical_relationship(store, relationship)

        interaction = Interaction(
            person=person_id,
            channel=channel,
            summary=summary,
            timestamp=relationship.last_contacted,
        )
        try:
            store.remember(
                _next_interaction_id(person_id),
                interaction.to_dict(),
                tags={"interaction", f"person:{person_id}"},
            )
        except Exception as exc:
            raise RelationshipError(f"failed to record interaction: {exc}") from exc
    return InteractionResult(interaction, relationship)


class Relationships:
    """Manage relationship graph metadata and interaction history."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def add(
        self,
        person: str,
        relation: str,
        *,
        since: float | None = None,
        notes: str = "",
        important_dates: dict[str, str] | None = None,
    ) -> Relationship:
        if not person:
            raise RelationshipError("person is required")
        if relation not in RELATIONSHIP_TYPES:
            raise RelationshipError(
                f"unknown relationship type '{relation}'; valid: {sorted(RELATIONSHIP_TYPES)}"
            )
        try:
            with _store_transaction(self._store):
                existing = self.get(person)
                relationship = existing or Relationship(person=person, relation=relation)
                relationship.person = person
                relationship.name = relationship.name or person
                relationship.relation = relation
                relationship.since = since if since is not None else relationship.since
                relationship.notes = notes if notes else relationship.notes
                if important_dates is not None:
                    relationship.important_dates = dict(important_dates)
                relationship.updated_at = time.time()
                _sync_relationship_graph(self._store, relationship)
                _persist_canonical_relationship(self._store, relationship)
        except Exception as exc:
            raise RelationshipError(f"failed to add relationship: {exc}") from exc
        return relationship

    def get(self, person: str) -> Relationship | None:
        _, raw = _fact_key_and_value(self._store, person)
        if not isinstance(raw, dict):
            return None
        try:
            return Relationship.from_dict(raw)
        except (TypeError, ValueError):
            return None

    def list(self, *, relation: str | None = None) -> list[Relationship]:
        relationships = scan_relationships(store=self._store).relationships
        if relation is not None:
            relationships = [item for item in relationships if item.relation == relation]
        return sorted(relationships, key=lambda item: item.person.lower())

    def remove(self, person: str) -> bool:
        try:
            with _store_transaction(self._store):
                if self.get(person) is None:
                    return False
                for key in (f"rel:{person}", f"relationship:{person}"):
                    if _recall_if_present(self._store, key) is None:
                        continue
                    self._store.forget(key)
                self._store.remove_node(f"person:{person}")
        except Exception as exc:
            raise RelationshipError(f"failed to remove relationship: {exc}") from exc
        return True

    def log_interaction(
        self, person: str, *, channel: str = "", summary: str = ""
    ) -> Interaction:
        if not person:
            raise RelationshipError("person is required")
        interaction = Interaction(person=person, channel=channel, summary=summary)
        fact_id = _next_interaction_id(person)
        try:
            with _store_transaction(self._store):
                if self.get(person) is None:
                    self.add(person, "other")
                tags = {"interaction", f"person:{person}"}
                if channel:
                    tags.add(channel)
                self._store.remember(fact_id, interaction.to_dict(), tags=tags)
        except Exception as exc:
            raise RelationshipError(f"failed to log interaction: {exc}") from exc
        return interaction

    def interactions(
        self, person: str | None = None, *, limit: int = 10
    ) -> list[Interaction]:
        try:
            facts = self._store.search(tag="interaction")
        except Exception:
            return []
        interactions: list[Interaction] = []
        for fact in facts:
            try:
                interaction = Interaction.from_dict(fact.value)
            except (AttributeError, TypeError, ValueError):
                continue
            if person is None or interaction.person == person:
                interactions.append(interaction)
        interactions.sort(key=lambda item: item.timestamp, reverse=True)
        return interactions[: max(0, limit)]

    def interactions_for(self, person: str, *, limit: int = 20) -> list[Interaction]:
        """Compatibility alias for person-filtered interactions."""
        return self.interactions(person, limit=limit)

    def last_interaction(self, person: str) -> Interaction | None:
        interactions = self.interactions(person, limit=1)
        return interactions[0] if interactions else None

    def set_important_date(self, person: str, label: str, value: str) -> bool:
        try:
            with _store_transaction(self._store):
                relationship = self.get(person)
                if relationship is None:
                    return False
                relationship.important_dates[label] = value
                relationship.updated_at = time.time()
                _persist_canonical_relationship(self._store, relationship)
        except Exception as exc:
            raise RelationshipError(f"failed to set important date: {exc}") from exc
        return True

    def upcoming_dates(self, *, within_days: float = 30) -> list[dict[str, Any]]:
        """Return important dates occurring within the requested window."""
        today = date.today()
        current_year = today.year
        results: list[dict[str, Any]] = []
        for relationship in self.list():
            for label, date_text in relationship.important_dates.items():
                parts = date_text.split("-")
                if len(parts) == 3:
                    _, month_text, day_text = parts
                elif len(parts) == 2:
                    month_text, day_text = parts
                else:
                    continue
                try:
                    month = int(month_text)
                    day = min(int(day_text), calendar.monthrange(current_year, month)[1])
                    target = date(current_year, month, day)
                except (ValueError, OverflowError):
                    continue
                days_until = (target - today).days
                if 0 <= days_until <= within_days:
                    results.append(
                        {
                            "person": relationship.person,
                            "label": label,
                            "date": date_text,
                            "daysUntil": round(days_until),
                        }
                    )
        return sorted(results, key=lambda item: item["daysUntil"])
