"""Unit tests for the Hermes CTL Productivity layer (Phase 2, Cycle 9)."""

import time

from hermes_ctl.memory.store import MemoryStore
from hermes_ctl.productivity.store import (
    Entity,
    Event,
    Note,
    ProductivityStore,
    Task,
)


def test_tasks_add_list_complete():
    ps = ProductivityStore(MemoryStore())
    ps.add_task(Task(id="t1", title="ship B0", priority=1))
    ps.add_task(Task(id="t2", title="write docs", priority=2))
    open_tasks = ps.list_tasks(only_open=True)
    assert len(open_tasks) == 2
    assert open_tasks[0].id == "t1"  # sorted by priority
    ps.complete_task("t1")
    assert len(ps.list_tasks(only_open=True)) == 1
    done = [t for t in ps.list_tasks() if t.done]
    assert done[0].id == "t1"


def test_notes_search_by_tag():
    ps = ProductivityStore(MemoryStore())
    ps.add_note(Note(id="n1", title="Roadmap", body="Phase 2", tags=["planning"]))
    ps.add_note(Note(id="n2", title="Groceries", body="milk", tags=["home"]))
    hits = ps.search_notes(tag="planning")
    assert len(hits) == 1 and hits[0].title == "Roadmap"


def test_calendar_upcoming_window():
    now = time.time()
    ps = ProductivityStore(MemoryStore())
    ps.add_event(Event(id="e1", title="standup", start=now - 10, end=now - 5))
    ps.add_event(Event(id="e2", title="review", start=now + 100, end=now + 200))
    ps.add_event(Event(id="e3", title="far", start=now + 10_000, end=now + 10_100))
    up = ps.upcoming_events(now=now, within=1000)
    ids = {e.id for e in up}
    assert ids == {"e2"}  # e1 ended, e3 outside window


def test_crm_find_entity():
    ps = ProductivityStore(MemoryStore())
    ps.add_entity(Entity(id="c1", name="Courtney", kind="person", fields={"relation": "partner"}))
    found = ps.find_entity("courtney")
    assert found is not None and found.kind == "person"
    assert ps.find_entity("ghost") is None


def test_productivity_persists():
    store = MemoryStore(persist_path=__import__("tempfile").mkdtemp() + "/mem.json")
    ps1 = ProductivityStore(store)
    ps1.add_task(Task(id="t1", title="x"))
    ps2 = ProductivityStore(store)
    assert any(t.id == "t1" for t in ps2.list_tasks())
