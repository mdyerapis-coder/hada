"""Tests for the family tasks module (offline, no LLM/network)."""

import time

from hermes_ctl.intelligence.family_tasks import (
    FamilyTask,
    FamilyTaskSnapshot,
    add_task,
    complete_task,
    deliver_family_tasks,
    remove_task,
    scan_family_tasks,
    update_task,
)
from hermes_ctl.memory.store import MemoryStore


def _store() -> MemoryStore:
    return MemoryStore()


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_family_task_defaults():
    t = FamilyTask()
    assert t.id == ""
    assert t.title == ""
    assert t.description == ""
    assert t.assigned_to == ""
    assert t.category == "other"
    assert t.priority == 3
    assert t.due_date == 0
    assert t.recurrence == "none"
    assert t.completed is False
    assert t.completed_at == 0.0
    assert t.tags == []


def test_family_task_to_dict_roundtrip():
    t = FamilyTask(
        id="fam_task:1000:1",
        title="Take out trash",
        description="Kitchen and bathroom bins",
        assigned_to="Mason",
        category="chore",
        priority=2,
        due_date=2000000000,
        recurrence="weekly",
        completed=False,
        tags=["kitchen", "weekly"],
    )
    d = t.to_dict()
    assert d["title"] == "Take out trash"
    assert d["assignedTo"] == "Mason"
    assert d["category"] == "chore"
    assert d["priority"] == 2
    assert d["recurrence"] == "weekly"
    assert d["dueDate"] == 2000000000
    assert "kitchen" in d["tags"]

    t2 = FamilyTask.from_dict(d)
    assert t2.title == "Take out trash"
    assert t2.assigned_to == "Mason"
    assert t2.priority == 2


def test_family_task_from_dict_empty():
    t = FamilyTask.from_dict({})
    assert t.title == ""
    assert t.category == "other"
    assert t.priority == 3
    assert t.completed is False


def test_snapshot_defaults():
    s = FamilyTaskSnapshot()
    assert s.total_count == 0
    assert s.by_category == {}
    assert s.by_assignee == {}
    assert s.overdue_count == 0
    assert s.due_today_count == 0
    assert s.completion_rate == 0.0


def test_snapshot_to_dict_roundtrip():
    t = FamilyTask(title="Clean garage", category="chore")
    s = FamilyTaskSnapshot(
        tasks=[t],
        total_count=1,
        by_category={"chore": 1},
        by_assignee={"Mason": 1},
        overdue_count=0,
        due_today_count=0,
        completion_rate=0.0,
        timestamp="2026-07-29T00:00:00Z",
    )
    d = s.to_dict()
    s2 = FamilyTaskSnapshot.from_dict(d)
    assert s2.total_count == 1
    assert s2.by_category["chore"] == 1
    assert s2.by_assignee["Mason"] == 1
    assert len(s2.tasks) == 1


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_family_tasks(store=None)
    assert snap.total_count == 0


def test_scan_empty_store():
    store = _store()
    snap = scan_family_tasks(store=store)
    assert snap.total_count == 0


def test_scan_with_tasks():
    store = _store()
    t1 = add_task(store, "Take out trash", category="chore", assigned_to="Mason")
    t2 = add_task(store, "Doctor appointment", category="appointment", assigned_to="Courtney")
    snap = scan_family_tasks(store=store)
    assert snap.total_count == 2
    assert snap.by_category.get("chore", 0) == 1
    assert snap.by_category.get("appointment", 0) == 1


# ---------------------------------------------------------------------------
# Add task tests
# ---------------------------------------------------------------------------

def test_add_task():
    store = _store()
    t = add_task(store, "Take out trash", category="chore", assigned_to="Mason", priority=2)
    assert t.title == "Take out trash"
    assert t.category == "chore"
    assert t.assigned_to == "Mason"
    assert t.priority == 2
    assert t.id.startswith("fam_task:")

    snap = scan_family_tasks(store=store)
    assert snap.total_count == 1


def test_add_task_with_all_fields():
    store = _store()
    t = add_task(
        store,
        "Weekly groceries",
        description="Get produce and dairy",
        assigned_to="Courtney",
        category="errand",
        priority=4,
        due_date=2000000000,
        recurrence="weekly",
        tags=["groceries", "weekly"],
    )
    assert t.description == "Get produce and dairy"
    assert t.recurrence == "weekly"
    assert t.due_date == 2000000000
    assert "groceries" in t.tags
    assert t.id.startswith("fam_task:")


def test_add_task_invalid_priority_clamped():
    store = _store()
    t_low = add_task(store, "Low priority", priority=0)  # below 1
    assert t_low.priority == 1  # clamped to 1
    t_high = add_task(store, "High priority", priority=10)  # above 5
    assert t_high.priority == 5  # clamped to 5


# ---------------------------------------------------------------------------
# Complete task tests
# ---------------------------------------------------------------------------


def test_complete_task():
    store = _store()
    t = add_task(store, "Fix leaky faucet", category="chore")
    completed = complete_task(store, t.id)
    assert completed is not None
    assert completed.completed is True
    assert completed.completed_at > 0

    snap = scan_family_tasks(store=store)
    assert snap.tasks[0].completed is True


def test_complete_nonexistent():
    store = _store()
    result = complete_task(store, "fam_task:nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# Update task tests
# ---------------------------------------------------------------------------


def test_update_task():
    store = _store()
    t = add_task(store, "Clean kitchen", category="chore", assigned_to="Mason", priority=2)
    updated = update_task(store, t.id, title="Clean entire kitchen", priority=4, assigned_to="Courtney")
    assert updated is not None
    assert updated.title == "Clean entire kitchen"
    assert updated.priority == 4
    assert updated.assigned_to == "Courtney"

    snap = scan_family_tasks(store=store)
    assert snap.total_count == 1
    assert snap.tasks[0].title == "Clean entire kitchen"


def test_update_nonexistent():
    store = _store()
    result = update_task(store, "fam_task:nonexistent", title="Nope")
    assert result is None


# ---------------------------------------------------------------------------
# Remove task tests
# ---------------------------------------------------------------------------


def test_remove_task():
    store = _store()
    t = add_task(store, "Old task", category="other")
    assert remove_task(store, t.id) is True
    snap = scan_family_tasks(store=store)
    assert snap.total_count == 0


def test_remove_nonexistent():
    store = _store()
    assert remove_task(store, "fam_task:nonexistent") is False


# ---------------------------------------------------------------------------
# Scan filter tests
# ---------------------------------------------------------------------------


def test_scan_filter_by_category():
    store = _store()
    add_task(store, "Wash dishes", category="chore")
    add_task(store, "Grocery run", category="errand")
    add_task(store, "Dentist", category="appointment")

    snap = scan_family_tasks(store=store, category="chore")
    assert snap.total_count == 1
    assert snap.tasks[0].title == "Wash dishes"

    snap2 = scan_family_tasks(store=store, category="errand")
    assert snap2.total_count == 1
    assert snap2.tasks[0].title == "Grocery run"


def test_scan_filter_by_assignee():
    store = _store()
    add_task(store, "Task A", assigned_to="Mason")
    add_task(store, "Task B", assigned_to="Courtney")
    add_task(store, "Task C", assigned_to="Mason")

    snap = scan_family_tasks(store=store, assignee="Mason")
    assert snap.total_count == 2

    snap2 = scan_family_tasks(store=store, assignee="Courtney")
    assert snap2.total_count == 1


# ---------------------------------------------------------------------------
# Overdue / due-today tests
# ---------------------------------------------------------------------------


def test_overdue_count():
    store = _store()
    past = int(time.time()) - 86400 * 3  # 3 days ago
    future = int(time.time()) + 86400 * 7  # 7 days from now
    add_task(store, "Past due task", due_date=past)
    add_task(store, "Future task", due_date=future)
    add_task(store, "No due date")

    snap = scan_family_tasks(store=store)
    assert snap.overdue_count == 1


def test_due_today_count():
    store = _store()
    today_ts = int(time.time())
    # Align to start of day for reliable comparison
    now = time.gmtime()
    today_start = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0)))
    add_task(store, "Due today task", due_date=today_start + 3600)  # 1 hour into today
    add_task(store, "Due tomorrow", due_date=today_start + 86400 * 2)
    add_task(store, "No due date")

    snap = scan_family_tasks(store=store)
    assert snap.due_today_count == 1


# ---------------------------------------------------------------------------
# Snapshot count tests
# ---------------------------------------------------------------------------


def test_snapshot_counts():
    store = _store()
    add_task(store, "Chore A", category="chore", assigned_to="Mason")
    add_task(store, "Chore B", category="chore", assigned_to="Courtney")
    add_task(store, "Errand A", category="errand", assigned_to="Mason")
    add_task(store, "Appointment A", category="appointment", assigned_to="Courtney")

    snap = scan_family_tasks(store=store)
    assert snap.total_count == 4
    assert snap.by_category["chore"] == 2
    assert snap.by_category["errand"] == 1
    assert snap.by_category["appointment"] == 1
    assert snap.by_assignee["Mason"] == 2
    assert snap.by_assignee["Courtney"] == 2
    assert snap.completion_rate == 0.0  # none completed


def test_snapshot_completion_rate():
    store = _store()
    add_task(store, "Task A", category="chore")
    add_task(store, "Task B", category="chore")
    t = add_task(store, "Task C", category="chore")
    add_task(store, "Task D", category="chore")
    complete_task(store, t.id)

    snap = scan_family_tasks(store=store)
    assert snap.total_count == 4
    assert snap.completion_rate == 0.25  # 1/4


# ---------------------------------------------------------------------------
# Deliver snapshot tests
# ---------------------------------------------------------------------------


def test_deliver_snapshot():
    store = _store()
    add_task(store, "Task A", category="chore")
    add_task(store, "Task B", category="errand")
    snap = scan_family_tasks(store=store)

    result = deliver_family_tasks(store, snap)
    assert result == "memory"

    # Verify snapshot persisted
    facts = store.search(tag="family_task_snapshot")
    assert len(facts) >= 1
    assert "tasks" in facts[-1].value
    assert facts[-1].value["totalCount"] == 2


def test_deliver_snapshot_no_store():
    snap = FamilyTaskSnapshot()
    result = deliver_family_tasks(None, snap)
    assert result == "memory"


# ---------------------------------------------------------------------------
# CLI smoke (import + parse only, no subprocess)
# ---------------------------------------------------------------------------


def test_cli_parser_has_family_task():
    """Verify the family-task subcommand is registered in the CLI parser."""
    from hermes_ctl.cli import build_parser
    parser = build_parser()
    for action in parser._actions:
        if action.dest == "cmd":
            choices = action.choices or {}
            assert "family-task" in choices, "family-task command not registered"
            return
    assert False, "cmd subparser not found"
