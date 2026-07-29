"""Tests for the relationship management module (offline, no network/LLM)."""

import time

import pytest

from hermes_ctl.intelligence.relationships import (
    RELATIONSHIP_TYPES,
    Interaction,
    Relationship,
    RelationshipError,
    Relationships,
)
from hermes_ctl.memory.store import MemoryStore


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


def test_add_updates_legacy_fact_without_creating_conflict(tmp_path):
    """Manager updates preserve the historical key instead of forking state."""
    path = tmp_path / "mem.json"
    store = MemoryStore(persist_path=str(path))
    store.remember(
        "relationship:Alice",
        Relationship(person="Alice", relation="friend", notes="legacy").to_dict(),
        tags={"relationship", "person:Alice", "friend"},
    )

    Relationships(store).add("Alice", "partner")

    reloaded = MemoryStore(persist_path=str(path))
    facts = [fact for fact in reloaded.search(tag="relationship") if fact.value.get("person") == "Alice"]
    assert [fact.id for fact in facts] == ["relationship:Alice"]
    relationship = Relationship.from_dict(facts[0].value)
    assert relationship.relation == "partner"
    assert relationship.notes == "legacy"


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


def test_add_creates_me_to_person_edge(tmp_path):
    store = _make_store(tmp_path)
    Relationships(store).add("Janni", "child")
    assert any(
        edge.source == "person:@me"
        and edge.target == "person:Janni"
        and edge.relation == "child"
        for edge in store._edges
    )


def test_add_is_idempotent_and_replaces_relationship_edge(tmp_path):
    path = tmp_path / "mem.json"
    store = MemoryStore(persist_path=str(path))
    manager = Relationships(store)

    manager.add("Alice", "partner")
    manager.add("Alice", "partner")
    manager.add("Alice", "friend")

    reloaded = MemoryStore(persist_path=str(path))
    edges = [
        edge
        for edge in reloaded._edges
        if edge.source == "person:@me" and edge.target == "person:Alice"
    ]
    assert [(edge.relation, edge.target) for edge in edges] == [("friend", "person:Alice")]


def test_log_interaction_preserves_existing_metadata(tmp_path):
    manager = Relationships(_make_store(tmp_path))
    manager.add(
        "Courtney",
        "partner",
        since=123.0,
        notes="important",
        important_dates={"birthday": "1990-06-15"},
    )
    manager.log_interaction("Courtney", channel="sms", summary="hello")
    relationship = manager.get("Courtney")
    assert relationship is not None
    assert relationship.relation == "partner"
    assert relationship.since == 123.0
    assert relationship.notes == "important"
    assert relationship.important_dates == {"birthday": "1990-06-15"}


def test_interaction_ids_do_not_collide(tmp_path, monkeypatch):
    store = _make_store(tmp_path)
    manager = Relationships(store)
    monkeypatch.setattr("hermes_ctl.intelligence.relationships.time.time_ns", lambda: 1)
    manager.log_interaction("Courtney", summary="first")
    manager.log_interaction("Courtney", summary="second")
    assert len(manager.interactions()) == 2


def test_upcoming_dates(tmp_path):
    manager = Relationships(_make_store(tmp_path))
    now = time.localtime()
    today = f"{now.tm_mon:02d}-{now.tm_mday:02d}"
    manager.add("Courtney", "partner", important_dates={"anniversary": today})
    result = manager.upcoming_dates(within_days=1)
    assert result
    assert result[0]["person"] == "Courtney"
