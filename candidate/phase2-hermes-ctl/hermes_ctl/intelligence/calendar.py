"""Hermes CTL — Calendar intelligence (Phase 4: Home Hub Integration).

Manages calendar events with household-oriented features
(add, complete, update, remove, scan/filter, snapshot delivery).

Follows the established Phase 3/4 module pattern:
  Layer 1 — Dataclass models (CalendarEvent, CalendarSnapshot)
  Layer 2 — scan_events() reads from MemoryStore with in-memory filters
  Layer 3 — add_event() / update_event() / complete_event() / remove_event()
  Layer 4 — deliver_calendar() persists snapshot to MemoryStore
  Layer 5 — CLI at hermes_ctl/cli/lifestyle_commands.py

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- All operations wrap store calls in try/except for graceful degradation.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Module-level counter for unique sortable event IDs
# ---------------------------------------------------------------------------

_event_seq: int = 0


def _next_event_id() -> str:
    """Generate a sortable calendar event ID using time + monotonic counter."""
    global _event_seq
    _event_seq += 1
    ms = int(time.time() * 1000)
    return f"cal_event:{ms}:{_event_seq}"


# ---------------------------------------------------------------------------
# Valid categories
# ---------------------------------------------------------------------------

VALID_CATEGORIES: frozenset[str] = frozenset({
    "appointment", "birthday", "meeting", "social", "health",
    "travel", "work", "family", "reminder", "other",
})

VALID_RECURRENCE: frozenset[str] = frozenset({
    "none", "daily", "weekly", "monthly", "yearly",
})


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass models
# ---------------------------------------------------------------------------


@dataclass
class CalendarEvent:
    """A single calendar event tracked in the household calendar.

    All fields have safe defaults so consumers never crash on missing data.
    """

    id: str = ""
    """Unique identifier (auto-generated as 'cal_event:<ms>:<seq>')."""

    title: str = ""
    """Event title / short description."""

    description: str = ""
    """Optional longer description of the event."""

    start_time: int = 0
    """Start time as Unix timestamp."""

    end_time: int = 0
    """End time as Unix timestamp (0 = same as start)."""

    all_day: bool = False
    """Whether this is an all-day event (ignores start/end time of day)."""

    location: str = ""
    """Optional location (address, room name, or virtual meeting link)."""

    category: str = "other"
    """Event category: appointment, birthday, meeting, social, health, travel, work, family, reminder, other."""

    recurrence: str = "none"
    """Recurrence pattern: none, daily, weekly, monthly, yearly."""

    completed: bool = False
    """Whether the event has been completed / attended."""

    completed_at: float = 0.0
    """Unix timestamp when completed (0 = not completed)."""

    created_at: float = field(default_factory=time.time)
    """Unix timestamp when the event was created."""

    tags: list[str] = field(default_factory=list)
    """Arbitrary tags for grouping / filtering."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "startTime": self.start_time,
            "start_time": self.start_time,
            "endTime": self.end_time,
            "end_time": self.end_time,
            "allDay": self.all_day,
            "all_day": self.all_day,
            "location": self.location,
            "category": self.category,
            "recurrence": self.recurrence,
            "completed": self.completed,
            "completedAt": self.completed_at,
            "completed_at": self.completed_at,
            "createdAt": self.created_at,
            "created_at": self.created_at,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CalendarEvent":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            start_time=d.get("startTime", d.get("start_time", 0)),
            end_time=d.get("endTime", d.get("end_time", 0)),
            all_day=d.get("allDay", d.get("all_day", False)),
            location=d.get("location", ""),
            category=d.get("category", "other"),
            recurrence=d.get("recurrence", "none"),
            completed=d.get("completed", False),
            completed_at=d.get("completedAt", d.get("completed_at", 0.0)),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            tags=d.get("tags", []),
        )


@dataclass
class CalendarSnapshot:
    """Collection view of calendar events with computed summaries."""

    events: list[CalendarEvent] = field(default_factory=list)
    total_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    upcoming_count: int = 0
    today_count: int = 0
    missed_count: int = 0
    completion_rate: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "totalCount": self.total_count,
            "total_count": self.total_count,
            "byCategory": dict(self.by_category),
            "by_category": dict(self.by_category),
            "upcomingCount": self.upcoming_count,
            "upcoming_count": self.upcoming_count,
            "todayCount": self.today_count,
            "today_count": self.today_count,
            "missedCount": self.missed_count,
            "missed_count": self.missed_count,
            "completionRate": self.completion_rate,
            "completion_rate": self.completion_rate,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CalendarSnapshot":
        return cls(
            events=[CalendarEvent.from_dict(e) for e in d.get("events", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            by_category=dict(d.get("byCategory", d.get("by_category", {}))),
            upcoming_count=d.get("upcomingCount", d.get("upcoming_count", 0)),
            today_count=d.get("todayCount", d.get("today_count", 0)),
            missed_count=d.get("missedCount", d.get("missed_count", 0)),
            completion_rate=d.get("completionRate", d.get("completion_rate", 0.0)),
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan / read
# ---------------------------------------------------------------------------


def _today_bounds() -> tuple[int, int]:
    """Return (start_of_today, end_of_today) as Unix timestamps in UTC."""
    now = time.gmtime()
    start = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0)))
    return start, start + 86400


def scan_events(
    *,
    store: Any = None,
    category: str | None = None,
    is_completed: bool | None = None,
    upcoming_only: bool = False,
    today_only: bool = False,
    missed_only: bool = False,
    tag: str | None = None,
) -> CalendarSnapshot:
    """Read all calendar events from MemoryStore with optional in-memory filters.

    Args:
        store: A MemoryStore instance.
        category: Filter by category (appointment, birthday, meeting, etc.).
        is_completed: Filter by completion state (True=completed, False=pending, None=all).
        upcoming_only: Only return events whose start_time is in the future.
        today_only: Only return events whose start_time falls today.
        missed_only: Only return past events that haven't been completed.
        tag: Filter by tag (exact match on any tag in the event's tag list).

    Returns:
        A populated ``CalendarSnapshot`` with computed summaries.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    now_ts = int(time.time())
    today_start, today_end = _today_bounds()

    if store is None:
        return CalendarSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="calendar_event"))
    except Exception:
        return CalendarSnapshot(timestamp=ts)

    events: list[CalendarEvent] = []
    by_category: dict[str, int] = {}
    upcoming_count = 0
    today_count = 0
    missed_count = 0

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        event = CalendarEvent.from_dict(val)
        if not event.id:
            continue

        # Apply filters
        if category is not None and event.category != category:
            continue
        if is_completed is not None and event.completed != is_completed:
            continue
        if upcoming_only and not (event.start_time > now_ts and not event.completed):
            continue
        if today_only and not (today_start <= event.start_time < today_end):
            continue
        if missed_only and not (event.end_time < now_ts and not event.completed and event.end_time > 0):
            continue
        if tag is not None and tag not in event.tags:
            continue

        events.append(event)
        cat = event.category or "other"
        by_category[cat] = by_category.get(cat, 0) + 1

        # Count upcoming (future, not completed)
        if event.start_time > now_ts and not event.completed:
            upcoming_count += 1

        # Count today
        if today_start <= event.start_time < today_end:
            today_count += 1

        # Count missed (past end_time, not completed, has actual end_time > 0)
        if event.end_time > 0 and event.end_time < now_ts and not event.completed:
            missed_count += 1

    # Sort: incomplete first, then by start_time ascending, then by title
    events.sort(key=lambda e: (e.completed, e.start_time or 0, e.title or ""))

    total = len(events)
    completed_count = sum(1 for e in events if e.completed)
    completion_rate = round(completed_count / total, 4) if total > 0 else 0.0

    return CalendarSnapshot(
        events=events,
        total_count=total,
        by_category=by_category,
        upcoming_count=upcoming_count,
        today_count=today_count,
        missed_count=missed_count,
        completion_rate=completion_rate,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Write operations
# ---------------------------------------------------------------------------


def _event_fact_id(event_id: str) -> str:
    """Normalise an event id into a MemoryStore fact key."""
    if event_id.startswith("cal_event:"):
        return event_id
    return f"cal_event:{event_id}"


def add_event(
    store: Any,
    title: str,
    *,
    description: str = "",
    start_time: int = 0,
    end_time: int = 0,
    all_day: bool = False,
    location: str = "",
    category: str = "other",
    recurrence: str = "none",
    tags: list[str] | None = None,
) -> CalendarEvent:
    """Add a new calendar event to MemoryStore.

    Args:
        store: A MemoryStore instance.
        title: Event title (required).
        description: Optional longer description.
        start_time: Start time as Unix timestamp.
        end_time: End time as Unix timestamp (0 = same as start).
        all_day: Whether this is an all-day event.
        location: Optional location.
        category: Event category (appointment, birthday, meeting, etc.).
        recurrence: Recurrence pattern.
        tags: Optional list of tags.

    Returns:
        The created ``CalendarEvent``.

    Raises:
        ValueError: If title is empty.
    """
    if not title or not title.strip():
        raise ValueError("event title is required")

    event_id = _next_event_id()
    now = time.time()

    if end_time <= 0:
        end_time = start_time

    event = CalendarEvent(
        id=event_id,
        title=title.strip(),
        description=description,
        start_time=start_time,
        end_time=end_time,
        all_day=all_day,
        location=location,
        category=category or "other",
        recurrence=recurrence or "none",
        created_at=now,
        tags=tags or [],
    )

    try:
        store.remember(event_id, event.to_dict(), tags={"calendar_event", f"cat:{event.category}"})
    except Exception as exc:
        raise RuntimeError(f"failed to add calendar event: {exc}") from exc

    return event


def update_event(store: Any, event_id: str, **kwargs: Any) -> CalendarEvent | None:
    """Update fields on an existing calendar event. Preserves created_at.

    Args:
        store: A MemoryStore instance.
        event_id: The event ID to update.
        **kwargs: Fields to update (title, description, start_time, end_time,
                  all_day, location, category, recurrence, tags).

    Returns:
        The updated ``CalendarEvent``, or None if not found.
    """
    fact_id = _event_fact_id(event_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        return None

    if not val:
        return None

    event = CalendarEvent.from_dict(val)

    # Apply updates, preserving created_at
    if "title" in kwargs and kwargs["title"]:
        event.title = kwargs["title"].strip()
    if "description" in kwargs:
        event.description = kwargs.get("description", "")
    if "start_time" in kwargs:
        event.start_time = int(kwargs.get("start_time", 0))
    if "end_time" in kwargs:
        event.end_time = int(kwargs.get("end_time", 0))
    if "all_day" in kwargs:
        event.all_day = bool(kwargs.get("all_day", False))
    if "location" in kwargs:
        event.location = kwargs.get("location", "")
    if "category" in kwargs:
        event.category = kwargs.get("category", "other")
    if "recurrence" in kwargs:
        event.recurrence = kwargs.get("recurrence", "none")
    if "tags" in kwargs:
        event.tags = list(kwargs.get("tags", []))

    try:
        store.remember(fact_id, event.to_dict(), tags={"calendar_event", f"cat:{event.category}"})
    except Exception as exc:
        raise RuntimeError(f"failed to update calendar event: {exc}") from exc

    return event


def complete_event(store: Any, event_id: str) -> CalendarEvent | None:
    """Mark a calendar event as completed / attended.

    Args:
        store: A MemoryStore instance.
        event_id: The event ID to mark complete.

    Returns:
        The updated ``CalendarEvent``, or None if not found.
    """
    fact_id = _event_fact_id(event_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        return None

    if not val:
        return None

    event = CalendarEvent.from_dict(val)
    event.completed = True
    event.completed_at = time.time()

    try:
        store.remember(fact_id, event.to_dict(), tags={"calendar_event", f"cat:{event.category}"})
    except Exception as exc:
        raise RuntimeError(f"failed to complete calendar event: {exc}") from exc

    return event


def remove_event(store: Any, event_id: str) -> bool:
    """Remove a calendar event from MemoryStore.

    Args:
        store: A MemoryStore instance.
        event_id: The event ID to remove.

    Returns:
        True if removed, False if not found.
    """
    fact_id = _event_fact_id(event_id)

    try:
        try:
            store.recall(fact_id)
        except Exception:
            return False
        store.forget(fact_id)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Layer 4 — Snapshot delivery
# ---------------------------------------------------------------------------


def deliver_calendar(store: Any, snapshot: CalendarSnapshot) -> str:
    """Persist a calendar snapshot to MemoryStore.

    Args:
        store: A MemoryStore instance.
        snapshot: The snapshot to persist.

    Returns:
        'memory' on success (no-store path returns 'memory' without crashing).
    """
    if store is not None:
        try:
            ts = snapshot.timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            store.remember(
                f"cal_snap:{ts}",
                snapshot.to_dict(),
                tags={"calendar_snapshot", "calendar_event"},
            )
        except Exception:
            pass  # non-fatal
    return "memory"
