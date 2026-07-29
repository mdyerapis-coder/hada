"""Tests for the calendar module (offline, no LLM/network)."""

import time

from hermes_ctl.intelligence.calendar import (
    CalendarEvent,
    CalendarSnapshot,
    add_event,
    complete_event,
    deliver_calendar,
    remove_event,
    scan_events,
    update_event,
)
from hermes_ctl.memory.store import MemoryStore


def _store() -> MemoryStore:
    return MemoryStore()


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_calendar_event_defaults():
    e = CalendarEvent()
    assert e.id == ""
    assert e.title == ""
    assert e.description == ""
    assert e.start_time == 0
    assert e.end_time == 0
    assert e.all_day is False
    assert e.location == ""
    assert e.category == "other"
    assert e.recurrence == "none"
    assert e.completed is False
    assert e.completed_at == 0.0
    assert e.tags == []


def test_calendar_event_to_dict_roundtrip():
    e = CalendarEvent(
        id="cal_event:1000:1",
        title="Team standup",
        description="Daily sync meeting",
        start_time=1700000000,
        end_time=1700003600,
        all_day=False,
        location="Meeting Room A",
        category="meeting",
        recurrence="daily",
        completed=False,
        tags=["work", "daily"],
    )
    d = e.to_dict()
    assert d["title"] == "Team standup"
    assert d["startTime"] == 1700000000
    assert d["endTime"] == 1700003600
    assert d["category"] == "meeting"
    assert d["recurrence"] == "daily"
    assert d["location"] == "Meeting Room A"
    assert "work" in d["tags"]

    e2 = CalendarEvent.from_dict(d)
    assert e2.title == "Team standup"
    assert e2.start_time == 1700000000
    assert e2.category == "meeting"


def test_calendar_event_from_dict_empty():
    e = CalendarEvent.from_dict({})
    assert e.title == ""
    assert e.category == "other"
    assert e.completed is False
    assert e.all_day is False


def test_snapshot_defaults():
    s = CalendarSnapshot()
    assert s.total_count == 0
    assert s.by_category == {}
    assert s.upcoming_count == 0
    assert s.today_count == 0
    assert s.missed_count == 0
    assert s.completion_rate == 0.0


def test_snapshot_to_dict_roundtrip():
    e = CalendarEvent(title="Standup", category="meeting")
    s = CalendarSnapshot(
        events=[e],
        total_count=1,
        by_category={"meeting": 1},
        upcoming_count=1,
        today_count=0,
        missed_count=0,
        completion_rate=0.0,
        timestamp="2026-07-29T00:00:00Z",
    )
    d = s.to_dict()
    s2 = CalendarSnapshot.from_dict(d)
    assert s2.total_count == 1
    assert s2.by_category["meeting"] == 1
    assert s2.upcoming_count == 1
    assert len(s2.events) == 1


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_events(store=None)
    assert snap.total_count == 0


def test_scan_empty_store():
    store = _store()
    snap = scan_events(store=store)
    assert snap.total_count == 0


def test_scan_with_events():
    store = _store()
    e1 = add_event(store, "Team standup", category="meeting")
    e2 = add_event(store, "Doctor appointment", category="appointment")
    snap = scan_events(store=store)
    assert snap.total_count == 2
    assert snap.by_category.get("meeting", 0) >= 1
    assert snap.by_category.get("appointment", 0) >= 1


# ---------------------------------------------------------------------------
# Add event tests
# ---------------------------------------------------------------------------


def test_add_event():
    store = _store()
    e = add_event(
        store, "Team standup", category="meeting",
        start_time=1700000000, end_time=1700003600,
        location="Room 3",
    )
    assert e.title == "Team standup"
    assert e.category == "meeting"
    assert e.start_time == 1700000000
    assert e.end_time == 1700003600
    assert e.location == "Room 3"
    assert e.id.startswith("cal_event:")

    snap = scan_events(store=store)
    assert snap.total_count == 1
    assert "Team standup" in [ev.title for ev in snap.events]


def test_add_event_with_all_fields():
    store = _store()
    e = add_event(
        store,
        "Birthday party",
        description="Bring cake",
        start_time=1700100000,
        end_time=1700107200,
        all_day=False,
        location="Home",
        category="social",
        recurrence="yearly",
        tags=["birthday", "family"],
    )
    assert e.description == "Bring cake"
    assert e.all_day is False
    assert e.recurrence == "yearly"
    assert "birthday" in e.tags
    assert e.id.startswith("cal_event:")


def test_add_event_default_end_time():
    """If end_time is 0 or negative, it's set to start_time."""
    store = _store()
    e = add_event(store, "Brief event", start_time=1700000000)
    assert e.end_time == 1700000000


# ---------------------------------------------------------------------------
# Complete event tests
# ---------------------------------------------------------------------------


def test_complete_event():
    store = _store()
    e = add_event(store, "Dentist appointment", category="appointment")
    completed = complete_event(store, e.id)
    assert completed is not None
    assert completed.completed is True
    assert completed.completed_at > 0

    snap = scan_events(store=store)
    assert snap.events[0].completed is True


def test_complete_nonexistent():
    store = _store()
    result = complete_event(store, "cal_event:nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# Update event tests
# ---------------------------------------------------------------------------


def test_update_event():
    store = _store()
    e = add_event(store, "Team standup", category="meeting", start_time=1700000000)
    updated = update_event(
        store, e.id,
        title="Daily standup",
        location="Zoom",
        category="work",
    )
    assert updated is not None
    assert updated.title == "Daily standup"
    assert updated.location == "Zoom"
    assert updated.category == "work"

    snap = scan_events(store=store)
    assert snap.total_count == 1
    assert snap.events[0].title == "Daily standup"


def test_update_nonexistent():
    store = _store()
    result = update_event(store, "cal_event:nonexistent", title="Nope")
    assert result is None


# ---------------------------------------------------------------------------
# Remove event tests
# ---------------------------------------------------------------------------


def test_remove_event():
    store = _store()
    e = add_event(store, "Old event", category="other")
    assert remove_event(store, e.id) is True
    snap = scan_events(store=store)
    assert snap.total_count == 0


def test_remove_nonexistent():
    store = _store()
    assert remove_event(store, "cal_event:nonexistent") is False


# ---------------------------------------------------------------------------
# Scan filter tests
# ---------------------------------------------------------------------------


def test_scan_filter_by_category():
    store = _store()
    add_event(store, "Standup", category="meeting", start_time=1700000000)
    add_event(store, "Birthday dinner", category="social", start_time=1700100000)
    add_event(store, "Doctor", category="appointment", start_time=1700200000)

    snap = scan_events(store=store, category="meeting")
    assert snap.total_count >= 1
    titles = [e.title for e in snap.events]
    assert "Standup" in titles

    snap2 = scan_events(store=store, category="social")
    assert snap2.total_count >= 1
    assert "Birthday dinner" in [e.title for e in snap2.events]


def test_scan_upcoming_only():
    store = _store()
    future_ts = int(time.time()) + 86400 * 7
    past_ts = int(time.time()) - 86400 * 3
    add_event(store, "Future event", start_time=future_ts)
    add_event(store, "Past event", start_time=past_ts)

    snap = scan_events(store=store, upcoming_only=True)
    assert snap.total_count == 1
    assert snap.events[0].title == "Future event"
    assert snap.upcoming_count == 1


def test_scan_today_only():
    store = _store()
    now = time.gmtime()
    today_start = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0)))
    today_event_ts = today_start + 3600  # 1 hour into today
    future_ts = today_start + 86400 * 3  # 3 days from now

    add_event(store, "Today event", start_time=today_event_ts)
    add_event(store, "Future event", start_time=future_ts)

    snap = scan_events(store=store, today_only=True)
    assert snap.total_count == 1
    assert snap.events[0].title == "Today event"
    assert snap.today_count == 1


def test_scan_missed_only():
    store = _store()
    past_end = int(time.time()) - 86400 * 2
    future_end = int(time.time()) + 86400 * 2
    add_event(store, "Missed event", start_time=past_end - 3600, end_time=past_end)
    add_event(store, "Upcoming event", start_time=future_end - 3600, end_time=future_end)

    snap = scan_events(store=store, missed_only=True)
    assert snap.total_count == 1
    assert snap.events[0].title == "Missed event"
    assert snap.missed_count == 1


# ---------------------------------------------------------------------------
# Snapshot count tests
# ---------------------------------------------------------------------------


def test_snapshot_counts():
    store = _store()
    future_ts = int(time.time()) + 86400 * 7
    add_event(store, "Meeting", category="meeting", start_time=future_ts)
    add_event(store, "Social", category="social", start_time=future_ts + 3600)
    add_event(store, "Appointment", category="appointment", start_time=future_ts + 7200)

    snap = scan_events(store=store)
    assert snap.total_count == 3
    assert snap.by_category.get("meeting", 0) >= 1
    assert snap.by_category.get("social", 0) >= 1
    assert snap.by_category.get("appointment", 0) >= 1
    assert snap.completion_rate == 0.0  # none completed


def test_snapshot_completion_rate():
    store = _store()
    add_event(store, "Event A", category="meeting")
    add_event(store, "Event B", category="social")
    e = add_event(store, "Event C", category="other")
    add_event(store, "Event D", category="work")
    complete_event(store, e.id)

    snap = scan_events(store=store)
    assert snap.total_count == 4
    assert snap.completion_rate == 0.25  # 1/4


# ---------------------------------------------------------------------------
# Deliver snapshot tests
# ---------------------------------------------------------------------------


def test_deliver_snapshot():
    store = _store()
    add_event(store, "Meeting", category="meeting")
    add_event(store, "Birthday", category="social")
    snap = scan_events(store=store)

    result = deliver_calendar(store, snap)
    assert result == "memory"

    # Verify snapshot persisted
    facts = store.search(tag="calendar_snapshot")
    assert len(facts) >= 1
    assert "events" in facts[-1].value
    assert facts[-1].value["totalCount"] == 2


def test_deliver_snapshot_no_store():
    snap = CalendarSnapshot()
    result = deliver_calendar(None, snap)
    assert result == "memory"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


def test_multi_category_counts():
    store = _store()
    add_event(store, "Daily sync", category="meeting")
    add_event(store, "Catch up", category="meeting")
    add_event(store, "Sick visit", category="health")
    add_event(store, "Vacation", category="travel")

    snap = scan_events(store=store)
    assert snap.total_count == 4
    assert snap.by_category.get("meeting", 0) >= 2
    assert snap.by_category.get("health", 0) >= 1
    assert snap.by_category.get("travel", 0) >= 1


# ---------------------------------------------------------------------------
# CLI smoke (import + parse only, no subprocess)
# ---------------------------------------------------------------------------


def test_cli_parser_has_calendar():
    """Verify the calendar subcommand is registered in the CLI parser."""
    from hermes_ctl.cli import build_parser
    parser = build_parser()
    for action in parser._actions:
        if action.dest == "cmd":
            choices = action.choices or {}
            assert "calendar" in choices, "calendar command not registered"
            return
    assert False, "cmd subparser not found"
