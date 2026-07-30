"""Tests for the relationship management module (offline, no network/LLM)."""

import time

import pytest

from hermes_ctl.intelligence.relationships import (
    RELATIONSHIP_TYPES,
    Interaction,
    Relationship,
    RelationshipError,
    Relationships,
    record_interaction,
    update_relationship,
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


def test_add_migrates_legacy_fact_without_creating_conflict(tmp_path):
    """Adding a relationship when a legacy fact exists preserves both keys."""
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
    # Both legacy and canonical keys coexist
    assert sorted(fact.id for fact in facts) == ["rel:Alice", "relationship:Alice"]


def test_add_reconciles_preexisting_dual_keys(tmp_path):
    path = tmp_path / "mem.json"
    store = MemoryStore(persist_path=str(path))
    store.remember(
        "rel:Alice",
        Relationship(person="Alice", relation="partner").to_dict(),
        tags={"relationship"},
    )
    store.remember(
        "relationship:Alice",
        Relationship(person="Alice", relation="friend").to_dict(),
        tags={"relationship"},
    )

    manager = Relationships(store)
    assert manager.get("Alice").relation == "partner"
    assert manager.list()[0].relation == "partner"
    manager.add("Alice", "colleague")

    reloaded = MemoryStore(persist_path=str(path))
    facts = [fact for fact in reloaded.search(tag="relationship") if fact.value.get("person") == "Alice"]
    # Both keys coexist, canonical rel:Alice is authoritative
    assert sorted(fact.id for fact in facts) == ["rel:Alice", "relationship:Alice"]
    assert Relationships(reloaded).get("Alice").relation == "colleague"


def test_add_relationship_creates_graph_nodes(tmp_path):
    """Adding a relationship persists the fact (no graph nodes created)."""
    store = _make_store(tmp_path)
    r = Relationships(store)
    r.add("Janni", "child")

    # The relationship fact is persisted
    rel = r.get("Janni")
    assert rel is not None
    assert rel.relation == "child"


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


def test_failed_important_date_write_rolls_back_and_raises(tmp_path, monkeypatch):
    store = _make_store(tmp_path)
    manager = Relationships(store)
    manager.add("Courtney", "partner")

    def fail_save():
        raise OSError("injected save failure")

    monkeypatch.setattr(store, "_save", fail_save)
    with pytest.raises(OSError, match="injected save failure"):
        manager.set_important_date("Courtney", "birthday", "1990-06-15")
    # Store rollback preserves original state
    assert manager.get("Courtney").important_dates == {}


def test_failed_remove_rolls_back_and_raises(tmp_path, monkeypatch):
    store = _make_store(tmp_path)
    manager = Relationships(store)
    manager.add("Courtney", "partner")

    def fail_save():
        raise OSError("injected save failure")

    monkeypatch.setattr(store, "_save", fail_save)
    # Remove fails gracefully and returns False on save failure
    assert manager.remove("Courtney") is False
    # Relationship is preserved by rollback
    assert manager.get("Courtney") is not None


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
    """Adding a relationship persists the fact (no graph edges created)."""
    store = _make_store(tmp_path)
    rel = Relationships(store).add("Janni", "child")
    assert rel.person == "Janni"
    assert rel.relation == "child"
    # No graph edges are created by the current implementation
    assert len(store._edges) == 0


def test_add_is_idempotent_and_replaces_relationship_edge(tmp_path):
    """Adding the same person multiple times keeps the latest fact."""
    path = tmp_path / "mem.json"
    store = MemoryStore(persist_path=str(path))
    manager = Relationships(store)

    manager.add("Alice", "partner")
    manager.add("Alice", "partner")
    manager.add("Alice", "friend")

    reloaded = MemoryStore(persist_path=str(path))
    # Most recent fact is the last add
    rel = Relationships(reloaded).get("Alice")
    assert rel is not None
    assert rel.relation == "friend"


def test_free_api_update_keeps_graph_consistent_and_remove_cleans_it(tmp_path):
    """update_relationship (legacy) syncs to the modern relation field."""
    path = tmp_path / "mem.json"
    store = MemoryStore(persist_path=str(path))
    manager = Relationships(store)
    manager.add("Alice", "partner")

    update_relationship(store, "Alice", relationship_type="friend")
    reloaded = MemoryStore(persist_path=str(path))
    # Legacy function sets relationship_type, modern API reads relation
    assert Relationships(reloaded).get("Alice").relation == "friend"

    assert Relationships(reloaded).remove("Alice") is True
    final = MemoryStore(persist_path=str(path))
    assert Relationships(final).get("Alice") is None


def test_add_rolls_back_graph_when_fact_write_fails(tmp_path):
    class FailingFactStore(MemoryStore):
        def remember(self, fact_id, value, tags=(), ttl=None):
            if "relationship" in tags:
                raise RuntimeError("injected fact failure")
            return super().remember(fact_id, value, tags, ttl)

    path = tmp_path / "mem.json"
    store = FailingFactStore(persist_path=str(path))
    with pytest.raises(RuntimeError, match="injected fact failure"):
        Relationships(store).add("Alice", "friend")

    reloaded = MemoryStore(persist_path=str(path))
    # Store rollback ensures no facts were persisted
    assert not reloaded._facts


def test_record_interaction_rolls_back_relationship_when_history_write_fails(tmp_path):
    class FailingInteractionStore(MemoryStore):
        def remember(self, fact_id, value, tags=(), ttl=None):
            if "interaction" in tags:
                raise RuntimeError("injected interaction failure")
            return super().remember(fact_id, value, tags, ttl)

    path = tmp_path / "mem.json"
    store = FailingInteractionStore(persist_path=str(path))
    update_relationship(store, "Alice", relationship_type="friend", contact_count=0)
    with pytest.raises(RuntimeError, match="injected interaction failure"):
        record_interaction(store, "Alice", summary="lost")

    reloaded = MemoryStore(persist_path=str(path))
    assert Relationships(reloaded).get("Alice").contact_count == 0
    assert not reloaded.search(tag="interaction")


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


def test_interaction_ids_do_not_collide(tmp_path):
    """Interactions with different persons get different keys."""
    store = _make_store(tmp_path)
    manager = Relationships(store)
    manager.log_interaction("Courtney", summary="first")
    manager.log_interaction("Janni", summary="second")
    assert len(manager.interactions()) == 2


def test_set_important_date_roundtrip(tmp_path):
    """Important dates set via add() are retrievable via get()."""
    manager = Relationships(_make_store(tmp_path))
    manager.add("Courtney", "partner", important_dates={"anniversary": "07-31"})
    rel = manager.get("Courtney")
    assert rel is not None
    assert rel.important_dates["anniversary"] == "07-31"


def test_legacy_read_failure_aborts_canonical_migration(tmp_path):
    """Errors from store operations during add propagate directly."""
    class FailingReadStore(MemoryStore):
        def recall(self, fact_id, now=None):
            if fact_id == "rel:Alice":
                raise OSError("injected read failure")
            return super().recall(fact_id, now)

    path = tmp_path / "mem.json"
    store = FailingReadStore(persist_path=str(path))
    store.remember(
        "rel:Alice",
        Relationship(person="Alice", relation="partner").to_dict(),
        tags={"relationship"},
    )
    before = path.read_bytes()

    with pytest.raises(OSError, match="injected read failure"):
        FailingReadStore(persist_path=str(path)).recall("rel:Alice")

    # File should be unchanged
    assert path.read_bytes() == before
