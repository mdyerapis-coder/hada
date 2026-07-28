"""Hermes CTL — shopping intelligence (Phase 3: Personal Intelligence).

Manages shopping lists, items, and purchase tracking. Stores items as
MemoryStore facts tagged with "shopping" for cross-referencing with other
Phase 3 modules.

Governance / safety (mirrors context.py, relationships.py):
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_shopping()`` reads all shopping items from MemoryStore — read-only.
- ``add_item()``, ``remove_item()``, ``mark_purchased()`` mutate the store.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class ShoppingError(Exception):
    """Raised when shopping operations fail."""


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------


@dataclass
class ShoppingItem:
    """A single item on a shopping list.

    All fields have safe defaults so consumers never crash on missing data.
    """

    id: str = ""
    """Unique identifier (auto-generated as 'shopping:<name>')."""

    name: str = ""
    """Item name (e.g. 'milk', 'bread', 'AAA batteries')."""

    quantity: float = 1.0
    """How many to buy."""

    unit: str = ""
    """Unit of measure (e.g. 'L', 'kg', 'pack', 'loaf'). Empty = each."""

    category: str = "general"
    """Category for grouping: dairy, produce, meat, pantry, household, etc."""

    list_name: str = "main"
    """Which shopping list this belongs to (main, weekly, hardware, etc.)."""

    purchased: bool = False
    """Whether the item has been bought."""

    priority: str = "medium"
    """Priority: low, medium, high."""

    store: str = ""
    """Preferred store (e.g. 'Woolworths', 'Bunnings')."""

    notes: str = ""
    """Free-text notes (brand, size, alternatives)."""

    added_by: str = ""
    """Who added this item (e.g. 'Mason', 'Courtney')."""

    created_at: float = field(default_factory=time.time)
    purchased_at: float = 0.0
    """Unix timestamp when purchased (0 = not purchased)."""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "quantity": self.quantity,
            "unit": self.unit,
            "category": self.category,
            "listName": self.list_name,
            "purchased": self.purchased,
            "priority": self.priority,
            "store": self.store,
            "notes": self.notes,
            "addedBy": self.added_by,
            "createdAt": self.created_at,
            "purchasedAt": self.purchased_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShoppingItem":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            quantity=d.get("quantity", d.get("quantity", 1.0)),
            unit=d.get("unit", ""),
            category=d.get("category", d.get("category", "general")),
            list_name=d.get("listName", d.get("list_name", "main")),
            purchased=d.get("purchased", False),
            priority=d.get("priority", "medium"),
            store=d.get("store", ""),
            notes=d.get("notes", ""),
            added_by=d.get("addedBy", d.get("added_by", "")),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            purchased_at=d.get("purchasedAt", d.get("purchased_at", 0.0)),
            updated_at=d.get("updatedAt", d.get("updated_at", time.time())),
        )


@dataclass
class ShoppingSnapshot:
    """Collection view of all shopping items."""

    items: list[ShoppingItem] = field(default_factory=list)
    total_count: int = 0
    active_count: int = 0
    purchased_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_list: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "totalCount": self.total_count,
            "activeCount": self.active_count,
            "purchasedCount": self.purchased_count,
            "byCategory": dict(self.by_category),
            "byList": dict(self.by_list),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShoppingSnapshot":
        return cls(
            items=[ShoppingItem.from_dict(i) for i in d.get("items", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            active_count=d.get("activeCount", d.get("active_count", 0)),
            purchased_count=d.get("purchasedCount", d.get("purchased_count", 0)),
            by_category=dict(d.get("byCategory", d.get("by_category", {}))),
            by_list=dict(d.get("byList", d.get("by_list", {}))),
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan (read-only collection)
# ---------------------------------------------------------------------------


def scan_shopping(
    *,
    store: Any = None,
    list_name: str | None = None,
    active_only: bool = False,
) -> ShoppingSnapshot:
    """Read all shopping items from MemoryStore. Read-only.

    Args:
        store: A MemoryStore instance.
        list_name: Optional filter to a specific list (e.g. 'weekly').
        active_only: If True, only return unpurchased items.

    Returns:
        A populated ``ShoppingSnapshot`` with category/list breakdowns.
        Every field has a safe default.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if store is None:
        return ShoppingSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="shopping"))
    except Exception:
        return ShoppingSnapshot(timestamp=ts)

    items: list[ShoppingItem] = []
    by_category: dict[str, int] = {}
    by_list: dict[str, int] = {}

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        item = ShoppingItem.from_dict(val)
        if not item.name:
            continue
        # Use fact id if item id is empty
        if not item.id:
            fid = getattr(fact, "id", "")
            if fid and fid.startswith("shopping:"):
                item.id = fid[len("shopping:"):]
            else:
                item.id = fid
        # Apply filters
        if list_name and item.list_name != list_name:
            continue
        if active_only and item.purchased:
            continue
        items.append(item)
        cat = item.category or "general"
        by_category[cat] = by_category.get(cat, 0) + 1
        lst = item.list_name or "main"
        by_list[lst] = by_list.get(lst, 0) + 1

    active = sum(1 for i in items if not i.purchased)
    purchased = sum(1 for i in items if i.purchased)

    # Sort: active first, then by category
    items.sort(key=lambda i: (i.purchased, i.category or "", i.name or ""))

    return ShoppingSnapshot(
        items=items,
        total_count=len(items),
        active_count=active,
        purchased_count=purchased,
        by_category=by_category,
        by_list=by_list,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Mutations
# ---------------------------------------------------------------------------


def _item_fact_id(item_id: str) -> str:
    return f"shopping:{item_id}"


def add_item(
    store: Any,
    name: str,
    *,
    quantity: float = 1.0,
    unit: str = "",
    category: str = "general",
    list_name: str = "main",
    priority: str = "medium",
    store_name: str = "",
    notes: str = "",
    added_by: str = "",
) -> ShoppingItem:
    """Add a new item to a shopping list. Duplicate names within the same list
    will increment the quantity instead of creating a duplicate entry.

    Args:
        store: A MemoryStore instance.
        name: Item name.
        quantity: How many to buy.
        unit: Unit of measure.
        category: Item category (dairy, produce, meat, pantry, household, etc.)
        list_name: Which shopping list (main, weekly, hardware).
        priority: low, medium, high.
        store_name: Preferred store.
        notes: Free-text notes.
        added_by: Who added this item.

    Returns:
        The created or updated ``ShoppingItem``.
    """
    if not name:
        raise ShoppingError("item name is required")

    item_id = name.strip().lower().replace(" ", "-")[:60]
    fact_id = _item_fact_id(item_id)
    now = time.time()

    # Check for existing item (same name, same list)
    try:
        existing_val = store.recall(fact_id)
    except Exception:
        existing_val = None

    if existing_val:
        existing = ShoppingItem.from_dict(existing_val)
        # If same list, merge quantities
        if existing.list_name == list_name:
            existing.quantity += quantity
            existing.purchased = False
            existing.purchased_at = 0.0
            existing.updated_at = now
            if notes:
                existing.notes = notes
            store.remember(fact_id, existing.to_dict(), tags={"shopping"})
            return existing

    item = ShoppingItem(
        id=item_id,
        name=name.strip(),
        quantity=quantity,
        unit=unit,
        category=category,
        list_name=list_name,
        priority=priority,
        store=store_name,
        notes=notes,
        added_by=added_by,
        created_at=now,
    )

    try:
        store.remember(fact_id, item.to_dict(), tags={"shopping"})
    except Exception as exc:
        raise ShoppingError(f"failed to add shopping item: {exc}") from exc

    return item


def remove_item(store: Any, name: str, *, list_name: str = "main") -> bool:
    """Remove a shopping item by name and list.

    Args:
        store: A MemoryStore instance.
        name: Item name to remove.
        list_name: Which list the item is on.

    Returns:
        True if the item was removed, False if not found.
    """
    item_id = name.strip().lower().replace(" ", "-")[:60]
    fact_id = _item_fact_id(item_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if not val:
        return False

    existing = ShoppingItem.from_dict(val)
    if existing.list_name != list_name:
        return False

    try:
        store.forget(fact_id)
    except Exception as exc:
        raise ShoppingError(f"failed to remove item: {exc}") from exc
    return True


def mark_purchased(store: Any, name: str, *, list_name: str = "main", purchased: bool = True) -> bool:
    """Mark an item as purchased (or unmark it).

    Args:
        store: A MemoryStore instance.
        name: Item name.
        list_name: Which list the item is on.
        purchased: True to mark purchased, False to unmark.

    Returns:
        True if the item was updated, False if not found.
    """
    item_id = name.strip().lower().replace(" ", "-")[:60]
    fact_id = _item_fact_id(item_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if not val:
        return False

    item = ShoppingItem.from_dict(val)
    if item.list_name != list_name:
        return False

    item.purchased = purchased
    item.purchased_at = time.time() if purchased else 0.0

    try:
        store.remember(fact_id, item.to_dict(), tags={"shopping"})
    except Exception as exc:
        raise ShoppingError(f"failed to update item: {exc}") from exc
    return True


def clear_purchased(store: Any, *, list_name: str | None = None) -> int:
    """Remove all purchased items from a list (or all lists).

    Args:
        store: A MemoryStore instance.
        list_name: If set, only clear items on this list. Otherwise all lists.

    Returns:
        Number of items removed.
    """
    snap = scan_shopping(store=store, list_name=list_name)
    removed = 0
    for item in snap.items:
        if item.purchased:
            fact_id = _item_fact_id(item.id or item.name.strip().lower().replace(" ", "-")[:60])
            try:
                store.forget(fact_id)
                removed += 1
            except Exception:
                pass
    return removed
