"""Hermes CTL — travel planning (Phase 3: Personal Intelligence).

Manages trips, destinations, dates, itinerary items, and trip status.
Stores trips as MemoryStore facts tagged with "travel" for cross-referencing
with other Phase 3 modules.

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_trips()`` reads all trip facts from MemoryStore — read-only.
- ``add_trip()``, ``update_trip_status()``, ``add_itinerary()`` mutate the store.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class TravelError(Exception):
    """Raised when travel operations fail."""


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------


@dataclass
class ItineraryItem:
    """A single scheduled activity within a trip."""

    day: int = 1
    """Day of the trip (1-indexed)."""

    time: str = ""
    """Time of the activity (e.g. '09:00', 'afternoon')."""

    activity: str = ""
    """Description of the activity."""

    location: str = ""
    """Where the activity takes place."""

    notes: str = ""
    """Free-text notes."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "time": self.time,
            "activity": self.activity,
            "location": self.location,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ItineraryItem":
        return cls(
            day=d.get("day", 1),
            time=d.get("time", ""),
            activity=d.get("activity", ""),
            location=d.get("location", ""),
            notes=d.get("notes", ""),
        )


@dataclass
class TravelTrip:
    """A single trip or travel plan.

    All fields have safe defaults so consumers never crash on missing data.
    """

    id: str = ""
    """Unique trip identifier (auto-generated from destination + date)."""

    destination: str = ""
    """Where the trip is to (city, address, region)."""

    start_date: str = ""
    """Start date in YYYY-MM-DD format."""

    end_date: str = ""
    """End date in YYYY-MM-DD format."""

    status: str = "planned"
    """Trip status: planned, active, completed, cancelled."""

    trip_type: str = "personal"
    """Type: personal, work, holiday, family, medical, other."""

    notes: str = ""
    """Free-text notes about the trip."""

    itinerary: list[ItineraryItem] = field(default_factory=list)
    """Scheduled activities for this trip."""

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "destination": self.destination,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "status": self.status,
            "tripType": self.trip_type,
            "notes": self.notes,
            "itinerary": [i.to_dict() for i in self.itinerary],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TravelTrip":
        return cls(
            id=d.get("id", ""),
            destination=d.get("destination", ""),
            start_date=d.get("startDate", d.get("start_date", "")),
            end_date=d.get("endDate", d.get("end_date", "")),
            status=d.get("status", "planned"),
            trip_type=d.get("tripType", d.get("trip_type", "personal")),
            notes=d.get("notes", ""),
            itinerary=[ItineraryItem.from_dict(i) for i in d.get("itinerary", [])],
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            updated_at=d.get("updatedAt", d.get("updated_at", time.time())),
        )


@dataclass
class TravelSnapshot:
    """Collection view of all trips."""

    trips: list[TravelTrip] = field(default_factory=list)
    total_count: int = 0
    planned_count: int = 0
    active_count: int = 0
    completed_count: int = 0
    upcoming: list[TravelTrip] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trips": [t.to_dict() for t in self.trips],
            "totalCount": self.total_count,
            "plannedCount": self.planned_count,
            "activeCount": self.active_count,
            "completedCount": self.completed_count,
            "upcoming": [t.to_dict() for t in self.upcoming],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TravelSnapshot":
        return cls(
            trips=[TravelTrip.from_dict(t) for t in d.get("trips", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            planned_count=d.get("plannedCount", d.get("planned_count", 0)),
            active_count=d.get("activeCount", d.get("active_count", 0)),
            completed_count=d.get("completedCount", d.get("completed_count", 0)),
            upcoming=[TravelTrip.from_dict(t) for t in d.get("upcoming", [])],
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan (read-only collection)
# ---------------------------------------------------------------------------


def scan_trips(
    *,
    store: Any = None,
    status: str | None = None,
) -> TravelSnapshot:
    """Read all trips from MemoryStore. Read-only.

    Args:
        store: A MemoryStore instance.
        status: Optional filter by status (planned, active, completed, cancelled).

    Returns:
        A populated ``TravelSnapshot`` with status breakdowns.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if store is None:
        return TravelSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="travel"))
    except Exception:
        return TravelSnapshot(timestamp=ts)

    trips: list[TravelTrip] = []
    planned = active = completed = 0

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        trip = TravelTrip.from_dict(val)
        if not trip.destination:
            continue
        if not trip.id:
            fid = getattr(fact, "id", "")
            if fid and fid.startswith("travel:"):
                trip.id = fid[len("travel:"):]
            else:
                trip.id = fid
        if status and trip.status != status:
            continue
        trips.append(trip)
        if trip.status == "planned":
            planned += 1
        elif trip.status == "active":
            active += 1
        elif trip.status == "completed":
            completed += 1

    # Upcoming = planned + active, sorted by start_date
    upcoming = sorted(
        [t for t in trips if t.status in ("planned", "active")],
        key=lambda t: t.start_date or "",
    )

    return TravelSnapshot(
        trips=trips,
        total_count=len(trips),
        planned_count=planned,
        active_count=active,
        completed_count=completed,
        upcoming=upcoming[:5],
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Mutations
# ---------------------------------------------------------------------------


def _trip_fact_id(trip_id: str) -> str:
    return f"travel:{trip_id}"


def add_trip(
    store: Any,
    destination: str,
    *,
    start_date: str = "",
    end_date: str = "",
    trip_type: str = "personal",
    notes: str = "",
) -> TravelTrip:
    """Create a new trip.

    Args:
        store: A MemoryStore instance.
        destination: Where the trip is to.
        start_date: Start date YYYY-MM-DD.
        end_date: End date YYYY-MM-DD.
        trip_type: personal, work, holiday, family, medical, other.
        notes: Free-text notes.

    Returns:
        The created ``TravelTrip``.
    """
    if not destination:
        raise TravelError("destination is required")

    now = time.time()
    trip_id = destination.strip().lower().replace(" ", "-")[:60]
    fact_id = _trip_fact_id(trip_id)

    trip = TravelTrip(
        id=trip_id,
        destination=destination.strip(),
        start_date=start_date,
        end_date=end_date,
        trip_type=trip_type,
        notes=notes,
        created_at=now,
        updated_at=now,
    )

    try:
        store.remember(fact_id, trip.to_dict(), tags={"travel"})
    except Exception as exc:
        raise TravelError(f"failed to add trip: {exc}") from exc

    return trip


def update_trip_status(store: Any, trip_id: str, status: str) -> TravelTrip | None:
    """Update a trip's status.

    Args:
        store: A MemoryStore instance.
        trip_id: Trip identifier.
        status: One of: planned, active, completed, cancelled.

    Returns:
        The updated trip, or None if not found.
    """
    valid_statuses = {"planned", "active", "completed", "cancelled"}
    if status not in valid_statuses:
        raise TravelError(f"invalid status '{status}'; must be one of {sorted(valid_statuses)}")

    fact_id = _trip_fact_id(trip_id)
    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if not val:
        return None

    trip = TravelTrip.from_dict(val)
    trip.status = status
    trip.updated_at = time.time()

    try:
        store.remember(fact_id, trip.to_dict(), tags={"travel"})
    except Exception as exc:
        raise TravelError(f"failed to update trip: {exc}") from exc

    return trip


def add_itinerary(
    store: Any,
    trip_id: str,
    activity: str,
    *,
    day: int = 1,
    time_str: str = "",
    location: str = "",
    notes: str = "",
) -> TravelTrip | None:
    """Add an itinerary item to a trip.

    Args:
        store: A MemoryStore instance.
        trip_id: Trip identifier.
        activity: Description of the activity.
        day: Day of the trip (1-indexed).
        time_str: Time of the activity.
        location: Where the activity takes place.
        notes: Free-text notes.

    Returns:
        The updated trip, or None if not found.
    """
    fact_id = _trip_fact_id(trip_id)
    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if not val:
        return None

    trip = TravelTrip.from_dict(val)
    trip.itinerary.append(ItineraryItem(
        day=day,
        time=time_str,
        activity=activity,
        location=location,
        notes=notes,
    ))
    trip.updated_at = time.time()

    try:
        store.remember(fact_id, trip.to_dict(), tags={"travel"})
    except Exception as exc:
        raise TravelError(f"failed to add itinerary item: {exc}") from exc

    return trip
