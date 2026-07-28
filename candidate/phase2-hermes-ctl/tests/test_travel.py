"""Tests for the travel planning module (offline, no LLM/network)."""

import time

import pytest

from hermes_ctl.intelligence.travel import (
    TravelError,
    TravelTrip,
    TravelSnapshot,
    ItineraryItem,
    add_itinerary,
    add_trip,
    scan_trips,
    update_trip_status,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_trip_defaults():
    t = TravelTrip()
    assert t.destination == ""
    assert t.status == "planned"
    assert t.trip_type == "personal"
    assert t.itinerary == []


def test_trip_to_dict_roundtrip():
    t = TravelTrip(
        destination="Sydney",
        start_date="2026-08-15",
        end_date="2026-08-20",
        status="planned",
        trip_type="holiday",
        notes="Beach holiday",
        itinerary=[ItineraryItem(day=1, activity="Arrive", location="Airport")],
    )
    d = t.to_dict()
    assert d["destination"] == "Sydney"
    assert d["startDate"] == "2026-08-15"
    assert d["status"] == "planned"
    assert len(d["itinerary"]) == 1

    t2 = TravelTrip.from_dict(d)
    assert t2.destination == "Sydney"
    assert t2.start_date == "2026-08-15"
    assert len(t2.itinerary) == 1
    assert t2.itinerary[0].activity == "Arrive"


def test_trip_from_dict_empty():
    t = TravelTrip.from_dict({})
    assert t.destination == ""
    assert t.status == "planned"
    assert t.itinerary == []


def test_itinerary_item_roundtrip():
    i = ItineraryItem(day=2, time="10:00", activity="Snorkelling", location="Beach", notes="bring sunscreen")
    d = i.to_dict()
    i2 = ItineraryItem.from_dict(d)
    assert i2.day == 2
    assert i2.activity == "Snorkelling"


def test_snapshot_defaults():
    s = TravelSnapshot()
    assert s.total_count == 0
    assert s.planned_count == 0
    assert s.upcoming == []


def test_snapshot_to_dict_roundtrip():
    t = TravelTrip(destination="Melbourne", status="planned")
    s = TravelSnapshot(trips=[t], total_count=1, planned_count=1, upcoming=[t])
    d = s.to_dict()
    s2 = TravelSnapshot.from_dict(d)
    assert s2.total_count == 1
    assert len(s2.trips) == 1


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_trips(store=None)
    assert snap.total_count == 0


def test_scan_empty_store(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    snap = scan_trips(store=store)
    assert snap.total_count == 0


def test_scan_with_trips(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("travel:sydney", {
        "destination": "Sydney", "status": "planned", "startDate": "2026-08-15",
    }, tags={"travel"})
    store.remember("travel:melbourne", {
        "destination": "Melbourne", "status": "active", "startDate": "2026-07-30",
    }, tags={"travel"})
    snap = scan_trips(store=store)
    assert snap.total_count == 2
    assert snap.planned_count == 1
    assert snap.active_count == 1


def test_scan_filter_by_status(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("travel:sydney", {
        "destination": "Sydney", "status": "completed",
    }, tags={"travel"})
    store.remember("travel:melbourne", {
        "destination": "Melbourne", "status": "planned",
    }, tags={"travel"})
    snap = scan_trips(store=store, status="planned")
    assert snap.total_count == 1
    assert snap.trips[0].destination == "Melbourne"


def test_scan_upcoming_sorted(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("travel:b", {
        "destination": "Brisbane", "status": "planned", "startDate": "2026-09-01",
    }, tags={"travel"})
    store.remember("travel:a", {
        "destination": "Adelaide", "status": "active", "startDate": "2026-08-01",
    }, tags={"travel"})
    snap = scan_trips(store=store)
    assert len(snap.upcoming) == 2
    assert snap.upcoming[0].destination == "Adelaide"  # earlier date first


# ---------------------------------------------------------------------------
# Add trip tests
# ---------------------------------------------------------------------------


def test_add_trip_creates(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    trip = add_trip(store, "Sydney", start_date="2026-08-15", trip_type="holiday")
    assert trip.destination == "Sydney"
    assert trip.status == "planned"
    snap = scan_trips(store=store)
    assert snap.total_count == 1


def test_add_trip_raises_on_no_destination(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(TravelError, match="destination is required"):
        add_trip(store, "")


def test_add_trip_with_all_fields(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    trip = add_trip(
        store, "Byron Bay",
        start_date="2026-09-01", end_date="2026-09-07",
        trip_type="holiday", notes="Surf trip",
    )
    assert trip.start_date == "2026-09-01"
    assert "Surf" in trip.notes


# ---------------------------------------------------------------------------
# Status update tests
# ---------------------------------------------------------------------------


def test_update_trip_status(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_trip(store, "Sydney")
    trip = update_trip_status(store, "sydney", "active")
    assert trip is not None
    assert trip.status == "active"


def test_update_trip_status_nonexistent(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    trip = update_trip_status(store, "nowhere", "active")
    assert trip is None


def test_update_trip_status_invalid(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(TravelError, match="invalid status"):
        update_trip_status(store, "sydney", "bogus")


# ---------------------------------------------------------------------------
# Itinerary tests
# ---------------------------------------------------------------------------


def test_add_itinerary(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_trip(store, "Sydney")
    trip = add_itinerary(store, "sydney", "Visit Opera House", day=1, time_str="10:00", location="Circular Quay")
    assert trip is not None
    assert len(trip.itinerary) == 1
    assert trip.itinerary[0].activity == "Visit Opera House"


def test_add_itinerary_multiple_items(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_trip(store, "Sydney")
    add_itinerary(store, "sydney", "Arrive", day=1)
    add_itinerary(store, "sydney", "Depart", day=5)
    trip = add_itinerary(store, "sydney", "Bondi Beach", day=2)
    assert len(trip.itinerary) == 3


def test_add_itinerary_nonexistent_trip(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    trip = add_itinerary(store, "nowhere", "Do something")
    assert trip is None
