"""Tests for the pantry stock management module (offline, no LLM/network)."""

import time

import pytest

from hermes_ctl.intelligence.pantry import (
    PantryError,
    PantryItem,
    PantrySnapshot,
    add_item,
    remove_item,
    update_quantity,
    scan_pantry,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_pantry_item_defaults():
    i = PantryItem()
    assert i.name == ""
    assert i.quantity == 1.0
    assert i.category == "dry-goods"
    assert i.location == "pantry"
    assert i.min_quantity == 0.0
    assert i.is_low_stock is False


def test_pantry_item_is_low_stock():
    i = PantryItem(name="oats", quantity=1, min_quantity=2)
    assert i.is_low_stock is True
    i.quantity = 2
    assert i.is_low_stock is True  # equal to threshold
    i.quantity = 3
    assert i.is_low_stock is False


def test_pantry_item_no_threshold():
    i = PantryItem(name="oats", quantity=0, min_quantity=0)
    assert i.is_low_stock is False


def test_pantry_item_to_dict_roundtrip():
    i = PantryItem(
        name="rolled oats",
        quantity=2.5,
        unit="kg",
        category="breakfast",
        location="pantry",
        min_quantity=1.0,
        notes="bulk bin",
    )
    d = i.to_dict()
    assert d["name"] == "rolled oats"
    assert d["quantity"] == 2.5
    assert d["category"] == "breakfast"
    assert d["location"] == "pantry"
    assert d["minQuantity"] == 1.0

    i2 = PantryItem.from_dict(d)
    assert i2.name == "rolled oats"
    assert i2.quantity == 2.5
    assert i2.category == "breakfast"
    assert i2.location == "pantry"
    assert i2.min_quantity == 1.0


def test_pantry_item_from_dict_empty():
    i = PantryItem.from_dict({})
    assert i.name == ""
    assert i.quantity == 1.0
    assert i.category == "dry-goods"
    assert i.location == "pantry"


def test_pantry_item_from_dict_camel_fallback():
    """Ensure camelCase keys (API format) are supported."""
    i = PantryItem.from_dict({
        "name": "pasta",
        "quantity": 3,
        "minQuantity": 1,
    })
    assert i.name == "pasta"
    assert i.quantity == 3
    assert i.min_quantity == 1


def test_snapshot_defaults():
    s = PantrySnapshot()
    assert s.total_count == 0
    assert s.low_stock_count == 0
    assert s.by_category == {}
    assert s.by_location == {}


def test_snapshot_to_dict_roundtrip():
    i = PantryItem(name="pasta", quantity=3, category="pasta-rice", location="pantry")
    s = PantrySnapshot(
        items=[i],
        total_count=1,
        low_stock_count=0,
        by_category={"pasta-rice": 1},
        by_location={"pantry": 1},
        timestamp="2026-07-29T00:00:00Z",
    )
    d = s.to_dict()
    assert d["totalCount"] == 1
    assert d["lowStockCount"] == 0
    assert d["byCategory"]["pasta-rice"] == 1

    s2 = PantrySnapshot.from_dict(d)
    assert s2.total_count == 1
    assert len(s2.items) == 1
    assert s2.items[0].name == "pasta"


# ---------------------------------------------------------------------------
# Store-based tests
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def test_add_item(store: MemoryStore):
    item = add_item(store, "rolled oats", quantity=2, unit="kg",
                    category="breakfast", notes="bulk bin")
    assert item.name == "rolled oats"
    assert item.quantity == 2.0
    assert item.category == "breakfast"


def test_add_item_empty_name(store: MemoryStore):
    with pytest.raises(PantryError, match="item name is required"):
        add_item(store, "")


def test_add_item_increments_quantity(store: MemoryStore):
    item1 = add_item(store, "pasta", quantity=2)
    assert item1.quantity == 2.0

    item2 = add_item(store, "pasta", quantity=3)
    assert item2.quantity == 5.0  # incremented


def test_scan_pantry_empty(store: MemoryStore):
    snap = scan_pantry(store=store)
    assert snap.total_count == 0
    assert snap.low_stock_count == 0


def test_scan_pantry_with_items(store: MemoryStore):
    add_item(store, "oats", quantity=2, category="breakfast")
    add_item(store, "pasta", quantity=3, category="pasta-rice")

    snap = scan_pantry(store=store)
    assert snap.total_count == 2
    assert snap.by_category.get("breakfast") == 1
    assert snap.by_category.get("pasta-rice") == 1


def test_scan_pantry_filter_category(store: MemoryStore):
    add_item(store, "oats", quantity=2, category="breakfast")
    add_item(store, "pasta", quantity=3, category="pasta-rice")

    snap = scan_pantry(store=store, category="breakfast")
    assert snap.total_count == 1
    assert snap.items[0].name == "oats"


def test_scan_pantry_filter_location(store: MemoryStore):
    add_item(store, "milk", quantity=1, location="fridge")
    add_item(store, "oats", quantity=2, location="pantry")

    snap = scan_pantry(store=store, location="fridge")
    assert snap.total_count == 1
    assert snap.items[0].name == "milk"


def test_scan_pantry_low_stock_only(store: MemoryStore):
    add_item(store, "oats", quantity=1, min_quantity=2)  # LOW
    add_item(store, "pasta", quantity=5, min_quantity=1)  # OK

    snap = scan_pantry(store=store, low_stock_only=True)
    assert snap.total_count == 1
    assert snap.items[0].name == "oats"
    assert snap.low_stock_count == 1


def test_scan_pantry_no_store():
    snap = scan_pantry()
    assert snap.total_count == 0
    assert snap.timestamp != ""


def test_remove_item(store: MemoryStore):
    add_item(store, "oats", quantity=2)
    assert remove_item(store, "oats") is True
    snap = scan_pantry(store=store)
    assert snap.total_count == 0


def test_remove_item_not_found(store: MemoryStore):
    assert remove_item(store, "nonexistent") is False


def test_update_quantity_delta(store: MemoryStore):
    add_item(store, "oats", quantity=5)
    item = update_quantity(store, "oats", delta=-2)
    assert item is not None
    assert item.quantity == 3.0


def test_update_quantity_absolute(store: MemoryStore):
    add_item(store, "oats", quantity=5)
    item = update_quantity(store, "oats", absolute=10)
    assert item is not None
    assert item.quantity == 10.0


def test_update_quantity_not_found(store: MemoryStore):
    assert update_quantity(store, "nonexistent", delta=1) is None


def test_update_quantity_no_zero(store: MemoryStore):
    add_item(store, "oats", quantity=2)
    item = update_quantity(store, "oats", delta=-10)  # would go negative
    assert item is not None
    assert item.quantity == 0.0  # clamped to zero


def test_update_quantity_no_args(store: MemoryStore):
    add_item(store, "oats", quantity=2)
    with pytest.raises(PantryError, match="either delta or absolute"):
        update_quantity(store, "oats")


def test_pantry_item_updated_at_bumps(store: MemoryStore):
    item = add_item(store, "oats", quantity=2)
    original = item.updated_at
    time.sleep(0.01)
    item2 = update_quantity(store, "oats", delta=1)
    assert item2 is not None
    assert item2.updated_at > original
