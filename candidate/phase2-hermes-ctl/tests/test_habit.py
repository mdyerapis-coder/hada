"""Tests for the habit tracking module (offline, no LLM/network)."""

import time

import pytest

from hermes_ctl.intelligence.habit import (
    Habit,
    HabitError,
    HabitLog,
    HabitSnapshot,
    add_habit,
    log_habit,
    scan_habits,
    VALID_FREQUENCIES,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_habit_defaults():
    h = Habit()
    assert h.name == ""
    assert h.frequency == "daily"
    assert h.category == "health"
    assert h.active is True
    assert h.streak == 0


def test_habit_to_dict_roundtrip():
    h = Habit(name="meditate", category="mindfulness", frequency="daily", target_per_day=1, streak=5)
    d = h.to_dict()
    assert d["name"] == "meditate"
    assert d["category"] == "mindfulness"
    assert d["streak"] == 5

    h2 = Habit.from_dict(d)
    assert h2.name == "meditate"
    assert h2.streak == 5


def test_habit_from_dict_empty():
    h = Habit.from_dict({})
    assert h.name == ""
    assert h.frequency == "daily"
    assert h.active is True


def test_habit_log_roundtrip():
    l = HabitLog(date="2026-07-29", notes="Done!")
    d = l.to_dict()
    l2 = HabitLog.from_dict(d)
    assert l2.date == "2026-07-29"
    assert l2.notes == "Done!"


def test_habit_snapshot_defaults():
    s = HabitSnapshot()
    assert s.total_count == 0
    assert s.active_count == 0
    assert s.top_streaks == []


def test_snapshot_with_habits():
    h = Habit(name="read", streak=10)
    s = HabitSnapshot(habits=[h], total_count=1, active_count=1, top_streaks=[h])
    d = s.to_dict()
    s2 = HabitSnapshot.from_dict(d)
    assert s2.total_count == 1


def test_valid_frequencies():
    assert "daily" in VALID_FREQUENCIES
    assert "weekly" in VALID_FREQUENCIES
    assert len(VALID_FREQUENCIES) == 5


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_habits(store=None)
    assert snap.total_count == 0


def test_scan_empty_store(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    snap = scan_habits(store=store)
    assert snap.total_count == 0


def test_scan_with_habits(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate", category="mindfulness")
    add_habit(store, "read", category="learning")
    snap = scan_habits(store=store)
    assert snap.total_count == 2
    assert snap.active_count == 2
    assert "mindfulness" in snap.by_category
    assert "learning" in snap.by_category


def test_scan_filter_by_category(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate", category="mindfulness")
    add_habit(store, "read", category="learning")
    snap = scan_habits(store=store, category="learning")
    assert snap.total_count == 1
    assert snap.habits[0].name == "read"


def test_scan_active_only(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    h = add_habit(store, "meditate")
    h.active = False
    store.remember("habit:meditate", h.to_dict(), tags={"habit"})
    add_habit(store, "read")
    snap = scan_habits(store=store, active_only=True)
    assert snap.total_count == 1
    assert snap.habits[0].name == "read"


def test_scan_due_today(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    h = add_habit(store, "meditate")
    h.last_done = time.strftime("%Y-%m-%d")
    h.active = True
    store.remember("habit:meditate", h.to_dict(), tags={"habit"})
    add_habit(store, "exercise")
    snap = scan_habits(store=store, due_today=True)
    assert len(snap.due_today) == 1
    assert snap.due_today[0].name == "exercise"


# ---------------------------------------------------------------------------
# Add habit tests
# ---------------------------------------------------------------------------


def test_add_habit_creates(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    habit = add_habit(store, "exercise", category="health", frequency="daily")
    assert habit.name == "exercise"
    assert habit.id == "exercise"
    assert habit.frequency == "daily"
    snap = scan_habits(store=store)
    assert snap.total_count == 1


def test_add_habit_raises_on_empty_name(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(HabitError, match="habit name is required"):
        add_habit(store, "")


def test_add_habit_invalid_frequency(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(HabitError, match="invalid frequency"):
        add_habit(store, "test", frequency="bogus")


def test_add_habit_with_notes(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    habit = add_habit(store, "read", category="learning", target_per_day=20, unit="pages", notes="read before bed")
    assert habit.target_per_day == 20
    assert "bed" in habit.notes


# ---------------------------------------------------------------------------
# Log habit tests
# ---------------------------------------------------------------------------


def test_log_habit_increases_streak(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate")
    h1 = log_habit(store, "meditate", date="2026-07-28")
    assert h1.streak == 1
    h2 = log_habit(store, "meditate", date="2026-07-29")
    assert h2.streak == 2


def test_log_habit_resets_streak_on_gap(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate")
    log_habit(store, "meditate", date="2026-07-25")
    h = log_habit(store, "meditate", date="2026-07-29")
    assert h.streak == 1  # reset (gap > 1 day)


def test_log_habit_increments_total(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate")
    log_habit(store, "meditate", date="2026-07-28")
    log_habit(store, "meditate", date="2026-07-29")
    log_habit(store, "meditate", date="2026-07-30")
    snap = scan_habits(store=store)
    assert snap.habits[0].total_count == 3


def test_log_habit_nonexistent(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    h = log_habit(store, "nonexistent")
    assert h is None


def test_log_habit_idempotent(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate")
    log_habit(store, "meditate", date="2026-07-29")
    h = log_habit(store, "meditate", date="2026-07-29")  # same date, should be no-op
    assert h.total_count == 1  # not incremented twice


def test_log_habit_with_notes(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate")
    h = log_habit(store, "meditate", date="2026-07-29", notes="10 min session")
    assert len(h.logs) >= 1
    assert any("10 min" in l.notes for l in h.logs)


def test_log_habit_updates_best_streak(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_habit(store, "meditate")
    for d in range(1, 6):
        log_habit(store, "meditate", date=f"2026-07-0{d}")
    snap = scan_habits(store=store)
    assert snap.habits[0].best_streak == 5
