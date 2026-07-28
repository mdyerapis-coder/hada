"""Hermes CTL — health tracking (Phase 3: Personal Intelligence).

Logs and tracks health metrics: weight, steps, sleep, water intake,
mood, exercise, medication, and custom metrics. Stores entries as
MemoryStore facts tagged with "health".

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_health()`` reads health metrics from MemoryStore — read-only.
- ``log_metric()`` appends a new metric entry.
- Every field has a safe default.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class HealthError(Exception):
    """Raised when health operations fail."""


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------

VALID_METRICS = frozenset({
    "weight", "steps", "sleep", "water", "mood", "exercise",
    "medication", "heart_rate", "blood_pressure", "blood_sugar",
    "calories", "custom",
})


@dataclass
class HealthEntry:
    """A single health metric entry."""

    metric: str = "custom"
    """Type of metric. One of: weight, steps, sleep, water, mood, exercise,
    medication, heart_rate, blood_pressure, blood_sugar, calories, custom."""

    value: float = 0.0
    """Numeric value of the metric."""

    unit: str = ""
    """Unit of measurement (kg, steps, hours, L, 1-10, min, etc.)."""

    date: str = ""
    """Date of the entry in YYYY-MM-DD format (default: today)."""

    notes: str = ""
    """Free-text notes."""

    source: str = "manual"
    """How the metric was recorded: manual, auto, pwa, api."""

    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "date": self.date,
            "notes": self.notes,
            "source": self.source,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HealthEntry":
        return cls(
            metric=d.get("metric", "custom"),
            value=d.get("value", 0.0),
            unit=d.get("unit", ""),
            date=d.get("date", d.get("date", "")),
            notes=d.get("notes", ""),
            source=d.get("source", "manual"),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
        )


@dataclass
class HealthSnapshot:
    """Aggregated view of health metrics."""

    entries: list[HealthEntry] = field(default_factory=list)
    total_count: int = 0
    by_metric: dict[str, int] = field(default_factory=dict)
    summary: dict[str, dict[str, float]] = field(default_factory=dict)
    """Per-metric summary: min, max, avg, last_value."""
    recent: list[HealthEntry] = field(default_factory=list)
    """Last 10 entries across all metrics."""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "totalCount": self.total_count,
            "byMetric": dict(self.by_metric),
            "summary": dict(self.summary),
            "recent": [e.to_dict() for e in self.recent],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HealthSnapshot":
        return cls(
            entries=[HealthEntry.from_dict(e) for e in d.get("entries", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            by_metric=d.get("byMetric", d.get("by_metric", {})),
            summary=d.get("summary", {}),
            recent=[HealthEntry.from_dict(e) for e in d.get("recent", [])],
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan (read-only)
# ---------------------------------------------------------------------------


def scan_health(
    *,
    store: Any = None,
    metric: str | None = None,
    date: str | None = None,
    limit: int = 50,
) -> HealthSnapshot:
    """Read health entries from MemoryStore.

    Args:
        store: A MemoryStore instance.
        metric: Optional filter by metric type.
        date: Optional filter by date (YYYY-MM-DD).
        limit: Max entries to return (default 50, 0 = all).

    Returns:
        A populated ``HealthSnapshot`` with per-metric breakdowns and summary.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if store is None:
        return HealthSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="health"))
    except Exception:
        return HealthSnapshot(timestamp=ts)

    entries: list[HealthEntry] = []
    by_metric: dict[str, int] = {}
    values_by_metric: dict[str, list[float]] = {}

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        entry = HealthEntry.from_dict(val)
        if metric and entry.metric != metric:
            continue
        if date and entry.date != date:
            continue
        entries.append(entry)
        by_metric[entry.metric] = by_metric.get(entry.metric, 0) + 1
        if entry.value != 0:  # skip zero as "not set"
            values_by_metric.setdefault(entry.metric, []).append(entry.value)

    # Per-metric summary
    summary: dict[str, dict[str, float]] = {}
    for m, vals in values_by_metric.items():
        summary[m] = {
            "min": min(vals),
            "max": max(vals),
            "avg": round(sum(vals) / len(vals), 2),
            "last_value": vals[-1],
            "count": len(vals),
        }

    # Sort by creation time descending for recent
    sorted_entries = sorted(entries, key=lambda e: e.created_at, reverse=True)

    return HealthSnapshot(
        entries=entries[:limit] if limit else entries,
        total_count=len(entries),
        by_metric=by_metric,
        summary=summary,
        recent=sorted_entries[:10],
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Logging
# ---------------------------------------------------------------------------


def log_metric(
    store: Any,
    metric: str,
    value: float,
    *,
    unit: str = "",
    date: str | None = None,
    notes: str = "",
    source: str = "manual",
) -> HealthEntry:
    """Log a health metric entry.

    Args:
        store: A MemoryStore instance.
        metric: Metric type (weight, steps, sleep, water, mood, etc).
        value: Numeric value.
        unit: Unit of measurement.
        date: Date string YYYY-MM-DD (default: today).
        notes: Free-text notes.
        source: How recorded (manual, auto, pwa, api).

    Returns:
        The created ``HealthEntry``.
    """
    if not metric:
        raise HealthError("metric type is required")

    if metric not in VALID_METRICS:
        raise HealthError(
            f"invalid metric '{metric}'; valid: {', '.join(sorted(VALID_METRICS))}"
        )

    now = time.time()
    date_str = date or time.strftime("%Y-%m-%d", time.localtime(now))

    # Unique id: health:<metric>:<date>:<unix>:<counter>
    import random
    counter = random.randint(0, 9999)
    entry_id = f"health:{metric}:{date_str}:{int(now * 1000)}:{counter}"

    entry = HealthEntry(
        metric=metric,
        value=value,
        unit=unit,
        date=date_str,
        notes=notes,
        source=source,
        created_at=now,
    )

    try:
        store.remember(entry_id, entry.to_dict(), tags={"health"})
    except Exception as exc:
        raise HealthError(f"failed to log metric: {exc}") from exc

    return entry
