"""Tests for the context-awareness module (offline, no network/LLM)."""

import json
import time

import pytest

from hermes_ctl.intelligence.context import (
    ContextError,
    ContextSnapshot,
    deliver_context,
    scan_context,
)
from hermes_ctl.memory.store import MemoryStore


def _make_store(tmp_path) -> MemoryStore:
    return MemoryStore(persist_path=str(tmp_path / "mem.json"))


def _seed_inbox(store: MemoryStore, count: int = 3) -> None:
    for i in range(count):
        store.remember(
            f"inbox:{i}",
            {"channel": "sms", "sender": "+61400000000", "body": f"Test message {i}", "timestamp": f"2026-07-29T0{i}:00:00Z"},
            tags={"inbox"},
        )


def test_scan_context_empty_store(tmp_path):
    """scan_context with no data returns safe defaults."""
    store = _make_store(tmp_path)
    ctx = scan_context(store=store)
    assert ctx.inbox_count == 0
    assert ctx.recent_inbox == []
    assert ctx.open_tasks == []
    assert ctx.current_plan is None
    assert ctx.latest_briefing is None
    assert ctx.date == time.strftime("%Y-%m-%d", time.gmtime())
    assert ctx.timestamp  # non-empty


def test_scan_context_with_inbox(tmp_path):
    """scan_context collects inbox items."""
    store = _make_store(tmp_path)
    _seed_inbox(store, 5)
    ctx = scan_context(store=store)
    assert ctx.inbox_count == 5
    assert len(ctx.recent_inbox) == 5
    # most recent first
    assert ctx.recent_inbox[0]["body"] == "Test message 4"


def test_scan_context_inbox_capped_at_5(tmp_path):
    """recent_inbox is capped at 5 entries."""
    store = _make_store(tmp_path)
    _seed_inbox(store, 20)
    ctx = scan_context(store=store)
    assert ctx.inbox_count == 20
    assert len(ctx.recent_inbox) == 5


def test_scan_context_with_plan(tmp_path):
    """scan_context loads the plan file if present."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    plan_data = {
        "date": "2026-07-29",
        "headline": "Focus day",
        "items": [{"time": "07:00", "priority": "high", "task": "Review inbox"}],
        "model": "fast",
        "generatedAt": "2026-07-29T00:00:00Z",
    }
    path = plans_dir / "plan-2026-07-29.json"
    path.write_text(json.dumps(plan_data))

    store = _make_store(tmp_path)
    ctx = scan_context(store=store, plans_dir=str(plans_dir))
    assert ctx.current_plan is not None
    assert ctx.current_plan["headline"] == "Focus day"
    assert len(ctx.current_plan["items"]) == 1


def test_scan_context_with_briefing(tmp_path):
    """scan_context loads the latest briefing file."""
    plans_dir = tmp_path / "dreams"
    plans_dir.mkdir()
    briefing_data = {
        "date": "2026-07-29",
        "model": "fast",
        "generatedAt": "2026-07-29T00:00:00Z",
        "prescriptions": [{
            "id": "MEMORY-2026-07-29",
            "cat": "MEMORY",
            "tone": "pink",
            "headline": "Archive old evidence",
            "prescription": "Move stale archives.",
            "evidence": ["a", "b", "c"],
            "command": "archive --old",
        }],
    }
    path = plans_dir / "dream-2026-07-29.json"
    path.write_text(json.dumps(briefing_data))

    store = _make_store(tmp_path)
    ctx = scan_context(store=store, plans_dir=str(plans_dir))
    assert ctx.latest_briefing is not None
    assert len(ctx.latest_briefing["prescriptions"]) == 1
    assert ctx.latest_briefing["prescriptions"][0]["cat"] == "MEMORY"


def test_context_to_dict_roundtrip():
    """ContextSnapshot to_dict/from_dict preserves all fields."""
    ctx = ContextSnapshot(
        timestamp="2026-07-29T00:00:00Z",
        date="2026-07-29",
        inbox_count=3,
        recent_inbox=[{"channel": "sms", "body": "hi"}],
        open_tasks=[{"id": "abc", "title": "Do X"}],
        current_plan={"headline": "Day"},
        latest_briefing={"prescriptions": []},
        user_profile={"name": "Mason"},
        context_facts=[{"id": "ctx:1", "value": {"k": "v"}}],
    )
    d = ctx.to_dict()
    # check camelCase keys
    assert d["inboxCount"] == 3
    assert d["currentPlan"]["headline"] == "Day"

    restored = ContextSnapshot.from_dict(d)
    assert restored.date == "2026-07-29"
    assert restored.inbox_count == 3
    assert restored.current_plan["headline"] == "Day"
    assert restored.user_profile["name"] == "Mason"


def test_context_from_dict_safe_defaults():
    """from_dict with empty dict returns safe defaults."""
    ctx = ContextSnapshot.from_dict({})
    assert ctx.timestamp == ""
    assert ctx.inbox_count == 0
    assert ctx.recent_inbox == []
    assert ctx.current_plan is None


def test_deliver_context_persists(tmp_path):
    """deliver_context writes to MemoryStore and returns 'memory'."""
    store = _make_store(tmp_path)
    ctx = scan_context(store=store)
    result = deliver_context(ctx, store=store)
    assert result == "memory"

    facts = store.search(tag="context")
    assert len(facts) >= 1
    # validate structure
    d = facts[-1].value
    assert "inboxCount" in d
    assert "currentPlan" in d


def test_deliver_context_no_store(tmp_path):
    """deliver_context without a store still completes (no crash)."""
    ctx = ContextSnapshot(date="2026-07-29", timestamp="now")
    result = deliver_context(ctx)
    assert result == "memory"


def test_deliver_context_tagged_correctly(tmp_path):
    """delivery tags the fact with 'context' and 'snapshot'."""
    store = _make_store(tmp_path)
    ctx = ContextSnapshot(date="2026-07-29", timestamp="now")
    deliver_context(ctx, store=store)
    facts = store.search(tag="snapshot")
    assert len(facts) >= 1
    # also retrievable via 'context' tag
    facts2 = store.search(tag="context")
    assert len(facts2) >= 1


def test_scan_context_missing_plans_dir_is_ok(tmp_path):
    """Missing plans_dir does not crash — returns None for plan/briefing."""
    store = _make_store(tmp_path)
    ctx = scan_context(store=store, plans_dir="/nonexistent/path")
    assert ctx.current_plan is None
    assert ctx.latest_briefing is None


def test_scan_context_corrupt_plan_file(tmp_path):
    """Corrupt plan JSON does not crash — returns None."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    (plans_dir / "plan-2026-07-29.json").write_text("not json at all")

    store = _make_store(tmp_path)
    ctx = scan_context(store=store, plans_dir=str(plans_dir))
    assert ctx.current_plan is None


def test_scan_context_with_open_tasks(tmp_path):
    """scan_context collects open tasks from ProductivityStore."""
    store = _make_store(tmp_path)
    from hermes_ctl.productivity.store import ProductivityStore, Task

    ps = ProductivityStore(store)
    import uuid
    t1 = Task(id=uuid.uuid4().hex[:8], title="Review PR")
    t2 = Task(id=uuid.uuid4().hex[:8], title="Write tests")
    ps.add_task(t1)
    ps.add_task(t2)

    ctx = scan_context(store=store)
    task_titles = [t["title"] for t in ctx.open_tasks]
    assert "Review PR" in task_titles
    assert "Write tests" in task_titles
