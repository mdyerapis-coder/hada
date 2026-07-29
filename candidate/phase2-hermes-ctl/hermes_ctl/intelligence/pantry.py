"""Hermes CTL — pantry stock management (Phase 4: Home Hub Integration).

Tracks household pantry inventory: what's in stock, quantities, low-stock
alerts, storage locations, and expiry-window notifications. Stores items as
MemoryStore facts tagged with "pantry" for cross-referencing with other
Phase 4 modules (shopping, inventory).

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- ``scan_pantry()`` reads all pantry items from MemoryStore — read-only.
- ``add_item()``, ``remove_item()``, ``update_quantity()`` mutate the store.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class PantryError(Exception):
    """Raised when pantry operations fail."""


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass model
# ---------------------------------------------------------------------------


PANTRY_CATEGORIES = [
    "dry-goods", "canned", "spices", "condiments", "baking",
    "beverages", "snacks", "breakfast", "pasta-rice", "sauces-oils",
    "fridge", "freezer", "produce", "other",
]

PANTRY_LOCATIONS = [
    "pantry", "cupboard", "fridge", "freezer", "counter", "garage", "other",
]


@dataclass
class PantryItem:
    """A single item tracked in the household pantry.

    All fields have safe defaults so consumers never crash on missing data.
    """

    id: str = ""
    """Unique identifier (auto-generated as 'pantry:<name>')."""

    name: str = ""
    """Item name (e.g. 'rolled oats', 'tinned tomatoes', 'olive oil')."""

    quantity: float = 1.0
    """Current stock quantity."""

    unit: str = ""
    """Unit of measure (e.g. 'kg', 'L', 'can', 'bottle'). Empty = each."""

    category: str = "dry-goods"
    """Category for grouping (see PANTRY_CATEGORIES)."""

    location: str = "pantry"
    """Storage location (see PANTRY_LOCATIONS)."""

    min_quantity: float = 0.0
    """Minimum stock before a low-stock alert is raised. 0 = no threshold."""

    notes: str = ""
    """Free-text notes (brand, size, alternatives, dietary info)."""

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "quantity": self.quantity,
            "unit": self.unit,
            "category": self.category,
            "location": self.location,
            "minQuantity": self.min_quantity,
            "notes": self.notes,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PantryItem":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            quantity=d.get("quantity", d.get("quantity", 1.0)),
            unit=d.get("unit", ""),
            category=d.get("category", d.get("category", "dry-goods")),
            location=d.get("location", d.get("location", "pantry")),
            min_quantity=d.get("minQuantity", d.get("min_quantity", 0.0)),
            notes=d.get("notes", ""),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            updated_at=d.get("updatedAt", d.get("updated_at", time.time())),
        )

    @property
    def is_low_stock(self) -> bool:
        """True if quantity <= min_quantity and threshold is set."""
        if self.min_quantity <= 0:
            return False
        return self.quantity <= self.min_quantity


@dataclass
class PantrySnapshot:
    """Collection view of all pantry items."""

    items: list[PantryItem] = field(default_factory=list)
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
            "byCategory": dict(self.by_category),
            "byLocation": dict(self.by_location),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PantrySnapshot":
        return cls(
            items=[PantryItem.from_dict(i) for i in d.get("items", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            low_stock_count=d.get("lowStockCount", d.get("low_stock_count", 0)),
            by_category=dict(d.get("byCategory", d.get("by_category", {}))),
            by_location=dict(d.get("byLocation", d.get("by_location", {}))),
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan (read-only collection)
# ---------------------------------------------------------------------------


def scan_pantry(
    *,
    store: Any = None,
    category: str | None = None,
    location: str | None = None,
    low_stock_only: bool = False,
) -> PantrySnapshot:
    """Read all pantry items from MemoryStore. Read-only.

    Args:
        store: A MemoryStore instance.
        category: Optional filter by category.
        location: Optional filter by storage location.
        low_stock_only: If True, only return items below min_quantity.

    Returns:
        A populated ``PantrySnapshot`` with category/location breakdowns.
        Every field has a safe default.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if store is None:
        return PantrySnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="pantry"))
    except Exception:
        return PantrySnapshot(timestamp=ts)

    items: list[PantryItem] = []
    by_category: dict[str, int] = {}
    by_location: dict[str, int] = {}

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        item = PantryItem.from_dict(val)
        if not item.name:
            continue
        if not item.id:
            fid = getattr(fact, "id", "")
            if fid and fid.startswith("pantry:"):
                item.id = fid[len("pantry:"):]
            else:
                item.id = fid
        # Apply filters
        if category and item.category != category:
            continue
        if location and item.location != location:
            continue
        if low_stock_only and not item.is_low_stock:
            continue

        items.append(item)
        cat = item.category or "dry-goods"
        by_category[cat] = by_category.get(cat, 0) + 1
        loc = item.location or "pantry"
        by_location[loc] = by_location.get(loc, 0) + 1

    low_stock = sum(1 for i in items if i.is_low_stock)

    # Sort: low-stock first, then by category, then by name
    items.sort(key=lambda i: (not i.is_low_stock, i.category or "", i.name or ""))

    return PantrySnapshot(
        items=items,
        total_count=len(items),
        low_stock_count=low_stock,
        by_category=by_category,
        by_location=by_location,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Mutations
# ---------------------------------------------------------------------------


def _item_fact_id(item_id: str) -> str:
    return f"pantry:{item_id}"


def add_item(
    store: Any,
    name: str,
    *,
    quantity: float = 1.0,
    unit: str = "",
    category: str = "dry-goods",
    location: str = "pantry",
    min_quantity: float = 0.0,
    notes: str = "",
) -> PantryItem:
    """Add or stock an item in the pantry.

    If an item with the same name already exists, its quantity is increased
    (instead of creating a duplicate entry).

    Args:
        store: A MemoryStore instance.
        name: Item name.
        quantity: Stock quantity.
        unit: Unit of measure.
        category: Item category (see PANTRY_CATEGORIES).
        location: Storage location (see PANTRY_LOCATIONS).
        min_quantity: Low-stock threshold (0 = no alert).
        notes: Free-text notes.

    Returns:
        The created or updated ``PantryItem``.
    """
    if not name:
        raise PantryError("item name is required")

    item_id = name.strip().lower().replace(" ", "-")[:60]
    fact_id = _item_fact_id(item_id)
    now = time.time()

    # Check for existing item
    try:
        existing_val = store.recall(fact_id)
    except Exception:
        existing_val = None

    if existing_val:
        existing = PantryItem.from_dict(existing_val)
        existing.quantity += quantity
        existing.updated_at = now
        if notes:
            existing.notes = notes
        if min_quantity > 0:
            existing.min_quantity = min_quantity
        store.remember(fact_id, existing.to_dict(), tags={"pantry"})
        return existing

    item = PantryItem(
        id=item_id,
        name=name.strip(),
        quantity=quantity,
        unit=unit,
        category=category,
        location=location,
        min_quantity=min_quantity,
        notes=notes,
        created_at=now,
    )

    try:
        store.remember(fact_id, item.to_dict(), tags={"pantry"})
    except Exception as exc:
        raise PantryError(f"failed to add pantry item: {exc}") from exc

    return item


def remove_item(store: Any, name: str) -> bool:
    """Remove a pantry item by name.

    Args:
        store: A MemoryStore instance.
        name: Item name to remove.

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

    try:
        store.forget(fact_id)
    except Exception as exc:
        raise PantryError(f"failed to remove item: {exc}") from exc
    return True


def update_quantity(
    store: Any,
    name: str,
    *,
    delta: float = 0.0,
    absolute: float | None = None,
) -> PantryItem | None:
    """Adjust an item's stock quantity.

    Args:
        store: A MemoryStore instance.
        name: Item name.
        delta: Signed amount to add/subtract (e.g. -0.5 to consume).
        absolute: If set, override quantity to this exact value.

    Returns:
        The updated ``PantryItem``, or None if not found.
    """
    if not name:
        raise PantryError("item name is required")
    if delta == 0 and absolute is None:
        raise PantryError("either delta or absolute must be specified")

    item_id = name.strip().lower().replace(" ", "-")[:60]
    fact_id = _item_fact_id(item_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        val = None

    if not val:
        return None

    item = PantryItem.from_dict(val)
    now = time.time()

    if absolute is not None:
        item.quantity = absolute
    else:
        item.quantity += delta

    if item.quantity < 0:
        item.quantity = 0.0

    item.updated_at = now

    try:
        store.remember(fact_id, item.to_dict(), tags={"pantry"})
    except Exception as exc:
        raise PantryError(f"failed to update quantity: {exc}") from exc

    return item
