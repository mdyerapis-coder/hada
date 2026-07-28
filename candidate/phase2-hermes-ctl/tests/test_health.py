"""Tests for the health tracking module (offline, no LLM/network)."""

import time

import pytest

from hermes_ctl.intelligence.health import (
    HealthError,
    HealthEntry,
    HealthSnapshot,
    log_metric,
    scan_health,
    VALID_METRICS,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_health_entry_defaults():
    e = HealthEntry()
    assert e.metric == "custom"
    assert e.value == 0.0
    assert e.source == "manual"


def test_health_entry_to_dict_roundtrip():
    e = HealthEntry(metric="weight", value=75.0, unit="kg", date="2026-07-29", notes="morning", source="manual")
    d = e.to_dict()
    assert d["metric"] == "weight"
    assert d["value"] == 75.0
    assert d["unit"] == "kg"

    e2 = HealthEntry.from_dict(d)
    assert e2.metric == "weight"
    assert e2.value == 75.0
    assert e2.date == "2026-07-29"


def test_health_entry_from_dict_empty():
    e = HealthEntry.from_dict({})
    assert e.metric == "custom"
    assert e.value == 0.0


def test_health_snapshot_defaults():
    s = HealthSnapshot()
    assert s.total_count == 0
    assert s.by_metric == {}
    assert s.recent == []


def test_health_snapshot_with_entries():
    e = HealthEntry(metric="steps", value=8000, unit="steps")
    s = HealthSnapshot(
        entries=[e],
        total_count=1,
        by_metric={"steps": 1},
        summary={"steps": {"min": 8000, "max": 8000, "avg": 8000, "last_value": 8000, "count": 1}},
        recent=[e],
    )
    d = s.to_dict()
    s2 = HealthSnapshot.from_dict(d)
    assert s2.total_count == 1
    assert s2.by_metric["steps"] == 1


def test_valid_metrics_set():
    assert "weight" in VALID_METRICS
    assert "steps" in VALID_METRICS
    assert "sleep" in VALID_METRICS
    assert "water" in VALID_METRICS
    assert "mood" in VALID_METRICS
    assert "exercise" in VALID_METRICS
    assert "custom" in VALID_METRICS
    assert len(VALID_METRICS) == 12


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_health(store=None)
    assert snap.total_count == 0


def test_scan_empty_store(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    snap = scan_health(store=store)
    assert snap.total_count == 0


def test_scan_with_metrics(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    log_metric(store, "weight", 75.0, unit="kg")
    log_metric(store, "steps", 8000, unit="steps")
    snap = scan_health(store=store)
    assert snap.total_count == 2
    assert "weight" in snap.by_metric
    assert "steps" in snap.by_metric


def test_scan_filter_by_metric(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    log_metric(store, "weight", 75.0, unit="kg")
    log_metric(store, "steps", 8000, unit="steps")
    snap = scan_health(store=store, metric="weight")
    assert snap.total_count == 1
    assert snap.entries[0].metric == "weight"


def test_scan_filter_by_date(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    log_metric(store, "weight", 75.0, unit="kg", date="2026-07-28")
    log_metric(store, "weight", 76.0, unit="kg", date="2026-07-29")
    snap = scan_health(store=store, date="2026-07-28")
    assert snap.total_count == 1
    assert snap.entries[0].value == 75.0


def test_scan_summary_computed(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    log_metric(store, "weight", 70.0, unit="kg")
    log_metric(store, "weight", 72.0, unit="kg")
    log_metric(store, "weight", 71.0, unit="kg")
    snap = scan_health(store=store, metric="weight")
    assert "weight" in snap.summary
    assert snap.summary["weight"]["min"] == 70.0
    assert snap.summary["weight"]["max"] == 72.0
    assert snap.summary["weight"]["count"] == 3
    assert snap.summary["weight"]["avg"] is not None


# ---------------------------------------------------------------------------
# Log metric tests
# ---------------------------------------------------------------------------


def test_log_basic(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    entry = log_metric(store, "water", 2.0, unit="L", date="2026-07-29")
    assert entry.metric == "water"
    assert entry.value == 2.0
    assert entry.date == "2026-07-29"
    snap = scan_health(store=store)
    assert snap.total_count == 1


def test_log_without_date_defaults_today(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    entry = log_metric(store, "steps", 10000)
    assert entry.date == time.strftime("%Y-%m-%d")


def test_log_raises_on_no_metric(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(HealthError, match="metric type is required"):
        log_metric(store, "", 50.0)


def test_log_raises_on_invalid_metric(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(HealthError, match="invalid metric"):
        log_metric(store, "invalid_metric", 50.0)


def test_log_with_source(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    entry = log_metric(store, "mood", 8, unit="1-10", notes="Feeling great", source="pwa")
    assert entry.source == "pwa"
    assert "great" in entry.notes


def test_log_multiple_entries_same_type(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    log_metric(store, "weight", 75.0, unit="kg")
    log_metric(store, "weight", 75.5, unit="kg")
    log_metric(store, "weight", 76.0, unit="kg")
    snap = scan_health(store=store, metric="weight")
    assert snap.total_count == 3


def test_log_adds_tags(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    log_metric(store, "exercise", 30, unit="min")
    facts = list(store.search(tag="health"))
    assert len(facts) == 1
