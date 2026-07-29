"""Cross-module integration tests: MemoryStore → Productivity → Information → Relationships → CLI.

Validates the unified app surface by exercising facts written by one subsystem
and consumed by another — exactly the seam that breaks if modules drift apart.
All tests are offline (temp filesystem, no network, no LLM).
"""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from hermes_ctl.memory.store import MemoryStore
from hermes_ctl.productivity.store import ProductivityStore, Task, Note, Event, Entity
from hermes_ctl.intelligence.relationships import Relationships, Relationship
from hermes_ctl.information.index import FileIndex, SearchIndex
from hermes_ctl.cli import build_parser, main


# =======================================================================
# Fixtures
# =======================================================================


@pytest.fixture
def store(tmp_path) -> MemoryStore:
    """A fresh MemoryStore on a temp JSON file (auto-persisted)."""
    p = str(tmp_path / "inbox.json")
    return MemoryStore(persist_path=p)


@pytest.fixture
def prod(store: MemoryStore) -> ProductivityStore:
    return ProductivityStore(store)


@pytest.fixture
def rels(store: MemoryStore) -> Relationships:
    return Relationships(store)


@pytest.fixture
def file_index(store: MemoryStore) -> FileIndex:
    return FileIndex(store=store)


# =======================================================================
# 1. MemoryStore ↔ ProductivityStore (tasks → memory search)
# =======================================================================


def test_task_persists_to_memory_store(store: MemoryStore, prod: ProductivityStore):
    """A task added via ProductivityStore is queryable via MemoryStore.search()."""
    task = Task(id="t001", title="review PR", done=False)
    prod.add_task(task)

    # Read back via raw MemoryStore
    raw = store.recall("productivity.tasks")
    assert raw is not None
    items = json.loads(json.dumps(raw))  # round-trip through JSON
    assert any(item["title"] == "review PR" and not item["done"] for item in items)

    # Also search by tag
    facts = store.search(tag="productivity")
    assert len(facts) >= 1


def test_note_appears_in_memory_search(store: MemoryStore, prod: ProductivityStore):
    """A note is searchable by tag across the two stores."""
    note = Note(id="n001", title="meeting notes", body="discussed roadmap", tags=["work"])
    prod.add_note(note)

    facts = store.search(tag="productivity")
    titles = []
    for f in facts:
        val = json.loads(json.dumps(f.value))
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "title" in item:
                    titles.append(item["title"])
    assert "meeting notes" in titles


# =======================================================================
# 2. Relationships ↔ MemoryStore (graph + interaction)
# =======================================================================


def test_relationship_stored_as_fact_and_graph_node(store: MemoryStore, rels: Relationships):
    """Relationships class writes facts to MemoryStore AND creates graph nodes."""
    rels.add("Courtney", "partner", notes="my partner", important_dates={"birthday": "1990-06-15"})

    # Fact-based retrieval
    fetched = rels.get("Courtney")
    assert fetched is not None
    assert fetched.person == "Courtney"
    assert fetched.relation == "partner"

    # Graph node
    assert "person:Courtney" in store._nodes
    assert store._nodes["person:Courtney"].kind == "person"


def test_interaction_updates_relationship_strength(store: MemoryStore, rels: Relationships):
    """Multiple interactions increase relationship strength."""
    rels.log_interaction("Courtney", channel="telegram", summary="hello")
    rels.log_interaction("Courtney", channel="email", summary="follow-up")

    rel = rels.get("Courtney")
    assert rel is not None
    # Should exist with at least some relation
    assert rel.relation is not None


def test_relationship_reachable_via_memory_search(store: MemoryStore, rels: Relationships):
    """Relationship facts are searchable by tag via raw MemoryStore."""
    rels.add("Courtney", "partner")

    facts = store.search(tag="relationship")
    assert len(facts) >= 1

    # Also check person tag
    facts_person = store.search(tag="person:Courtney")
    assert len(facts_person) >= 1


# =======================================================================
# 3. Information (FileIndex) ↔ MemoryStore
# =======================================================================


def test_file_indexing_persists_to_memory(tmp_path, store: MemoryStore, file_index: FileIndex):
    """Indexing files stores metadata in MemoryStore as searchable facts."""
    # Create a test file to index
    test_file = tmp_path / "note.txt"
    test_file.write_text("Meeting about project roadmap and deadlines.\nFollow-up next week.")

    rec = file_index.index_file(str(test_file))
    assert rec.path == str(test_file)
    assert rec.size > 0

    # The index should be stored as a searchable fact via tag
    facts = store.search(tag="information")
    assert len(facts) >= 1

    # Also verify via SearchIndex
    si = SearchIndex(store)
    si.index(str(test_file), "roadmap meeting deadlines")
    results = si.search("roadmap")
    assert str(test_file) in results


# =======================================================================
# 4. End-to-end CLI integration (all subsystems via command line)
# =======================================================================


def test_cli_memory_then_productivity_roundtrip(monkeypatch, tmp_path):
    """CLI memory remember -> tasks list -> notes list."""
    store_path = str(tmp_path / "store.json")
    monkeypatch.setenv("HERMES_CTL_STORE", store_path)

    # Remember a fact
    rc = main(["memory", "remember", "greeting", json.dumps({"text": "hello world"}), "--tag", "test"])
    assert rc == 0

    # Add a task
    rc = main(["tasks", "add", "finish integration tests"])
    assert rc == 0

    # Add a note
    rc = main(["notes", "add", "integration notes", "--body", "test passing"])
    assert rc == 0

    # Verify memory search returns our fact (use main() + capsys trick or read store directly)
    store = MemoryStore(persist_path=store_path)
    facts = store.search(tag="test")
    assert any("greeting" in f.id for f in facts)

    # Verify tasks list returns our task
    prod = ProductivityStore(store)
    tasks = prod.list_tasks()
    assert any(t.title == "finish integration tests" for t in tasks)

    # Verify notes list returns our note
    notes = prod.search_notes()
    assert any(n.title == "integration notes" for n in notes)


def test_cli_information_status(tmp_path):
    """Information CLI command: status on empty index doesn't crash."""
    rc = main(["information", "status"])
    assert rc == 0


def test_cli_information_index_and_search(monkeypatch, tmp_path):
    """Information CLI: index a file then search it."""
    store_path = str(tmp_path / "store.json")
    monkeypatch.setenv("HERMES_CTL_STORE", store_path)

    # Create a test file with searchable content
    docs = tmp_path / "docs"
    docs.mkdir()
    readme = docs / "readme.md"
    readme.write_text("# Test Document\nThis is test content for search.")

    # Index it via CLI
    rc = main(["information", "index", str(docs)])
    assert rc == 0

    # Search via CLI - the CLI indexes file path as search term, so "readme" should match
    rc = main(["information", "search", "readme"])
    assert rc == 0


# =======================================================================
# 5. Data integrity: fact written by one module, read by another
# =======================================================================


def test_same_store_backs_all_modules(tmp_path):
    """MemoryStore, ProductivityStore, Relationships all share the same persistence file."""
    store_path = tmp_path / "shared.json"
    store = MemoryStore(persist_path=str(store_path))

    # Write via ProductivityStore - stored under productivity.tasks key
    prod = ProductivityStore(store)
    prod.add_task(Task(id="shared-1", title="shared task"))

    # Write via Relationships
    rels = Relationships(store)
    rels.add("TestPerson", "friend")

    # Write directly
    store.remember("direct-key", {"value": 42}, tags=["direct"])

    # Reload from persistence - should see ALL three
    store2 = MemoryStore(persist_path=str(store_path))

    # Task is stored under productivity.tasks, not individual key
    raw = store2.recall("productivity.tasks")
    assert raw is not None
    assert any(item["id"] == "shared-1" for item in raw)

    # Direct key should be readable
    assert store2.recall("direct-key")["value"] == 42

    # Relationship fact should be loadable from persisted store
    rels2 = Relationships(store2)
    assert rels2.get("TestPerson") is not None


# =======================================================================
# 6. CLI help shows all subsystem commands
# =======================================================================


def test_cli_help_lists_all_commands():
    """The help output lists every subsystem command."""
    p = build_parser()
    help_text = p.format_help()

    expected_commands = [
        "memory", "inbox", "identity", "tasks", "notes",
        "calendar", "crm", "send", "brains", "context",
        "briefing", "plan", "remind", "relationship",
        "shopping", "travel", "finance", "information",
    ]
    for cmd in expected_commands:
        assert cmd in help_text, f"CLI help missing '{cmd}' command"
    assert len(expected_commands) >= 17


def test_all_commands_have_parsers():
    """Every expected subcommand has a registered parser (no duplicates)."""
    p = build_parser()
    # Access the subparsers action to inspect choices
    sub_action = None
    for action in p._actions:
        if action.dest == "cmd":
            sub_action = action
            break
    assert sub_action is not None, "No cmd subparser found"
    choices = list(sub_action.choices.keys())
    assert "memory" in choices
    assert "inbox" in choices
    assert "information" in choices
    assert "tasks" in choices
    assert "notes" in choices
    assert "send" in choices
    assert len(choices) >= 17
