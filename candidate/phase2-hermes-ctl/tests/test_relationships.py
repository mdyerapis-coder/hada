<<<<<<< HEAD
"""Tests for the relationship management module (offline, no LLM/network)."""

import json
import os
import tempfile
=======
"""Tests for the relationship management module (offline, no network/LLM)."""

>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
import time

import pytest

from hermes_ctl.intelligence.relationships import (
<<<<<<< HEAD
    Relationship,
    RelationshipError,
    RelationshipSnapshot,
    record_interaction,
    scan_relationships,
    update_relationship,
    _compute_strength,
=======
    RELATIONSHIP_TYPES,
    Interaction,
    Relationship,
    RelationshipError,
    Relationships,
>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
)
from hermes_ctl.memory.store import MemoryStore


<<<<<<< HEAD
# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_relationship_defaults():
    r = Relationship()
    assert r.person_id == ""
    assert r.relationship_type == "acquaintance"
    assert r.strength == 0.0
    assert r.contact_count == 0
    assert r.channels == []
    assert r.notes == ""


def test_relationship_to_dict_roundtrip():
    r = Relationship(
        person_id="courtney",
        name="Courtney",
        relationship_type="partner",
        strength=0.85,
        contact_count=42,
        last_contacted=time.time(),
        channels=["telegram", "sms"],
        notes="my partner",
        tags=["family"],
    )
    d = r.to_dict()
    assert d["personId"] == "courtney"
    assert d["relationshipType"] == "partner"
    assert d["strength"] == 0.85
    assert d["contactCount"] == 42

    r2 = Relationship.from_dict(d)
    assert r2.person_id == "courtney"
    assert r2.relationship_type == "partner"
    assert r2.strength == 0.85
    assert r2.contact_count == 42
    assert r2.channels == ["telegram", "sms"]


def test_relationship_from_dict_accepts_snake_case():
    r = Relationship.from_dict({
        "person_id": "janni",
        "name": "Janni",
        "relationship_type": "family",
        "strength": 0.9,
    })
    assert r.person_id == "janni"
    assert r.name == "Janni"
    assert r.relationship_type == "family"


def test_relationship_from_dict_empty():
    r = Relationship.from_dict({})
    assert r.person_id == ""
    assert r.relationship_type == "acquaintance"
    assert r.strength == 0.0


def test_snapshot_defaults():
    s = RelationshipSnapshot()
    assert s.total_count == 0
    assert s.by_type == {}
    assert s.relationships == []
    assert s.recent_contacts == []
    assert s.timestamp == ""


def test_snapshot_to_dict_roundtrip():
    r = Relationship(person_id="a", name="Alice", relationship_type="friend", strength=0.5)
    s = RelationshipSnapshot(
        relationships=[r],
        total_count=1,
        by_type={"friend": 1},
        recent_contacts=[r],
        timestamp="2026-07-29T00:00:00Z",
    )
    d = s.to_dict()
    assert d["totalCount"] == 1
    assert d["byType"]["friend"] == 1

    s2 = RelationshipSnapshot.from_dict(d)
    assert s2.total_count == 1
    assert s2.by_type["friend"] == 1
    assert len(s2.relationships) == 1


# ---------------------------------------------------------------------------
# Scan tests (empty store)
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_relationships(store=None)
    assert snap.total_count == 0
    assert snap.relationships == []


def test_scan_empty_store(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    snap = scan_relationships(store=store)
    assert snap.total_count == 0
    assert snap.relationships == []


# ---------------------------------------------------------------------------
# Scan tests (seeded store)
# ---------------------------------------------------------------------------


def test_scan_with_one_relationship(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("relationship:alice", {
        "person_id": "alice", "name": "Alice", "relationshipType": "friend",
        "strength": 0.5, "contactCount": 5, "lastContacted": time.time(),
    }, tags={"relationship"})
    snap = scan_relationships(store=store)
    assert snap.total_count == 1
    assert snap.by_type.get("friend") == 1


def test_scan_with_multiple_types(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("relationship:courtney", {
        "person_id": "courtney", "name": "Courtney", "relationshipType": "partner",
        "contactCount": 10, "lastContacted": time.time(),
    }, tags={"relationship"})
    store.remember("relationship:bob", {
        "person_id": "bob", "name": "Bob", "relationshipType": "colleague",
        "contactCount": 3, "lastContacted": time.time() - 86400 * 30,
    }, tags={"relationship"})
    snap = scan_relationships(store=store)
    assert snap.total_count == 2
    assert snap.by_type["partner"] == 1
    assert snap.by_type["colleague"] == 1
    # most recent first
    assert snap.recent_contacts[0].person_id == "courtney"


def test_scan_recent_contacts_capped(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    for i in range(10):
        store.remember(f"relationship:p{i}", {
            "person_id": f"p{i}", "name": f"Person{i}", "relationshipType": "friend",
            "contactCount": 1, "lastContacted": time.time() - i * 3600,
        }, tags={"relationship"})
    snap = scan_relationships(store=store)
    assert snap.total_count == 10
    assert len(snap.recent_contacts) == 5


# ---------------------------------------------------------------------------
# Update / persistence tests
# ---------------------------------------------------------------------------


def test_update_creates_new_relationship(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    rel = update_relationship(store, "courtney", name="Courtney", relationship_type="partner")
    assert rel.person_id == "courtney"
    assert rel.name == "Courtney"
    assert rel.relationship_type == "partner"
    assert rel.contact_count == 0
    # verify it's in the store
    snap = scan_relationships(store=store)
    assert snap.total_count == 1


def test_update_merges_existing(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    update_relationship(store, "alice", name="Alice", relationship_type="friend")
    # Second update with different fields
    rel = update_relationship(store, "alice", notes="met at conference", strength=0.6)
    assert rel.name == "Alice"  # preserved from first
    assert rel.notes == "met at conference"
    assert rel.strength == 0.6


def test_update_raises_on_empty_id(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(RelationshipError, match="person_id is required"):
        update_relationship(store, "")


def test_update_with_channels_and_tags(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    rel = update_relationship(
        store, "doc", name="Dr. Smith",
        relationship_type="service",
        channels=["email", "sms"],
        tags=["doctor", "health"],
    )
    assert "email" in rel.channels
    assert "doctor" in rel.tags


# ---------------------------------------------------------------------------
# Record interaction tests
# ---------------------------------------------------------------------------


def test_record_interaction_creates_new(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    rel = record_interaction(store, "courtney", name="Courtney", channel="telegram")
    assert rel.contact_count == 1
    assert rel.channels == ["telegram"]
    assert rel.strength > 0


def test_record_interaction_increments_count(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    record_interaction(store, "bob", name="Bob", channel="sms")
    rel = record_interaction(store, "bob", channel="telegram")
    assert rel.contact_count == 2
    assert "sms" in rel.channels
    assert "telegram" in rel.channels


def test_record_interaction_updates_strength(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    r1 = record_interaction(store, "alice", name="Alice")
    first_strength = r1.strength
    # Multiple interactions increase strength
    for _ in range(8):
        record_interaction(store, "alice")
    r_last = record_interaction(store, "alice")
    assert r_last.strength > first_strength


# ---------------------------------------------------------------------------
# Strength computation tests
# ---------------------------------------------------------------------------


def test_compute_strength_increases_with_contacts():
    s1 = _compute_strength(1, time.time())
    s5 = _compute_strength(5, time.time())
    assert s5 > s1


def test_compute_strength_decays_with_age():
    recent = _compute_strength(5, time.time())
    old = _compute_strength(5, time.time() - 86400 * 30)
    assert recent >= old


def test_compute_strength_capped():
    s = _compute_strength(100, time.time())
    assert s <= 1.0
    assert s >= 0.0


# ---------------------------------------------------------------------------
# Integration: store roundtrip with is_expired
# ---------------------------------------------------------------------------


def test_relationship_fact_is_expired(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    update_relationship(store, "temp", name="Temp", relationship_type="acquaintance")
    # Verify it's searchable
    facts = list(store.search(tag="relationship"))
    assert len(facts) == 1
=======
def _make_store(tmp_path) -> MemoryStore:
    return MemoryStore(persist_path=str(tmp_path / "mem.json"))


# =======================================================================
# Relationship dataclass
# =======================================================================


def test_relationship_to_dict():
    r = Relationship(person="Courtney", relation="partner", since=1000.0, notes="wife", important_dates={"birthday": "1990-01-01"})
    d = r.to_dict()
    assert d["person"] == "Courtney"
    assert d["relation"] == "partner"
    assert d["importantDates"]["birthday"] == "1990-01-01"


def test_relationship_from_dict():
    d = {"person": "Janni", "relation": "child", "since": None, "notes": "", "importantDates": {}}
    r = Relationship.from_dict(d)
    assert r.person == "Janni"
    assert r.relation == "child"


# =======================================================================
# Interaction dataclass
# =======================================================================


def test_interaction_to_dict():
    i = Interaction(person="Courtney", channel="sms", summary="discussed dinner", timestamp=1000.0)
    d = i.to_dict()
    assert d["person"] == "Courtney"
    assert d["channel"] == "sms"


def test_interaction_from_dict():
    d = {"person": "Courtney", "channel": "sms", "summary": "hi", "timestamp": 2000.0}
    i = Interaction.from_dict(d)
    assert i.person == "Courtney"
    assert i.summary == "hi"


# =======================================================================
# Relationships
# =======================================================================


def test_add_relationship(tmp_path):
    """Adding a relationship creates a node + edge + fact."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    rel = r.add("Courtney", "partner", notes="wife")
    assert rel.person == "Courtney"
    assert rel.relation == "partner"

    # Verify it persisted
    fetched = r.get("Courtney")
    assert fetched is not None
    assert fetched.person == "Courtney"
    assert fetched.notes == "wife"


def test_add_relationship_creates_graph_nodes(tmp_path):
    """Adding a relationship creates person nodes in the knowledge graph."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Janni", "child")

    # The @me node should exist
    assert "person:@me" in store._nodes
    # The person node should exist
    assert "person:Janni" in store._nodes


def test_add_invalid_relationship_type(tmp_path):
    """Adding a relationship with an invalid type raises RelationshipError."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    with pytest.raises(RelationshipError, match="unknown relationship type"):
        r.add("Test", "invalid_type")


def test_list_relationships(tmp_path):
    """list() returns all relationships."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Courtney", "partner")
    r.add("Janni", "child")
    assert len(r.list()) == 2


def test_list_filter_by_relation(tmp_path):
    """list(relation=...) filters by relationship type."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Courtney", "partner")
    r.add("Janni", "child")
    partners = r.list(relation="partner")
    assert len(partners) == 1
    assert partners[0].person == "Courtney"


def test_get_nonexistent(tmp_path):
    """get() returns None for unknown person."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    assert r.get("Nobody") is None


def test_remove_relationship(tmp_path):
    """remove() deletes the relationship fact."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Courtney", "partner")
    assert r.remove("Courtney") is True
    assert r.get("Courtney") is None


def test_remove_nonexistent(tmp_path):
    """remove() returns False for unknown person."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    assert r.remove("Nobody") is False


def test_add_relationship_with_dates(tmp_path):
    """add() accepts important dates."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Courtney", "partner", important_dates={"birthday": "1990-06-15"})
    rel = r.get("Courtney")
    assert rel is not None
    assert rel.important_dates["birthday"] == "1990-06-15"


# =======================================================================
# Interactions
# =======================================================================


def test_log_interaction(tmp_path):
    """log_interaction() records a new interaction."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    i = r.log_interaction("Courtney", channel="sms", summary="discussed weekend plans")
    assert i.person == "Courtney"
    assert i.channel == "sms"
    assert i.summary == "discussed weekend plans"


def test_interactions_list(tmp_path):
    """interactions() returns all interactions sorted by time descending."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.log_interaction("Courtney", summary="first")
    r.log_interaction("Janni", summary="second")
    r.log_interaction("Courtney", summary="third")
    items = r.interactions()
    assert len(items) == 3
    # most recent first
    assert items[0].summary == "third"


def test_interactions_filter_by_person(tmp_path):
    """interactions(person=...) filters by person."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.log_interaction("Courtney", summary="c1")
    r.log_interaction("Janni", summary="j1")
    items = r.interactions(person="Courtney")
    assert len(items) == 1
    assert items[0].summary == "c1"


def test_last_interaction(tmp_path):
    """last_interaction() returns the most recent one."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.log_interaction("Courtney", summary="earlier", channel="email")
    import time as t_mod
    t_mod.sleep(0.01)
    r.log_interaction("Courtney", summary="latest")
    last = r.last_interaction("Courtney")
    assert last is not None
    assert last.summary == "latest"


def test_last_interaction_none(tmp_path):
    """last_interaction() returns None for a person with no interactions."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    assert r.last_interaction("Nobody") is None


# =======================================================================
# Important dates
# =======================================================================


def test_set_important_date(tmp_path):
    """set_important_date() updates the relationship."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Courtney", "partner")
    assert r.set_important_date("Courtney", "birthday", "1990-06-15") is True
    rel = r.get("Courtney")
    assert rel is not None
    assert rel.important_dates["birthday"] == "1990-06-15"


def test_set_important_date_nonexistent(tmp_path):
    """set_important_date() returns False for unknown person."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    assert r.set_important_date("Nobody", "birthday", "2000-01-01") is False


# =======================================================================
# RELATIONSHIP_TYPES constant
# =======================================================================


def test_relationship_types():
    assert "partner" in RELATIONSHIP_TYPES
    assert "child" in RELATIONSHIP_TYPES
    assert "friend" in RELATIONSHIP_TYPES
    assert "work" in RELATIONSHIP_TYPES
    assert len(RELATIONSHIP_TYPES) >= 10
>>>>>>> 6870f79 (feat(phase3): travel planning module (Cycle 27))
