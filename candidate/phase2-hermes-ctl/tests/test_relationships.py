"""Tests for the relationship management module (offline, no LLM/network)."""

import json
import os
import tempfile
import time

import pytest

from hermes_ctl.intelligence.relationships import (
    Relationship,
    RelationshipError,
    RelationshipSnapshot,
    record_interaction,
    scan_relationships,
    update_relationship,
    _compute_strength,
)
from hermes_ctl.memory.store import MemoryStore


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
    assert rel.strength == 0.1


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


def test_compute_strength_preserves_historical_formula(monkeypatch):
    monkeypatch.setattr("hermes_ctl.intelligence.relationships.time.time", lambda: 1_000_000.0)
    assert _compute_strength(1, 1_000_000.0) == pytest.approx(0.28)


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


def test_record_interaction_ids_do_not_collide(tmp_path, monkeypatch):
    store = MemoryStore(persist_path=str(tmp_path / "store.json"))
    monkeypatch.setattr("hermes_ctl.intelligence.relationships.time.time_ns", lambda: 1)
    record_interaction(store, "courtney", channel="sms")
    record_interaction(store, "courtney", channel="telegram")
    assert len(list(store.search(tag="interaction"))) == 2


def test_legacy_positional_calls_and_mapping_returns(tmp_path):
    store = MemoryStore(persist_path=str(tmp_path / "store.json"))
    updated = update_relationship(
        store, "courtney", name="Courtney", relationship_type="partner"
    )
    assert isinstance(updated, dict)
    assert updated.get("relationship_type") == "partner"
    assert updated.person_id == "courtney"

    scanned = scan_relationships(store)
    assert isinstance(scanned, list)
    assert scanned.total_count == 1
    assert scanned[0]["relationship_type"] == "partner"

    recorded = record_interaction(store, "courtney", "sms", "hello")
    assert isinstance(recorded, dict)
    assert recorded["person"] == "courtney"
    assert recorded["channel"] == "sms"
    assert recorded["summary"] == "hello"
    assert recorded.contact_count == 1
