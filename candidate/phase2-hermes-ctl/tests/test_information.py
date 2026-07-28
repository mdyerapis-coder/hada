"""Unit tests for the Hermes CTL Information layer (Phase 2, Cycle 10)."""

import tempfile

from hermes_ctl.information.index import FileIndex, KnowledgeBase, SearchIndex
from hermes_ctl.memory.store import MemoryStore


def test_file_index_hashes_and_stores():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"hello hermes")
        path = f.name
    fi = FileIndex(MemoryStore())
    rec = fi.index_file(path)
    assert rec.size == len(b"hello hermes")
    assert len(rec.sha256) == 64
    got = fi.get(path)
    assert got is not None and got.sha256 == rec.sha256
    assert len(fi.all()) == 1
    import os

    os.unlink(path)


def test_search_index_and_query():
    si = SearchIndex(MemoryStore())
    si.index("n1", "Hermes CTL roadmap phase two")
    si.index("n2", "phase two productivity tasks")
    assert si.search("phase") == ["n1", "n2"]  # both
    assert si.search("productivity") == ["n2"]  # only n2
    assert si.search("roadmap productivity") == []  # AND of terms -> none


def test_knowledge_base_links():
    store = MemoryStore()
    kb = KnowledgeBase(store)
    kb.add_fact_node("mason", "person")
    kb.add_fact_node("janni", "person")
    kb.link("mason", "parent_of", "janni")
    rels = kb.related("mason", relation="parent_of")
    assert len(rels) == 1 and rels[0].target == "janni"


def test_information_persists():
    d = tempfile.mkdtemp()
    p = d + "/mem.json"
    si1 = SearchIndex(MemoryStore(persist_path=p))
    si1.index("d1", "persisted search term")
    si2 = SearchIndex(MemoryStore(persist_path=p))
    assert si2.search("persisted") == ["d1"]
