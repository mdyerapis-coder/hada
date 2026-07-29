"""Unit tests for the Hermes CTL memory store (Phase 2 foundation)."""

import json
import os
import tempfile
import threading

import pytest

from hermes_ctl.memory.store import (
    Edge,
    Fact,
    MemoryError,
    MemoryStore,
    Node,
    PersistenceCommitError,
)


def test_long_term_remember_recall_forget():
    m = MemoryStore()
    m.remember("user.name", "Mason Dyer", tags=["identity", "profile"])
    assert m.recall("user.name") == "Mason Dyer"
    m.forget("user.name")
    try:
        m.recall("user.name")
        assert False, "expected MemoryError after forget"
    except MemoryError:
        pass


def test_long_term_ttl_expiry():
    m = MemoryStore()
    m.remember("otp", "123456", ttl=0.01)
    import time

    time.sleep(0.02)
    try:
        m.recall("otp")
        assert False, "expected expiry"
    except MemoryError:
        pass


def test_search_by_tag():
    m = MemoryStore()
    m.remember("a", 1, tags=["x"])
    m.remember("b", 2, tags=["y"])
    m.remember("c", 3, tags=["x"])
    hits = m.search(tag="x")
    assert {f.id for f in hits} == {"a", "c"}


def test_working_memory_lifecycle():
    m = MemoryStore()
    m.put_working("session", {"turn": 1})
    assert m.get_working("session")["turn"] == 1
    m.clear_working()
    try:
        m.get_working("session")
        assert False, "expected MemoryError after clear"
    except MemoryError:
        pass


def test_knowledge_graph_nodes_and_edges():
    m = MemoryStore()
    m.add_node("mason", "person", {"role": "owner"})
    m.add_node("janni", "person", {"role": "child"})
    m.relate("mason", "parent_of", "janni")
    edges = m.neighbors("mason", relation="parent_of")
    assert len(edges) == 1
    assert edges[0].target == "janni"
    # relate requires existing nodes
    try:
        m.relate("mason", "knows", "ghost")
        assert False, "expected MemoryError for unknown target"
    except MemoryError:
        pass


def test_json_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "mem.json")
        m1 = MemoryStore(persist_path=path)
        m1.remember("k", "v", tags=["t"])
        m1.add_node("n1", "person")
        m1.relate("n1", "knows", "n1")
        m2 = MemoryStore(persist_path=path)
        assert m2.recall("k") == "v"
        assert m2.search(tag="t")[0].id == "k"
        assert m2.neighbors("n1")[0].relation == "knows"


def test_fact_serialization_shape():
    f = Fact(id="x", value={"a": 1}, tags={"t"})
    d = f.to_dict()
    assert d["id"] == "x"
    assert d["tags"] == ["t"]
    f2 = Fact.from_dict(d)
    assert f2.tags == {"t"} and f2.value == {"a": 1}


def test_edge_serialization_shape():
    e = Edge(source="a", target="b", relation="r")
    d = e.to_dict()
    assert Edge.from_dict(d) == e


def test_set_relation_rolls_back_live_state_when_persistence_fails(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(path))
    store.add_node("person:@me", "person")
    store.add_node("person:Alice", "person")
    store.set_relation("person:@me", "partner", "person:Alice")

    def fail_save():
        raise OSError("injected save failure")

    monkeypatch.setattr(store, "_save", fail_save)
    with pytest.raises(OSError, match="injected save failure"):
        store.set_relation("person:@me", "friend", "person:Alice")

    assert [(edge.relation, edge.target) for edge in store._edges] == [
        ("partner", "person:Alice")
    ]
    reloaded = MemoryStore(persist_path=str(path))
    assert [(edge.relation, edge.target) for edge in reloaded._edges] == [
        ("partner", "person:Alice")
    ]


def test_caught_nested_write_failure_aborts_outer_transaction(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(path))
    store.add_node("person:@me", "person")
    store.add_node("person:Alice", "person")
    store.set_relation("person:@me", "partner", "person:Alice")
    original_save = store._save

    def fail_save():
        raise OSError("injected nested failure")

    with pytest.raises(MemoryError, match="nested failure"):
        with store.transaction():
            monkeypatch.setattr(store, "_save", fail_save)
            try:
                store.set_relation("person:@me", "friend", "person:Alice")
            except OSError:
                pass
            finally:
                monkeypatch.setattr(store, "_save", original_save)

    assert [(edge.relation, edge.target) for edge in store._edges] == [
        ("partner", "person:Alice")
    ]


def test_serialization_failure_removes_partial_temp_file(tmp_path):
    path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(path))
    store.remember("stable", "value")

    with pytest.raises(TypeError):
        store.remember("bad", object())

    assert list(tmp_path.glob("memory.json.tmp*")) == []
    assert store.recall("stable") == "value"
    with pytest.raises(MemoryError):
        store.recall("bad")


def test_expiry_save_failure_rolls_back_live_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(path))
    store.remember("expired", "still durable", ttl=0)

    def fail_save():
        raise OSError("injected expiry save failure")

    monkeypatch.setattr(store, "_save", fail_save)
    with pytest.raises(OSError, match="expiry save failure"):
        store.recall("expired")

    assert "expired" in store._facts
    assert MemoryStore(persist_path=str(path))._facts["expired"].value == "still durable"


def test_two_instances_do_not_lose_concurrent_writes(tmp_path):
    path = tmp_path / "memory.json"
    first = MemoryStore(persist_path=str(path))
    second = MemoryStore(persist_path=str(path))
    barrier = threading.Barrier(2)
    errors = []

    def write_many(store, prefix):
        try:
            barrier.wait()
            for number in range(25):
                store.remember(f"{prefix}:{number}", number)
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    threads = [
        threading.Thread(target=write_many, args=(first, "a")),
        threading.Thread(target=write_many, args=(second, "b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    reloaded = MemoryStore(persist_path=str(path))
    assert len(reloaded._facts) == 50


def test_reload_failure_preserves_live_state(tmp_path):
    path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(path))
    store.remember("stable", "value")
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        store.has_fact("stable")
    assert store._facts["stable"].value == "value"


def test_directory_fsync_failure_keeps_committed_live_and_durable_state(
    tmp_path, monkeypatch
):
    path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(path))
    store.remember("stable", "value")
    real_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    with pytest.raises(PersistenceCommitError) as caught:
        store.remember("new", "committed")

    assert caught.value.committed is True
    assert store.recall("new") == "committed"
    reloaded = MemoryStore(persist_path=str(path))
    assert reloaded.recall("new") == "committed"
    assert set(store._facts) == set(reloaded._facts) == {"stable", "new"}
