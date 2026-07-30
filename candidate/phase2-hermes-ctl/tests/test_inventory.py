"""Tests for the inventory intelligence module (offline, no LLM/network)."""

import json
import time

import pytest

from hermes_ctl.intelligence.inventory import (
    InventoryError,
    InventoryItem,
    InventorySnapshot,
    add_item,
    remove_item,
    update_quantity,
    scan_inventory,
    deliver_inventory,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_inventory_item_defaults():
    i = InventoryItem()
    assert i.name == ""
    assert i.quantity == 1.0
    assert i.unit == "each"
    assert i.category == "general"
    assert i.min_quantity == 0.0


def test_inventory_item_to_dict_roundtrip():
    i = InventoryItem(
        name="olive oil",
        quantity=2,
        unit="L",
        category="pantry",
        location="pantry shelf 2",
        min_quantity=1.0,
        notes="extra virgin",
        added_by="Mason",
    )
    d = i.to_dict()
    assert d["name"] == "olive oil"
    assert d["quantity"] == 2
    assert d["category"] == "pantry"
    assert d["location"] == "pantry shelf 2"
    assert d["minQuantity"] == 1.0

    i2 = InventoryItem.from_dict(d)
    assert i2.name == "olive oil"
    assert i2.quantity == 2
    assert i2.category == "pantry"
    assert i2.min_quantity == 1.0


def test_inventory_item_from_dict_empty():
    i = InventoryItem.from_dict({})
    assert i.name == ""
    assert i.quantity == 1.0
    assert i.unit == "each"
    assert i.category == "general"


def test_inventory_item_from_dict_camel_and_snake():
    """Accept both camelCase (API) and snake_case (internal) keys."""
    camel = InventoryItem.from_dict({"minQuantity": 3.0, "addedBy": "Test"})
    assert camel.min_quantity == 3.0
    assert camel.added_by == "Test"

    snake = InventoryItem.from_dict({"min_quantity": 5.0, "added_by": "Test2"})
    assert snake.min_quantity == 5.0
    assert snake.added_by == "Test2"


def test_snapshot_defaults():
    s = InventorySnapshot()
    assert s.total_count == 0
    assert s.low_stock_count == 0
    assert s.by_category == {}
    assert s.by_location == {}


def test_snapshot_to_dict_roundtrip():
    i = InventoryItem(name="paper towels", quantity=6, category="household")
    s = InventorySnapshot(
        items=[i],
        total_count=1,
        low_stock_count=0,
        by_category={"household": 1},
        by_location={"(unassigned)": 1},
        timestamp="2025-01-01T00:00:00",
    )
    d = s.to_dict()
    assert d["totalCount"] == 1
    assert d["lowStockCount"] == 0
    assert d["byCategory"]["household"] == 1

    s2 = InventorySnapshot.from_dict(d)
    assert s2.total_count == 1
    assert len(s2.items) == 1
    assert s2.items[0].name == "paper towels"


# ---------------------------------------------------------------------------
# Store operation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    return MemoryStore()


class TestAddItem:
    def test_add_new_item(self, store):
        item = add_item(store, "AAA batteries", category="household", quantity=8, location="drawer")
        assert item.name == "AAA batteries"
        assert item.quantity == 8
        assert item.category == "household"
        assert item.location == "drawer"
        assert item.id == "inventory:aaa-batteries"

    def test_add_item_empty_name_raises(self, store):
        with pytest.raises(InventoryError):
            add_item(store, "")

    def test_add_item_updates_existing(self, store):
        add_item(store, "flour", quantity=2, unit="kg", category="pantry")
        updated = add_item(store, "flour", quantity=5)
        assert updated.quantity == 5
        assert updated.category == "pantry"  # preserved from first add
        assert updated.unit == "kg"

    def test_add_item_preserves_created_at(self, store):
        first = add_item(store, "sugar", quantity=1)
        time.sleep(0.01)
        second = add_item(store, "sugar", quantity=2)
        assert second.created_at == first.created_at
        assert second.updated_at > first.updated_at


class TestRemoveItem:
    def test_remove_existing(self, store):
        add_item(store, "soap", category="cleaning")
        assert remove_item(store, "soap") is True
        snap = scan_inventory(store)
        assert snap.total_count == 0

    def test_remove_nonexistent(self, store):
        assert remove_item(store, "nonexistent") is False


class TestUpdateQuantity:
    def test_update_existing(self, store):
        add_item(store, "paper towels", quantity=6)
        updated = update_quantity(store, "paper towels", 3)
        assert updated is not None
        assert updated.quantity == 3

    def test_update_nonexistent(self, store):
        assert update_quantity(store, "ghost item", 5) is None


class TestScanInventory:
    def test_empty_store(self, store):
        snap = scan_inventory(store)
        assert snap.total_count == 0
        assert snap.items == []

    def test_scan_all_items(self, store):
        add_item(store, "milk", category="groceries", quantity=2)
        add_item(store, "detergent", category="cleaning", quantity=1)
        add_item(store, "rice", category="pantry", quantity=5)

        snap = scan_inventory(store)
        assert snap.total_count == 3
        assert "groceries" in snap.by_category
        assert snap.by_category["groceries"] == 1
        assert snap.by_category["pantry"] == 1

    def test_scan_by_category(self, store):
        add_item(store, "apples", category="groceries")
        add_item(store, "bleach", category="cleaning")
        add_item(store, "bananas", category="groceries")

        snap = scan_inventory(store, category="groceries")
        assert snap.total_count == 2
        assert all(i.category == "groceries" for i in snap.items)

    def test_scan_by_location(self, store):
        add_item(store, "hammer", location="garage")
        add_item(store, "nails", location="garage")
        add_item(store, "sponge", location="kitchen")

        snap = scan_inventory(store, location="garage")
        assert snap.total_count == 2

    def test_scan_low_stock(self, store):
        add_item(store, "olive oil", quantity=0.5, min_quantity=1.0)
        add_item(store, "salt", quantity=3, min_quantity=1.0)
        add_item(store, "pepper", quantity=0.25, min_quantity=0.5)

        snap = scan_inventory(store, low_stock_only=True)
        assert snap.total_count == 2  # olive oil and pepper are below min
        names = {i.name for i in snap.items}
        assert "olive oil" in names
        assert "pepper" in names
        assert "salt" not in names

    def test_low_stock_count(self, store):
        add_item(store, "item A", quantity=1, min_quantity=2)
        add_item(store, "item B", quantity=5, min_quantity=3)
        add_item(store, "item C", quantity=0)

        snap = scan_inventory(store)
        assert snap.low_stock_count == 1  # only item A


class TestDeliverInventory:
    def test_deliver_persists_snapshot(self, store):
        add_item(store, "test item", category="test")
        snap = scan_inventory(store)
        deliver_inventory(snap, store)

        # Snapshot should be findable
        facts = store.search(tag="inventory")
        fact_ids = [f.id for f in facts]
        assert any("inventory:snapshot:" in fid for fid in fact_ids)


# ---------------------------------------------------------------------------
# Integration safety
# ---------------------------------------------------------------------------


def test_no_side_effects_on_empty_store():
    store = MemoryStore()
    snap = scan_inventory(store)
    assert snap.total_count == 0
    assert snap.items == []
    assert snap.by_category == {}
    assert snap.by_location == {}
