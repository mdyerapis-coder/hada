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

from hermes_ctl.memory.store import MemoryError as StoreMemoryError


# ---------------------------------------------------------------------------
# Legacy API compatibility helpers
# ---------------------------------------------------------------------------


class _AttrDict(dict):
    """Dict subclass that also supports attribute read/write access (legacy compat)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class _AttrList(list):
    """List subclass that also supports arbitrary attributes (legacy compat)."""
    pass


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


# Module-level interaction counter for unique keys
_interaction_seq: int = 0


def _next_interaction_seq() -> int:
    global _interaction_seq
    _interaction_seq += 1
    return _interaction_seq


@dataclass
class Relationship:
    """A relationship with a person — unified dataclass.

    Supports both the rich API (person_id, name, relationship_type, strength,
    contact_count, last_contacted, channels, tags, notes) and the simple
    Relationships-class API (person, relation, since, notes, important_dates).

    Also supports dict-like access via ``__getitem__`` / ``get`` for legacy
    compatibility.
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

    def __post_init__(self) -> None:
        """Detect historical 5-arg positional constructor and remap fields.

        The old API was ``Relationship(person, relation, since, notes,
        important_dates)``.  When the dataclass fields receive those positional
        arguments they land in the wrong slots (person_id, name, relationship_type,
        strength, contact_count).  We detect this by checking whether ``name``
        holds a valid relationship-type string (rather than a real name), and
        whether ``person`` is still empty.
        """
        if not self.person_id:
            return
        # Historical pattern: person_id == person, name == relation,
        # relationship_type == since (float/None), strength == notes (str),
        # contact_count == important_dates (dict)
        has_old_pattern = (
            not self.person
            and self.name in RELATIONSHIP_TYPES
        )
        if not has_old_pattern:
            return
        self.person = self.person_id
        self.relation = self.name
        if isinstance(self.relationship_type, (int, float)) or self.relationship_type is None:
            self.since = self.relationship_type  # type: ignore[assignment]
        if isinstance(self.strength, str):
            self.notes = self.strength
        if isinstance(self.contact_count, dict):
            self.important_dates = self.contact_count  # type: ignore[assignment]
        # Reset consumed fields so they don't cause confusion later
        self.person_id = ""
        self.name = ""
        self.relationship_type = "acquaintance"
        self.strength = 0.0
        self.contact_count = 0

    def __getitem__(self, key: str) -> Any:
        """Support dict-style access, e.g. rel['relationship_type']."""
        field_map = {
            "personId": "person_id",
            "relationshipType": "relationship_type",
            "contactCount": "contact_count",
            "lastContacted": "last_contacted",
            "importantDates": "important_dates",
        }
        attr = field_map.get(key, key)
        return getattr(self, attr)

    def get(self, key: str, default: Any = None) -> Any:
        """dict-like ``.get()`` for legacy code that expects a mapping."""
        try:
            return self[key]
        except (AttributeError, KeyError, TypeError):
            return default

    def to_dict(self) -> dict[str, Any]:
        # Sync relationship_type with relation when one is set and the other
        # is the default, so legacy dict access (``rel["relationship_type"]``)
        # returns the meaningful value regardless of which API was used.
        rel_type = self.relationship_type
        if rel_type == "acquaintance" and self.relation not in ("other", ""):
            rel_type = self.relation
        person = self.person if self.person else (self.person_id or self.name)
        relation = self.relation if self.relation != "other" else (rel_type if rel_type != "acquaintance" else "other")
        return {
            # CamelCase (rich API)
            "personId": self.person_id,
            "person_id": self.person_id,
            "name": self.name,
            "relationshipType": rel_type,
            "relationship_type": rel_type,
            "strength": self.strength,
            "contactCount": self.contact_count,
            "contact_count": self.contact_count,
            "lastContacted": self.last_contacted,
            "last_contacted": self.last_contacted,
            "channels": list(self.channels),
            "tags": list(self.tags),
            "notes": self.notes,
            # Simple API
            "person": person,
            "relation": relation,
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

    def __post_init__(self) -> None:
        """Detect historical 2-arg positional constructor and remap fields.

        The old API was ``RelationshipSnapshot(recent_contacts, relationships)``
        but the dataclass fields are ``total_count, by_type, relationships,
        recent_contacts``.  We detect this when the first two fields receive
        lists instead of int/dict.
        """
        if isinstance(self.total_count, list):
            self.recent_contacts = self.total_count
            self.total_count = 0
        if isinstance(self.by_type, list):
            self.relationships = self.by_type
            self.by_type = {}
            if not self.total_count:
                self.total_count = len(self.relationships)

    def __getitem__(self, index: int) -> dict[str, Any]:
        """Support indexing, e.g. snapshot[0] returns a dict."""
        return self.relationships[index].to_dict()

    def __len__(self) -> int:
        return len(self.relationships)

    def to_dict(self) -> dict[str, Any]:
        def _serialize_recent(item: Any) -> dict[str, Any]:
            if isinstance(item, Interaction):
                return {"_type": "interaction", **item.to_dict()}
            return {"_type": "relationship", **item.to_dict()}

        return {
            "totalCount": self.total_count,
            "byType": dict(self.by_type),
            "relationships": [r.to_dict() for r in self.relationships],
            "recentContacts": [_serialize_recent(r) for r in self.recent_contacts],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RelationshipSnapshot":
        def _deserialize(item: dict[str, Any]) -> Interaction | Relationship:
            data = {k: v for k, v in item.items() if k != "_type"}
            if item.get("_type") == "interaction":
                return Interaction.from_dict(data)
            return Relationship.from_dict(data)

        return cls(
            total_count=d.get("totalCount", d.get("total_count", 0)),
            by_type=d.get("byType", d.get("by_type", {})),
            relationships=[Relationship.from_dict(r) for r in d.get("relationships", [])],
            recent_contacts=[_deserialize(r) for r in d.get("recentContacts", d.get("recent_contacts", []))],
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Free functions (legacy API)
# ---------------------------------------------------------------------------


def scan_relationships(store: Any) -> _AttrList:
    """Return all relationship facts as an _AttrList (legacy API returns a list)."""
    try:
        facts = store.search(tag="relationship")
    except Exception:
        result = _AttrList()
        result.total_count = 0
        result.by_type = {}
        result.relationships = []
        result.recent_contacts = []
        result.timestamp = ""
        return result
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
    result = _AttrList(rels)
    result.total_count = len(rels)
    result.by_type = by_type
    result.relationships = rels
    result.recent_contacts = recent
    result.timestamp = ""
    return result


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
) -> _AttrDict:
    """Upsert a relationship record in the memory store.

    Returns a dict-like ``_AttrDict`` for legacy API compatibility (supports
    both ``d["key"]`` and ``d.key`` access).
    """
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
        rel.relation = relationship_type
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
    # Keep graph edges consistent
    _upsert_graph_edge(store, person_id, rel.relationship_type)
    return _AttrDict(rel.to_dict())


def _upsert_graph_edge(store: Any, person_id: str, relation: str) -> None:
    """Ensure the ``@me → person`` edge exists with the current relation."""
    try:
        store.set_relation("person:@me", relation, f"person:{person_id}")
    except Exception:
        pass


def record_interaction(
    store: Any,
    person_id: str,
    channel: str = "",
    summary: str = "",
    *,
    name: str = "",
    relationship_type: str | None = None,
) -> _AttrDict:
    """Record a new interaction, update contact count and recency."""
    interaction: dict[str, Any] = {
        "person": person_id,
        "channel": channel or "",
        "summary": summary or "",
        "timestamp": time.time(),
    }
    try:
        store.remember(
            f"interaction:{person_id}:{time.time_ns()}:{_next_interaction_seq()}",
            interaction,
            tags={"interaction", f"person:{person_id}"},
        )
    except Exception as exc:
        raise RelationshipError("failed to record interaction") from exc
    rel = update_relationship(
        store,
        person_id,
        name=name or None,
        relationship_type=relationship_type,
        channels=[channel] if channel else None,
        last_contacted=time.time(),
    )
    # rel is an _AttrDict; update mutable contact_count + strength
    rel.contact_count += 1
    # Simple strength formula for interaction recording: count-based
    rel.strength = round(min(1.0, max(0.0, rel.contact_count / 10)), 4)
    store.remember(
        f"rel:{person_id}",
        rel.to_dict(),
        tags={"relationship", f"person:{person_id}"},
    )
    # Merge interaction fields so legacy callers can access
    # both relationship fields (contact_count, strength) and
    # interaction fields (person, channel, summary).
    rel["channel"] = channel or ""
    rel["summary"] = summary or ""
    rel["person"] = person_id
    return rel


def _compute_strength(contact_count: int, last_contacted: float) -> float:
    """Compute a relationship strength score 0.0–1.0 (historical formula)."""
    return round(min(1.0, max(0.0, contact_count * 0.28)), 4)


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
        # Migrate any legacy ``relationship:{person}`` fact to ``rel:{person}``
        # and remove the old key so there is exactly one canonical fact.
        try:
            self._migrate_legacy_key(person)
        except StoreMemoryError:
            pass
        except Exception as exc:
            raise RelationshipError("legacy read failure") from exc
        # Load existing relationship if present (preserves migrated metadata)
        existing = self.get(person)
        if existing is not None:
            existing.relation = relation
            if since is not None:
                existing.since = since
            if notes:
                existing.notes = notes
            if important_dates:
                existing.important_dates.update(important_dates)
            rel = existing
        else:
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
        # Create or update the graph edge
        try:
            self._store.set_relation("person:@me", relation, f"person:{person}")
        except Exception:
            pass
        try:
            self._store.remember(
                fact_id,
                rel.to_dict(),
                tags={"relationship", f"person:{person}", relation},
            )
        except BaseException:
            # Rollback graph additions on fact write failure
            self._cleanup_after_failed_add(person)
            raise RelationshipError("failed to add relationship")
        return rel

    def _migrate_legacy_key(self, person: str) -> None:
        """Migrate legacy ``relationship:{person}`` → ``rel:{person}``.

        If the canonical key already exists we preserve it; otherwise we
        copy the legacy value and delete the old key.
        """
        legacy_id = f"relationship:{person}"
        canonical_id = f"rel:{person}"
        try:
            canonical = self._store.recall(canonical_id)
        except Exception:
            canonical = None
        try:
            legacy_raw = self._store.recall(legacy_id)
        except StoreMemoryError:
            legacy_raw = None  # no legacy fact — OK
        if legacy_raw is None:
            return  # no legacy fact to migrate
        if canonical is None:
            # Promote the legacy fact to the canonical key
            self._store.remember(
                canonical_id,
                legacy_raw,
                tags={"relationship", f"person:{person}"},
            )
        # Remove the legacy key
        try:
            self._store.forget(legacy_id)
        except Exception:
            pass

    def _cleanup_after_failed_add(self, person: str) -> None:
        """Remove nodes and edges created during a failed add."""
        try:
            self._store.remove_node(f"person:{person}")
        except Exception:
            pass
        # Also remove @me if it's now isolated (no edges left)
        try:
            if not self._store.neighbors("person:@me"):
                self._store.remove_node("person:@me")
        except Exception:
            pass

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
        except StoreMemoryError:
            return False
        except Exception as exc:
            raise RelationshipError("failed to remove relationship") from exc
        # Clean up graph nodes and edges
        try:
            self._store.remove_node(f"person:{person}")
        except Exception:
            pass
        # Also remove @me if now isolated
        try:
            if not self._store.neighbors("person:@me"):
                self._store.remove_node("person:@me")
        except Exception:
            pass
        return True

    # ---- interactions ----

    def log_interaction(
        self, person: str, *, channel: str = "", summary: str = ""
    ) -> Interaction:
        interaction = Interaction(person=person, channel=channel, summary=summary)
        key = f"interaction:{person}:{time.time_ns()}:{_next_interaction_seq()}"
        self._store.remember(
            key,
            interaction.to_dict(),
            tags={"interaction", f"person:{person}"},
        )
        # Only add a relationship if one doesn't already exist — don't overwrite
        # existing metadata.
        existing = self.get(person)
        if existing is None:
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
        try:
            self._store.remember(
                fact_id,
                rel.to_dict(),
                tags={"relationship", f"person:{person}", rel.relation},
            )
        except BaseException as exc:
            raise RelationshipError("failed to set important date") from exc
        return True

    def upcoming_dates(
        self, within_days: int = 30
    ) -> list[dict[str, Any]]:
        """Return important dates occurring within the next N days."""
        now = time.localtime()
        from datetime import datetime, timedelta

        today = datetime(now.tm_year, now.tm_mon, now.tm_mday)
        deadline = today + timedelta(days=within_days)
        result: list[dict[str, Any]] = []
        for rel in self.list():
            for label, date_str in rel.important_dates.items():
                # Support MM-DD format
                parts = date_str.split("-")
                if len(parts) == 2:
                    month, day = int(parts[0]), int(parts[1])
                    date_this_year = datetime(now.tm_year, month, day)
                    if today <= date_this_year <= deadline:
                        result.append({
                            "person": rel.person,
                            "label": label,
                            "date": date_str,
                            "datetime": date_this_year.isoformat(),
                        })
        result.sort(key=lambda x: x["datetime"])
        return result


def _guess_relation(person: str) -> str:
    return "other"
