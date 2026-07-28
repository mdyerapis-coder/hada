"""Tests for the shopping intelligence module (offline, no LLM/network)."""

import json
import time

import pytest

from hermes_ctl.intelligence.shopping import (
    ShoppingError,
    ShoppingItem,
    ShoppingSnapshot,
    add_item,
    clear_purchased,
    mark_purchased,
    remove_item,
    scan_shopping,
)
from hermes_ctl.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


def test_shopping_item_defaults():
    i = ShoppingItem()
    assert i.name == ""
    assert i.quantity == 1.0
    assert i.category == "general"
    assert i.list_name == "main"
    assert i.purchased is False
    assert i.priority == "medium"


def test_shopping_item_to_dict_roundtrip():
    i = ShoppingItem(
        name="milk",
        quantity=2,
        unit="L",
        category="dairy",
        list_name="weekly",
        priority="high",
        store="Woolworths",
        notes="full cream",
        added_by="Mason",
    )
    d = i.to_dict()
    assert d["name"] == "milk"
    assert d["quantity"] == 2
    assert d["category"] == "dairy"
    assert d["listName"] == "weekly"
    assert d["store"] == "Woolworths"

    i2 = ShoppingItem.from_dict(d)
    assert i2.name == "milk"
    assert i2.quantity == 2
    assert i2.category == "dairy"
    assert i2.priority == "high"


def test_shopping_item_from_dict_empty():
    i = ShoppingItem.from_dict({})
    assert i.name == ""
    assert i.quantity == 1.0
    assert i.category == "general"


def test_snapshot_defaults():
    s = ShoppingSnapshot()
    assert s.total_count == 0
    assert s.active_count == 0
    assert s.purchased_count == 0
    assert s.by_category == {}


def test_snapshot_to_dict_roundtrip():
    i = ShoppingItem(name="eggs", quantity=12, category="dairy")
    s = ShoppingSnapshot(
        items=[i],
        total_count=1,
        active_count=1,
        by_category={"dairy": 1},
        by_list={"main": 1},
        timestamp="2026-07-29T00:00:00Z",
    )
    d = s.to_dict()
    s2 = ShoppingSnapshot.from_dict(d)
    assert s2.total_count == 1
    assert s2.active_count == 1
    assert len(s2.items) == 1


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_no_store():
    snap = scan_shopping(store=None)
    assert snap.total_count == 0


def test_scan_empty_store(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    snap = scan_shopping(store=store)
    assert snap.total_count == 0


def test_scan_with_items(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("shopping:milk", {
        "name": "milk", "quantity": 2, "unit": "L", "category": "dairy",
    }, tags={"shopping"})
    store.remember("shopping:bread", {
        "name": "bread", "quantity": 1, "category": "bakery",
    }, tags={"shopping"})
    snap = scan_shopping(store=store)
    assert snap.total_count == 2
    assert snap.by_category["dairy"] == 1
    assert snap.by_category["bakery"] == 1


def test_scan_active_only(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("shopping:milk", {
        "name": "milk", "category": "dairy", "purchased": False,
    }, tags={"shopping"})
    store.remember("shopping:bread", {
        "name": "bread", "category": "bakery", "purchased": True,
    }, tags={"shopping"})
    snap = scan_shopping(store=store, active_only=True)
    assert snap.total_count == 1  # only unpurchased
    assert snap.items[0].name == "milk"


def test_scan_filter_by_list(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    store.remember("shopping:milk", {
        "name": "milk", "category": "dairy", "list_name": "weekly",
    }, tags={"shopping"})
    store.remember("shopping:nails", {
        "name": "nails", "category": "hardware", "list_name": "hardware",
    }, tags={"shopping"})
    snap = scan_shopping(store=store, list_name="hardware")
    assert snap.total_count == 1
    assert snap.items[0].name == "nails"


# ---------------------------------------------------------------------------
# Add item tests
# ---------------------------------------------------------------------------


def test_add_item_creates(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    item = add_item(store, "milk", quantity=2, category="dairy")
    assert item.name == "milk"
    assert item.quantity == 2
    snap = scan_shopping(store=store)
    assert snap.total_count == 1


def test_add_item_merges_duplicate(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk", quantity=2, category="dairy")
    add_item(store, "milk", quantity=1, category="dairy")  # should merge
    snap = scan_shopping(store=store)
    assert snap.total_count == 1
    assert snap.items[0].quantity == 3  # 2 + 1


def test_add_item_raises_on_no_name(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    with pytest.raises(ShoppingError, match="item name is required"):
        add_item(store, "")


def test_add_item_with_all_fields(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    item = add_item(
        store, "AAA batteries",
        quantity=4, unit="pack", category="household",
        list_name="hardware", priority="high",
        store_name="Bunnings", notes="rechargeable",
        added_by="Mason",
    )
    assert item.store == "Bunnings"
    assert "rechargeable" in item.notes
    assert item.added_by == "Mason"


# ---------------------------------------------------------------------------
# Remove / mark purchased tests
# ---------------------------------------------------------------------------


def test_remove_item(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk", category="dairy")
    assert remove_item(store, "milk") is True
    snap = scan_shopping(store=store)
    assert snap.total_count == 0


def test_remove_nonexistent(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    assert remove_item(store, "nonexistent") is False


def test_remove_wrong_list(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk", list_name="weekly")
    assert remove_item(store, "milk", list_name="hardware") is False  # different list
    snap = scan_shopping(store=store)
    assert snap.total_count == 1  # still there


def test_mark_purchased(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk")
    assert mark_purchased(store, "milk") is True
    snap = scan_shopping(store=store)
    assert snap.items[0].purchased is True
    assert snap.items[0].purchased_at > 0


def test_mark_purchased_toggle_back(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk")
    mark_purchased(store, "milk", purchased=True)
    mark_purchased(store, "milk", purchased=False)
    snap = scan_shopping(store=store)
    assert snap.items[0].purchased is False


def test_mark_purchased_nonexistent(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    assert mark_purchased(store, "no-such-item") is False


# ---------------------------------------------------------------------------
# Clear purchased tests
# ---------------------------------------------------------------------------


def test_clear_purchased_all(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk")
    add_item(store, "bread")
    add_item(store, "eggs")
    mark_purchased(store, "milk")
    mark_purchased(store, "bread")
    count = clear_purchased(store)
    assert count == 2
    snap = scan_shopping(store=store)
    assert snap.total_count == 1  # eggs
    assert snap.items[0].name == "eggs"


def test_clear_purchased_by_list(tmp_path):
    p = str(tmp_path / "store.json")
    store = MemoryStore(persist_path=p)
    add_item(store, "milk", list_name="main")
    add_item(store, "nails", list_name="hardware")
    mark_purchased(store, "milk")
    mark_purchased(store, "nails")
    count = clear_purchased(store, list_name="main")
    assert count == 1
    snap = scan_shopping(store=store)
    assert snap.total_count == 1  # nails still there
    assert snap.items[0].name == "nails"
