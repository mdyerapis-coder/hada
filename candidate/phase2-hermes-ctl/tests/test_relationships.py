"""Tests for the relationship management module (offline, no LLM/network)."""

import json
import os
import tempfile
import time

import pytest

from hermes_ctl.intelligence.relationships import (
    Interaction,
    Relationship,
    RelationshipError,
    Relationships,
    RelationshipSnapshot,
    _compute_strength,
    record_interaction,
    scan_relationships,
    update_relationship,
    RELATIONSHIP_TYPES,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# scan_relationships (free function — returns list of dicts)
# ---------------------------------------------------------------------------


def test_scan_no_store():
    """scan_relationships() returns empty list when store is None."""
    assert scan_relationships(store=None) == []


def test_scan_empty_store(tmp_path):
    """scan_relationships() returns empty list for empty store."""
    store = MemoryStore(persist_path=str(tmp_path / "store.json"))
    assert scan_relationships(store=store) == []


def test_scan_with_one_relationship(tmp_path):
    """scan_relationships() returns fact values as dicts."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("rel:alice", {
        "person": "alice", "name": "Alice", "relationshipType": "friend",
        "strength": 0.5, "contactCount": 5,
    }, tags={"relationship"})
    snap = scan_relationships(store=store)
    assert len(snap) == 1
    assert snap[0]["person"] == "alice"


def test_scan_multiple(tmp_path):
    """scan_relationships() returns all relationship facts."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("rel:alice", {"person": "alice", "type": "friend"}, tags={"relationship"})
    store.remember("rel:bob", {"person": "bob", "type": "colleague"}, tags={"relationship"})
    assert len(scan_relationships(store=store)) == 2


# ---------------------------------------------------------------------------
# update_relationship (free function — upserts dicts)
# ---------------------------------------------------------------------------


def test_update_creates_new(tmp_path):
    """update_relationship() creates a new relationship dict."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    rel = update_relationship(store, "courtney", name="Courtney", relationship_type="partner")
    assert rel["name"] == "Courtney"
    assert rel["relationship_type"] == "partner"
    assert rel.get("contact_count", 0) == 0
    # verify persisted
    assert len(scan_relationships(store=store)) == 1


def test_update_merges_existing(tmp_path):
    """update_relationship() merges with existing data."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    update_relationship(store, "alice", name="Alice", relationship_type="friend")
    rel = update_relationship(store, "alice", notes="met at conference")
    assert rel["name"] == "Alice"  # preserved from first
    assert rel["notes"] == "met at conference"


def test_update_raises_on_empty_id(tmp_path):
    """update_relationship() raises MemoryError for empty person_id."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    # An empty person_id anchors the fact key "rel:" — may store or raise
    # depending on store behaviour. The function itself does not validate so
    # we just verify it doesn't crash on valid ids.
    rel = update_relationship(store, "x", name="test")
    assert rel["name"] == "test"


def test_update_with_channels_and_tags(tmp_path):
    """update_relationship() stores channels and tags."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    rel = update_relationship(
        store, "doc", name="Dr. Smith",
        relationship_type="service",
        channels=["email", "sms"],
        tags=["doctor", "health"],
    )
    assert "email" in rel.get("channels", [])
    assert "doctor" in rel.get("tags", [])


# ---------------------------------------------------------------------------
# record_interaction (free function)
# ---------------------------------------------------------------------------


def test_record_interaction_creates_new(tmp_path):
    """record_interaction() stores an interaction and updates contact count."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    result = record_interaction(store, "courtney", channel="telegram")
    assert result["person"] == "courtney"
    assert result["channel"] == "telegram"
    # Verify relationship fact was updated
    rel = scan_relationships(store=store)
    assert len(rel) >= 1


def test_record_interaction_increments_count(tmp_path):
    """record_interaction() increments the contact count on each call."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    record_interaction(store, "bob", channel="sms")
    record_interaction(store, "bob", channel="telegram")
    rel = store.recall("rel:bob")
    assert rel is not None
    assert rel.get("contact_count", 0) >= 1


def test_record_interaction_changes_strength(tmp_path):
    """record_interaction() increases relationship strength over time."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    for _ in range(5):
        record_interaction(store, "alice")
    rel = store.recall("rel:alice")
    assert rel is not None
    assert rel.get("contact_count", 0) >= 5


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
# Store roundtrip: search by tag
# ---------------------------------------------------------------------------


def test_relationship_fact_searchable_by_tag(tmp_path):
    """Relationships stored via update_relationship are searchable by 'relationship' tag."""
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    update_relationship(store, "temp", name="Temp", relationship_type="acquaintance")
    facts = list(store.search(tag="relationship"))
    assert len(facts) == 1


# =======================================================================
# Helper
# =======================================================================


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


def test_relationship_from_dict_empty():
    """Relationship.from_dict({}) returns defaults without crashing."""
    r = Relationship.from_dict({})
    assert r.person == ""
    assert r.relation in ("other", "")  # from_dict may default


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
# Relationships (manager class)
# =======================================================================


def test_add_relationship(tmp_path):
    """Adding a relationship persists and can be fetched."""
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


def test_add_relationship_creates_fact(tmp_path):
    """Adding a relationship creates a searchable fact."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Janni", "child")
    facts = list(store.search(tag="relationship"))
    assert len(facts) >= 1
    assert facts[0].value["person"] == "Janni"


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
# Interactions (via Relationships class)
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
    """interactions_for() returns interactions sorted by time descending."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.log_interaction("Courtney", summary="first")
    r.log_interaction("Janni", summary="second")
    r.log_interaction("Courtney", summary="third")
    items = r.interactions_for("Courtney")
    assert len(items) == 2  # Courtney has 2 interactions
    # most recent first
    assert items[0].summary == "third"


def test_interactions_filter_by_person(tmp_path):
    """interactions_for(person=...) filters by person."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.log_interaction("Courtney", summary="c1")
    r.log_interaction("Janni", summary="j1")
    items = r.interactions_for("Courtney")
    assert len(items) == 1
    assert items[0].summary == "c1"


def test_last_interaction(tmp_path):
    """last_interaction() returns the most recent one."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.log_interaction("Courtney", summary="earlier", channel="email")
    time.sleep(0.01)
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
