"""Tests for the HADA Command Centre snapshot adapter.

Covers: roadmap parsing, status mapping, fail-closed stale handling,
and snapshot-shape validation. No network; a fixture roadmap is used.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "scripts" / "control-board-snapshot.py"

spec = importlib.util.spec_from_file_location("snapshot_mod", SCRIPT)
snapshot_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_mod)

FIXTURE_ROADMAP = """\
# HADA Master Roadmap

# Phase 0 — Governance Foundation
Governance is operative: ADR framework and guardrails are in place and enforced.

# Phase 1 — Autonomous Engineering
**Locally complete and verified.** The M1 appliance demonstrates the full DoD.

# Phase 2 — Hermes CTL
Build personal AI control system. Not started yet.

# Phase 3 — Personal Intelligence
Planned future work.

## Current Status (auto-maintained)

## Phase 0 — Governance Foundation
Governance is operative: ADR framework and guardrails are in place and enforced.

## Phase 1 — Autonomous Engineering (M1: HADA release appliance)
**Locally complete and verified.** The M1 appliance demonstrates the full Phase 1 Definition of Done.
"""


def test_parse_roadmap_status_mapping(tmp_path):
    p = tmp_path / "MASTER_ROADMAP.md"
    p.write_text(FIXTURE_ROADMAP, encoding="utf-8")
    out = snapshot_mod.parse_roadmap(p)
    assert out["available"] is True
    by_name = {ph["name"]: ph["status"] for ph in out["phases"]}
    assert by_name["Phase 0"] == "active"      # "operative ... enforced"
    assert by_name["Phase 1"] == "complete"    # "locally complete and verified"
    assert by_name["Phase 2"] == "planned"     # defined, no status override
    assert by_name["Phase 3"] == "planned"


def test_parse_roadmap_no_invented_percentages(tmp_path):
    p = tmp_path / "MASTER_ROADMAP.md"
    p.write_text(FIXTURE_ROADMAP, encoding="utf-8")
    out = snapshot_mod.parse_roadmap(p)
    for ph in out["phases"]:
        assert "%" not in ph["status"]


def test_parse_roadmap_missing_file():
    out = snapshot_mod.parse_roadmap(Path("/nonexistent/MASTER_ROADMAP.md"))
    assert out["available"] is False
    assert "reason" in out


def test_is_stale_fail_closed():
    assert snapshot_mod.is_stale(None) is True           # unknown -> stale
    assert snapshot_mod.is_stale("not-a-date") is True    # malformed -> stale
    assert snapshot_mod.is_stale("2099-01-01T00:00:00+00:00") is False  # future -> fresh
    assert snapshot_mod.is_stale("2000-01-01T00:00:00+00:00") is True   # old -> stale


def test_validate_snapshot_real_generated():
    snap_path = HERE.parents[1] / "deploy" / "control-board" / "snapshot.json"
    if not snap_path.exists():
        pytest.skip("snapshot.json not generated; run control-board-snapshot.py")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    problems = snapshot_mod.validate_snapshot(snap)
    assert problems == [], f"snapshot validation problems: {problems}"
    assert snap.get("is_fixture") is False


def test_validate_snapshot_detects_fixture():
    bad = {"generated_at": "2026-01-01T00:00:00+00:00", "is_fixture": True,
           "repository": {"available": True}, "ci": {"available": True},
           "roadmap": {"available": True}, "governance": {"available": True}}
    problems = snapshot_mod.validate_snapshot(bad)
    assert any("fixture" in p for p in problems)


def test_validate_snapshot_detects_missing_available():
    bad = {"generated_at": "2026-01-01T00:00:00+00:00", "is_fixture": False,
           "repository": {}, "ci": {"available": True},
           "roadmap": {"available": True}, "governance": {"available": True}}
    problems = snapshot_mod.validate_snapshot(bad)
    assert any("repository" in p and "available" in p for p in problems)
