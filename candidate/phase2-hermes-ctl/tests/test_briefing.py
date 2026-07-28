"""Tests for the Dream-style briefing module (offline, no LLM/network)."""

import os
import tempfile

from hermes_ctl.intelligence.briefing import (
    Briefing,
    BriefingError,
    Prescription,
    deliver_briefing,
    generate_briefing,
    scan_signals,
    validate_briefing,
)
from hermes_ctl.memory.store import MemoryStore


_TONE = {"MEMORY": "pink", "COST": "orange", "SKILLS": "blue", "WORKFLOW": "yellow"}


def _p(pid: str, cat: str = "MEMORY") -> Prescription:
    return Prescription(
        id=pid,
        cat=cat,
        tone=_TONE.get(cat, "pink"),  # invalid cat -> tone still set; validation rejects cat
        headline="Headline under 120 chars for " + pid,
        prescription="Concrete next step for " + pid + ".",
        evidence=["evidence one", "evidence two", "evidence three"],
        command="hermesctl briefing run",
        dollar_impact=120,
        time_impact_mins=60,
    )


def test_valid_briefing_passes():
    b = generate_briefing([_p("mem-a", "MEMORY"), _p("cost-a", "COST"),
                           _p("skill-a", "SKILLS"), _p("wf-a", "WORKFLOW")],
                          date="2026-07-28", model="hermes-7b")
    assert len(b.prescriptions) == 4
    # round-trips through JSON
    again = Briefing.from_dict(b.to_dict())
    assert len(again.prescriptions) == 4


def test_too_many_prescriptions_rejected():
    with __import__("pytest").raises(BriefingError):
        generate_briefing([_p(f"x{i}", "MEMORY") for i in range(5)],
                          date="2026-07-28", model="m")


def test_wrong_tone_for_cat_rejected():
    bad = _p("mem-b", "MEMORY")
    bad.tone = "orange"  # wrong for MEMORY
    with __import__("pytest").raises(BriefingError):
        generate_briefing([bad], date="2026-07-28", model="m")


def test_bad_category_rejected():
    bad = _p("x", "NONSENSE")
    with __import__("pytest").raises(BriefingError):
        generate_briefing([bad], date="2026-07-28", model="m")


def test_duplicate_id_rejected():
    with __import__("pytest").raises(BriefingError):
        generate_briefing([_p("dup", "MEMORY"), _p("dup", "COST")],
                          date="2026-07-28", model="m")


def test_evidence_must_be_exactly_three():
    p = _p("mem-c")
    p.evidence = ["only one"]
    with __import__("pytest").raises(BriefingError):
        generate_briefing([p], date="2026-07-28", model="m")


def test_headline_too_long_rejected():
    p = _p("mem-d")
    p.headline = "x" * 121
    with __import__("pytest").raises(BriefingError):
        generate_briefing([p], date="2026-07-28", model="m")


def test_empty_prescriptions_rejected():
    with __import__("pytest").raises(BriefingError):
        generate_briefing([], date="2026-07-28", model="m")


def test_deliver_writes_idempotent_json(tmp_path):
    d = tmp_path / "dreams"
    b = generate_briefing([_p("mem-e", "MEMORY")], date="2026-07-28", model="m")
    p1 = deliver_briefing(b, dreams_dir=str(d))
    # re-run overwrites, does not append a second file
    p2 = deliver_briefing(b, dreams_dir=str(d))
    assert p1 == p2
    files = list(d.glob("dream-*.json"))
    assert len(files) == 1
    import json
    data = json.loads(files[0].read_text())
    assert data["date"] == "2026-07-28"
    assert len(data["prescriptions"]) == 1


def test_deliver_to_memory_store(tmp_path):
    store = MemoryStore(persist_path=str(tmp_path / "mem.json"))
    b = generate_briefing([_p("mem-f", "MEMORY")], date="2026-07-28", model="m")
    deliver_briefing(b, store=store)
    facts = store.search(tag="briefing")
    assert len(facts) == 1
    assert facts[0].value["prescriptions"][0]["id"] == "mem-f"


def test_invalid_briefing_not_delivered(tmp_path):
    store = MemoryStore(persist_path=str(tmp_path / "mem.json"))
    b = Briefing(date="2026-07-28", model="m", generated_at="now", prescriptions=[])
    with __import__("pytest").raises(BriefingError):
        deliver_briefing(b, store=store, dreams_dir=str(tmp_path / "dreams"))
    # nothing persisted
    assert store.search(tag="briefing") == []


def test_scan_signals_read_only(tmp_path):
    store = MemoryStore(persist_path=str(tmp_path / "mem.json"))
    store.remember("briefing:2026-07-27", {"x": 1}, tags={"briefing"})
    sig = scan_signals(store=store, inbox_dir=str(tmp_path))
    assert "memory_facts" in sig
    assert sig["memory_facts"]
