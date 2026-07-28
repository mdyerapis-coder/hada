"""Tests for the smart reminders module (offline, no network)."""

import json
import os
import tempfile

from hermes_ctl.intelligence.plan import Plan, PlanItem
from hermes_ctl.intelligence.remind import (
    RemindError,
    _is_pending,
    _load_plan_from_disk,
    _parse_current_time,
    run_remind,
)


def test_is_pending_time_before():
    """Item with time before current time is pending."""
    item = PlanItem("08:00", "high", "Do the thing")
    assert _is_pending(item, set(), 9, 0)


def test_is_pending_time_after():
    """Item with time after current time is not pending."""
    item = PlanItem("10:00", "high", "Future thing")
    assert not _is_pending(item, set(), 8, 0)


def test_is_pending_anytime():
    item = PlanItem("anytime", "medium", "Flex task")
    assert _is_pending(item, set(), 8, 0)


def test_is_pending_already_reminded():
    item = PlanItem("08:00", "high", "Done task")
    assert not _is_pending(item, {"Done task"}, 9, 0)


def test_load_plan_from_disk_exact(tmp_path):
    plan = Plan(date="2026-07-29", headline="Test", items=[PlanItem("09:00", "low", "test")])
    p = tmp_path / "plan-2026-07-29.json"
    with open(p, "w") as f:
        json.dump(plan.to_dict(), f)
    loaded = _load_plan_from_disk(str(tmp_path), "2026-07-29")
    assert loaded is not None
    assert loaded.headline == "Test"


def test_load_plan_from_disk_fallback(tmp_path):
    plan = Plan(date="2026-07-28", headline="Older", items=[PlanItem("09:00", "low", "t")])
    p = tmp_path / "plan-2026-07-28.json"
    with open(p, "w") as f:
        json.dump(plan.to_dict(), f)
    loaded = _load_plan_from_disk(str(tmp_path), "2099-01-01")  # no exact match
    assert loaded is not None
    assert loaded.date == "2026-07-28"


def test_load_plan_from_disk_missing(tmp_path):
    assert _load_plan_from_disk(str(tmp_path), "2099-01-01") is None


def test_run_remind_no_plan(tmp_path):
    count = run_remind(plans_dir=str(tmp_path), telegram_chat="test")
    assert count == 0  # graceful no-op


def test_run_remind_with_pending(tmp_path, monkeypatch):
    # write a plan file with items before current time
    plan = Plan(
        date="2026-07-29",
        headline="Busy day",
        items=[
            PlanItem("08:00", "high", "Inbox zero"),
            PlanItem("10:00", "medium", "Deep work block"),
        ],
    )
    with open(os.path.join(tmp_path, "plan-2026-07-29.json"), "w") as f:
        json.dump(plan.to_dict(), f)

    # monkeypatch _parse_current_time to return 09:00 (so 08:00 is pending, 10:00 is not)
    monkeypatch.setattr("hermes_ctl.intelligence.remind._parse_current_time", lambda: (9, 0))

    # Monkeypatch TelegramChannel.send to be a no-op that tracks deliveries
    sent = []

    class FakeTG:
        def send(self, msg):
            sent.append(msg)

    monkeypatch.setattr("hermes_ctl.communications.telegram.TelegramChannel", lambda: FakeTG())

    count = run_remind(plans_dir=str(tmp_path), telegram_chat="test", store=None)
    assert count == 1  # only 1 pending (08:00)
    assert len(sent) == 1
    assert "Inbox zero" in sent[0].body


def test_run_remind_skip_reminded(tmp_path, monkeypatch):
    # plan with 2 items, one already reminded
    class FakeStore:
        def __init__(self):
            self._data = {}

        def search(self, tag="", **kw):
            return []

        def remember(self, key, value, tags=None, **kw):
            self._data[key] = value

    store = FakeStore()

    plan = Plan(
        date="2026-07-29",
        headline="Day",
        items=[PlanItem("08:00", "high", "Remind this"), PlanItem("08:00", "medium", "Already reminded")],
    )
    with open(os.path.join(tmp_path, "plan-2026-07-29.json"), "w") as f:
        json.dump(plan.to_dict(), f)

    monkeypatch.setattr("hermes_ctl.intelligence.remind._parse_current_time", lambda: (9, 0))

    # Pre-mark one as reminded via store
    from hermes_ctl.intelligence.remind import REMIND_TAG
    store.remember(f"reminded:Already reminded", {"task": "Already reminded", "time": "08:00 UTC"}, tags={REMIND_TAG})

    # Make search return the reminded item
    from hermes_ctl.memory.store import Fact
    original_search = store.search
    def mock_search(tag="", **kw):
        if tag == REMIND_TAG:
            return [Fact(id="reminded:Already reminded", value={"task": "Already reminded", "time": "08:00 UTC"}, tags={REMIND_TAG})]
        return []

    monkeypatch.setattr(store, "search", mock_search)
    monkeypatch.setattr("hermes_ctl.communications.telegram.TelegramChannel", lambda: type("FakeTG", (), {"send": lambda s, m: None})())

    count = run_remind(plans_dir=str(tmp_path), telegram_chat="test", store=store)
    assert count == 1  # only "Remind this" sent
