"""Hermes CTL — habit tracking (Phase 3: Personal Intelligence).

Tracks habits, daily completion, streaks, and categories. Stores habit
definitions and daily logs as MemoryStore facts tagged with "habit".

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_habits()`` reads habits from MemoryStore — read-only.
- ``add_habit()``, ``log_habit()``, ``update_streak()`` mutate the store.
- Every field has a safe default.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class HabitError(Exception):
    """Raised when habit operations fail."""


VALID_FREQUENCIES = frozenset({"daily", "weekdays", "weekly", "monthly", "custom"})


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------


@dataclass
class HabitLog:
    """A single daily habit completion log."""

    date: str = ""
    """Date in YYYY-MM-DD format."""

    notes: str = ""
    """Optional note about this completion."""

    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "notes": self.notes,
            "createdAt": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HabitLog":
        return cls(
            date=d.get("date", ""),
            notes=d.get("notes", ""),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
        )


@dataclass
class Habit:
    """A habit definition with tracking state."""

    id: str = ""
    """Unique habit identifier (auto-generated from name)."""

    name: str = ""
    """Habit name (e.g. 'meditate', 'exercise', 'read')."""

    category: str = "health"
    """Category: health, productivity, learning, social, mindfulness, finance, custom."""

    frequency: str = "daily"
    """How often: daily, weekdays, weekly, monthly, custom."""

    target_per_day: int = 1
    """Target completions per day (e.g. 3 glasses of water)."""

    unit: str = ""
    """Unit for tracking (e.g. 'minutes', 'pages', 'glasses')."""

    streak: int = 0
    """Current consecutive-day streak."""

    best_streak: int = 0
    """Best recorded streak."""

    total_count: int = 0
    """Total completions over all time."""

    last_done: str = ""
    """Last completion date YYYY-MM-DD."""

    logs: list[HabitLog] = field(default_factory=list)
    """Recent completion logs (last 90-ish entries)."""

    notes: str = ""
    """Free-text notes about the habit."""

    active: bool = True
    """Whether the habit is currently being tracked."""

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "frequency": self.frequency,
            "targetPerDay": self.target_per_day,
            "unit": self.unit,
            "streak": self.streak,
            "bestStreak": self.best_streak,
            "totalCount": self.total_count,
            "lastDone": self.last_done,
            "logs": [l.to_dict() for l in self.logs[-90:]],
            "notes": self.notes,
            "active": self.active,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Habit":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            category=d.get("category", "health"),
            frequency=d.get("frequency", "daily"),
            target_per_day=d.get("targetPerDay", d.get("target_per_day", 1)),
            unit=d.get("unit", ""),
            streak=d.get("streak", 0),
            best_streak=d.get("bestStreak", d.get("best_streak", 0)),
            total_count=d.get("totalCount", d.get("total_count", 0)),
            last_done=d.get("lastDone", d.get("last_done", "")),
            logs=[HabitLog.from_dict(l) for l in d.get("logs", [])],
            notes=d.get("notes", ""),
            active=d.get("active", True),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            updated_at=d.get("updatedAt", d.get("updated_at", time.time())),
        )


@dataclass
class HabitSnapshot:
    """Collection view of habits with streak analysis."""

    habits: list[Habit] = field(default_factory=list)
    total_count: int = 0
    active_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    top_streaks: list[Habit] = field(default_factory=list)
    """Habits sorted by streak, descending."""
    due_today: list[Habit] = field(default_factory=list)
    """Habits not yet completed today."""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "habits": [h.to_dict() for h in self.habits],
            "totalCount": self.total_count,
            "activeCount": self.active_count,
            "byCategory": dict(self.by_category),
            "topStreaks": [h.to_dict() for h in self.top_streaks[:5]],
            "dueToday": [h.to_dict() for h in self.due_today[:10]],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HabitSnapshot":
        return cls(
            habits=[Habit.from_dict(h) for h in d.get("habits", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            active_count=d.get("activeCount", d.get("active_count", 0)),
            by_category=d.get("byCategory", d.get("by_category", {})),
            top_streaks=[Habit.from_dict(h) for h in d.get("topStreaks", [])],
            due_today=[Habit.from_dict(h) for h in d.get("dueToday", [])],
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan (read-only)
# ---------------------------------------------------------------------------


def scan_habits(
    *,
    store: Any = None,
    category: str | None = None,
    active_only: bool = False,
    due_today: bool = False,
) -> HabitSnapshot:
    """Read habits from MemoryStore.

    Args:
        store: A MemoryStore instance.
        category: Optional filter by category.
        active_only: Only include active habits.
        due_today: Only include habits not yet completed today.

    Returns:
        A populated ``HabitSnapshot`` with category breakdown and streaks.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    today = time.strftime("%Y-%m-%d")

    if store is None:
        return HabitSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="habit"))
    except Exception:
        return HabitSnapshot(timestamp=ts)

    habits: list[Habit] = []
    by_category: dict[str, int] = {}

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        habit = Habit.from_dict(val)
        if not habit.name:
            continue
        if category and habit.category != category:
            continue
        if active_only and not habit.active:
            continue
        if due_today and habit.last_done == today:
            continue

        habits.append(habit)
        by_category[habit.category] = by_category.get(habit.category, 0) + 1

    active = sum(1 for h in habits if h.active)
    top_streaks = sorted(habits, key=lambda h: h.streak, reverse=True)
    due = [h for h in habits if h.active and h.last_done != today]

    return HabitSnapshot(
        habits=habits,
        total_count=len(habits),
        active_count=active,
        by_category=by_category,
        top_streaks=top_streaks,
        due_today=due,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Mutations
# ---------------------------------------------------------------------------


def _habit_fact_id(habit_id: str) -> str:
    return f"habit:{habit_id}"


def add_habit(
    store: Any,
    name: str,
    *,
    category: str = "health",
    frequency: str = "daily",
    target_per_day: int = 1,
    unit: str = "",
    notes: str = "",
) -> Habit:
    """Create a new habit.

    Args:
        store: A MemoryStore instance.
        name: Habit name.
        category: Habit category.
        frequency: How often (daily, weekdays, weekly, monthly, custom).
        target_per_day: Target completions per day.
        unit: Unit for tracking.
        notes: Free-text notes.

    Returns:
        The created ``Habit``.
    """
    if not name:
        raise HabitError("habit name is required")

    if frequency not in VALID_FREQUENCIES:
        raise HabitError(
            f"invalid frequency '{frequency}'; valid: {', '.join(sorted(VALID_FREQUENCIES))}"
        )

    now = time.time()
    habit_id = name.strip().lower().replace(" ", "-")[:60]
    fact_id = _habit_fact_id(habit_id)

    habit = Habit(
        id=habit_id,
        name=name.strip(),
        category=category,
        frequency=frequency,
        target_per_day=target_per_day,
        unit=unit,
        notes=notes,
        active=True,
        created_at=now,
        updated_at=now,
    )

    try:
        store.remember(fact_id, habit.to_dict(), tags={"habit"})
    except Exception as exc:
        raise HabitError(f"failed to add habit: {exc}") from exc

    return habit


def log_habit(store: Any, habit_id: str, *, date: str | None = None, notes: str = "") -> Habit | None:
    """Mark a habit as completed for a given date.

    Updates streak, last_done, total_count. Streak resets if a day was
    skipped (gap between last_done and current date > 1 day).

    Args:
        store: A MemoryStore instance.
        habit_id: Habit identifier.
        date: Date string YYYY-MM-DD (default: today).
        notes: Optional note about this completion.

    Returns:
        The updated habit, or None if not found.
    """
    fact_id = _habit_fact_id(habit_id)
    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if not val:
        return None

    habit = Habit.from_dict(val)
    today = date or time.strftime("%Y-%m-%d")

    # Check if already logged for this date
    if any(l.date == today for l in habit.logs):
        return habit  # already done today

    # Update streak
    if habit.last_done:
        try:
            last = time.strptime(habit.last_done, "%Y-%m-%d")
            cur = time.strptime(today, "%Y-%m-%d")
            days_diff = (time.mktime(cur) - time.mktime(last)) / 86400
            if days_diff <= 1.5:  # consecutive day (with tolerance for timezone)
                habit.streak += 1
            else:
                habit.streak = 1  # reset
        except (ValueError, OSError):
            habit.streak = 1
    else:
        habit.streak = 1

    habit.best_streak = max(habit.best_streak, habit.streak)
    habit.total_count += 1
    habit.last_done = today
    habit.updated_at = time.time()

    # Append log
    log_entry = HabitLog(date=today, notes=notes)
    habit.logs.append(log_entry)
    if len(habit.logs) > 180:
        habit.logs = habit.logs[-180:]

    try:
        store.remember(fact_id, habit.to_dict(), tags={"habit"})
    except Exception as exc:
        raise HabitError(f"failed to log habit: {exc}") from exc

    return habit
