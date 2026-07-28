"""Tests for the daily plan module (offline, no LLM/network)."""

import json

from hermes_ctl.intelligence.plan import (
    Plan,
    PlanItem,
    PlanError,
    generate_plan,
    validate_plan,
    deliver_plan,
    run_plan,
)


def _fake_router(replies):
    class _R:
        def __init__(self, rs):
            self._rs = list(rs)
        def complete(self, role, prompt, *, max_tokens=400):
            return self._rs.pop(0)
    return _R(replies)


def test_generate_and_validate_plan():
    items = [
        PlanItem(time="07:00", priority="high", task="Review inbox"),
        PlanItem(time="09:00", priority="medium", task="Deep work block"),
    ]
    plan = generate_plan(items, date="2026-07-28", headline="Focus day")
    validate_plan(plan)
    assert plan.headline == "Focus day"
    assert len(plan.items) == 2


def test_validate_rejects_bad_priority():
    plan = Plan(date="2026-07-28", headline="x", items=[PlanItem("08:00", "urgent", "t")])
    try:
        validate_plan(plan)
        assert False, "should reject bad priority"
    except PlanError:
        pass


def test_validate_rejects_empty():
    try:
        validate_plan(Plan(date="", headline="", items=[]))
        assert False
    except PlanError:
        pass


def test_deliver_writes_file(tmp_path):
    items = [PlanItem("07:00", "high", "Inbox")]
    plan = generate_plan(items, date="2026-07-28", headline="Day")
    path = deliver_plan(plan, plans_dir=str(tmp_path))
    import glob
    f = glob.glob(str(tmp_path / "plan-*.json"))[0]
    data = json.load(open(f))
    assert data["headline"] == "Day"
    assert data["items"][0]["task"] == "Inbox"


def test_run_plan_generates_and_delivers(tmp_path):
    router = _fake_router([
        '{"headline":"Light maintenance day","items":['
        '{"time":"08:00","priority":"high","task":"Triage inbox"},'
        '{"time":"10:00","priority":"medium","task":"Plan tomorrow"}]}',
    ])
    # run_plan imports http_router lazily; we pass a router that already has .complete
    path = run_plan(
        brains=router,
        store=None,
        plans_dir=str(tmp_path),
        date="2026-07-28",
    )
    import glob
    f = glob.glob(str(tmp_path / "plan-*.json"))[0]
    data = json.load(open(f))
    assert len(data["items"]) == 2
    assert data["items"][0]["priority"] == "high"


def test_run_plan_fail_closed_on_bad_llm(tmp_path):
    router = _fake_router(["not json at all"])
    try:
        run_plan(brains=router, store=None, plans_dir=str(tmp_path), date="2026-07-28")
        assert False, "should raise on bad LLM output"
    except PlanError:
        pass
    # nothing delivered
    import glob
    assert not glob.glob(str(tmp_path / "plan-*.json"))
