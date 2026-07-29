"""Hermes CTL — inventory intelligence (Phase 4: Home Hub Integration).

Manages household inventory items, stock levels, and location tracking.
Stores items as MemoryStore facts tagged with "inventory" for cross-referencing
with other modules.

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_inventory()`` reads all inventory items from MemoryStore — read-only.
- ``add_item()``, ``remove_item()``, ``update_quantity()`` mutate the store.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class InventoryError(Exception):
    """Raised when inventory operations fail."""


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------


@dataclass
class InventoryItem:
    """A single item tracked in household inventory.

    All fields have safe defaults so consumers never crash on missing data.
    """

    id: str = ""
    """Unique identifier (auto-generated as 'inventory:<name>')."""

    name: str = ""
    """Item name (e.g. 'AAA batteries', 'olive oil', 'toilet paper')."""

    category: str = "general"
    """Category: groceries, household, pantry, cleaning, personal, hardware, etc."""

    quantity: float = 1.0
    """Current stock quantity."""

    unit: str = "each"
    """Unit of measure (e.g. 'L', 'kg', 'pack', 'roll', 'each')."""

    min_quantity: float = 0.0
    """Minimum desired stock before reorder is needed."""

    location: str = ""
    """Where the item is kept (e.g. 'pantry', 'laundry', 'garage shelf 3')."""

    notes: str = ""
    """Free-text notes (brand, size, alternatives, reorder info)."""

    added_by: str = ""
    """Who added this item (e.g. 'Mason', 'Courtney')."""

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "quantity": self.quantity,
            "unit": self.unit,
            "minQuantity": self.min_quantity,
            "location": self.location,
            "notes": self.notes,
            "addedBy": self.added_by,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InventoryItem":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            category=d.get("category", d.get("category", "general")),
            quantity=float(d.get("quantity", 1.0)),
            unit=d.get("unit", "each"),
            min_quantity=float(d.get("minQuantity", d.get("min_quantity", 0.0))),
            location=d.get("location", ""),
            notes=d.get("notes", ""),
            added_by=d.get("addedBy", d.get("added_by", "")),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            updated_at=d.get("updatedAt", d.get("updated_at", time.time())),
        )


@dataclass
class InventorySnapshot:
    """Collection view of all inventory items."""

    items: list[InventoryItem] = field(default_factory=list)
    total_count: int = 0
    low_stock_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_location: dict[str, int] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "totalCount": self.total_count,
            "lowStockCount": self.low_stock_count,
            "byCategory": self.by_category,
            "byLocation": self.by_location,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InventorySnapshot":
        raw = d.get("items", [])
        return cls(
            items=[InventoryItem.from_dict(i) for i in raw],
            total_count=d.get("totalCount", d.get("total_count", len(raw))),
            low_stock_count=d.get("lowStockCount", d.get("low_stock_count", 0)),
            by_category=d.get("byCategory", d.get("by_category", {})),
            by_location=d.get("byLocation", d.get("by_location", {})),
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Store operations
# ---------------------------------------------------------------------------


INVENTORY_TAG = "inventory"


def _item_id(name: str) -> str:
    """Deterministic fact ID for an inventory item by name."""
    safe = name.lower().strip().replace(" ", "-")
    return f"inventory:{safe}"


def add_item(
    store: Any,
    name: str,
    *,
    category: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    min_quantity: float | None = None,
    location: str | None = None,
    notes: str | None = None,
    added_by: str | None = None,
) -> InventoryItem:
    """Add or update a tracked inventory item.

    If an item with the same name already exists, the existing values are
    preserved and only the explicitly provided fields override.
    """
    if not name or not name.strip():
        raise InventoryError("item name is required")

    item_id = _item_id(name)
    try:
        raw = store.recall(item_id)
    except Exception:
        raw = None

    now = time.time()
    if raw is not None:
        existing = InventoryItem.from_dict(raw) if isinstance(raw, dict) else raw
        item = InventoryItem(
            id=item_id,
            name=name.strip(),
            category=category if category is not None else existing.category,
            quantity=quantity if quantity is not None else existing.quantity,
            unit=unit if unit is not None else existing.unit,
            min_quantity=min_quantity if min_quantity is not None else existing.min_quantity,
            location=location if location is not None else existing.location,
            notes=notes if notes is not None else existing.notes,
            added_by=added_by if added_by is not None else existing.added_by,
            created_at=existing.created_at,
            updated_at=now,
        )
    else:
        item = InventoryItem(
            id=item_id,
            name=name.strip(),
            category=category or "general",
            quantity=quantity or 1.0,
            unit=unit or "each",
            min_quantity=min_quantity or 0.0,
            location=location or "",
            notes=notes or "",
            added_by=added_by or "",
            created_at=now,
            updated_at=now,
        )

    store.remember(item_id, item.to_dict(), tags=(INVENTORY_TAG,))
    return item


def remove_item(store: Any, name: str) -> bool:
    """Remove an inventory item by name. Returns True if removed."""
    item_id = _item_id(name)
    try:
        raw = store.recall(item_id)
    except Exception:
        raw = None
    if raw is None:
        return False
    store.forget(item_id)
    return True


def update_quantity(store: Any, name: str, quantity: float) -> InventoryItem | None:
    """Update the stock quantity of an inventory item."""
    item_id = _item_id(name)
    try:
        raw = store.recall(item_id)
    except Exception:
        raw = None
    if raw is None:
        return None

    existing = InventoryItem.from_dict(raw) if isinstance(raw, dict) else raw
    item = InventoryItem(
        id=item_id,
        name=existing.name,
        category=existing.category,
        quantity=quantity,
        unit=existing.unit,
        min_quantity=existing.min_quantity,
        location=existing.location,
        notes=existing.notes,
        added_by=existing.added_by,
        created_at=existing.created_at,
        updated_at=time.time(),
    )
    store.remember(item_id, item.to_dict(), tags=(INVENTORY_TAG,))
    return item


def scan_inventory(
    store: Any,
    *,
    category: str | None = None,
    location: str | None = None,
    low_stock_only: bool = False,
) -> InventorySnapshot:
    """Scan all inventory items and return a categorised snapshot.

    Supports optional filtering by category, location, or low-stock status.
    """
    facts = store.search(tag=INVENTORY_TAG)
    items: list[InventoryItem] = []
    for f in facts:
        raw = f.value if hasattr(f, "value") else f
        if isinstance(raw, dict):
            item = InventoryItem.from_dict(raw)
        else:
            continue

        if category and item.category != category:
            continue
        if location and item.location != location:
            continue
        if low_stock_only and item.min_quantity > 0 and item.quantity >= item.min_quantity:
            continue

        items.append(item)

    # Categorise
    by_category: dict[str, int] = {}
    by_location: dict[str, int] = {}
    low_stock = 0
    for item in items:
        by_category[item.category] = by_category.get(item.category, 0) + 1
        loc = item.location or "(unassigned)"
        by_location[loc] = by_location.get(loc, 0) + 1
        if item.min_quantity > 0 and item.quantity < item.min_quantity:
            low_stock += 1

    return InventorySnapshot(
        items=items,
        total_count=len(items),
        low_stock_count=low_stock,
        by_category=by_category,
        by_location=by_location,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    )


def deliver_inventory(snap: InventorySnapshot, store: Any) -> None:
    """Persist an inventory snapshot to MemoryStore."""
    store.remember(
        f"inventory:snapshot:{int(time.time())}",
        snap.to_dict(),
        tags=(INVENTORY_TAG, "snapshot"),
    )
