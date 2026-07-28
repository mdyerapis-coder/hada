"""Unit tests for the Hermes CTL memory store (Phase 2 foundation)."""

import os
import tempfile

from hermes_ctl.memory.store import Edge, Fact, MemoryError, MemoryStore, Node


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
