"""Hermes CTL — Financial awareness (Phase 3: Personal Intelligence).

Tracks budgets, expenses, and provides spend analysis. Manual-entry
(no automatic bank sync — that would need API keys and network access,
which is a governance boundary).

Follows the Phase 3 module pattern:
  Layer 1 — Dataclass models (Budget, Expense, FinancialSnapshot)
  Layer 2 — scan_finances() reads from MemoryStore
  Layer 3 — add_budget() / add_expense() writes to MemoryStore
  Layer 4 — deliver_finances() persists snapshot to MemoryStore
  Layer 5 — CLI at hermes_ctl/cli.py
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Any


class FinanceError(Exception):
    """Raised on invalid financial operations."""


VALID_CATEGORIES: frozenset[str] = frozenset({
    "groceries", "dining", "transport", "utilities", "housing",
    "entertainment", "shopping", "health", "education", "savings",
    "income", "custom",
})


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass models
# ---------------------------------------------------------------------------

@dataclass
class Budget:
    """A budget category with a spending limit."""
    category: str = ""
    limit: float = 0.0
    spent: float = 0.0
    period: str = "monthly"  # weekly, monthly, yearly

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.spent)

    @property
    def overspent(self) -> bool:
        return self.spent > self.limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "limit": self.limit,
            "spent": self.spent,
            "period": self.period,
            "remaining": self.remaining,
            "overspent": self.overspent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Budget":
        return cls(
            category=d.get("category", ""),
            limit=d.get("limit", 0.0),
            spent=d.get("spent", 0.0),
            period=d.get("period", "monthly"),
        )


@dataclass
class Expense:
    """A single expense entry."""
    id: str = ""
    category: str = ""
    amount: float = 0.0
    description: str = ""
    date: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "amount": self.amount,
            "description": self.description,
            "date": self.date,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Expense":
        return cls(
            id=d.get("id", ""),
            category=d.get("category", ""),
            amount=d.get("amount", 0.0),
            description=d.get("description", ""),
            date=d.get("date", ""),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class FinancialSnapshot:
    """Complete financial awareness snapshot."""
    budgets: list[Budget] = field(default_factory=list)
    expenses: list[Expense] = field(default_factory=list)
    total_budget: float = 0.0
    total_spent: float = 0.0
    overspent_categories: list[str] = field(default_factory=list)
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "budgets": [b.to_dict() for b in self.budgets],
            "expenses": [e.to_dict() for e in self.expenses[-20:]],  # cap recent
            "total_budget": self.total_budget,
            "total_spent": self.total_spent,
            "overspent_categories": self.overspent_categories,
            "by_category": self.by_category,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FinancialSnapshot":
        return cls(
            budgets=[Budget.from_dict(b) for b in d.get("budgets", [])],
            expenses=[Expense.from_dict(e) for e in d.get("expenses", [])],
            total_budget=d.get("total_budget", 0.0),
            total_spent=d.get("total_spent", 0.0),
            overspent_categories=d.get("overspent_categories", []),
            by_category=d.get("by_category", {}),
            date=d.get("date", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan / read
# ---------------------------------------------------------------------------

FINANCE_TAG = "finance"
BUDGET_TAG = "finance:budget"
EXPENSE_TAG = "finance:expense"
SNAPSHOT_TAG = "finance:snapshot"


def _category_spending(expenses: list[Expense], date_prefix: str) -> dict[str, float]:
    """Sum expenses by category for a given month (date_prefix YYYY-MM)."""
    out: dict[str, float] = {}
    for e in expenses:
        if e.date.startswith(date_prefix):
            out[e.category] = out.get(e.category, 0.0) + e.amount
    return out


def scan_finances(
    *,
    store: Any = None,
    date: str | None = None,
    budgets_only: bool = False,
) -> FinancialSnapshot:
    """Read financial data from MemoryStore.

    Pure collection: no network, no side effects.
    Returns a FinancialSnapshot with budgets, expenses, and computed summaries.
    """
    date = date or time.strftime("%Y-%m-%d", time.gmtime())
    month_prefix = date[:7]  # YYYY-MM

    budgets: list[Budget] = []
    expenses: list[Expense] = []
    overspent: list[str] = []

    if store is not None:
        try:
            facts = store.search(tag=BUDGET_TAG)
            for f in facts:
                val = f.value
                if isinstance(val, dict):
                    budgets.append(Budget.from_dict(val))
        except Exception:
            pass  # graceful degradation

        if not budgets_only:
            try:
                facts = store.search(tag=EXPENSE_TAG)
                for f in facts:
                    val = f.value
                    if isinstance(val, dict) and val.get("date", "").startswith(month_prefix):
                        expenses.append(Expense.from_dict(val))
            except Exception:
                pass  # graceful degradation

    # Compute per-category spend for this month
    cat_spend = _category_spending(expenses, month_prefix)

    # Overlay budget spent amounts from actual expenses
    for b in budgets:
        b.spent = cat_spend.get(b.category, 0.0)
        b.spent = round(b.spent, 2)
        if b.overspent:
            overspent.append(b.category)

    # By-category summary
    by_category: dict[str, dict[str, Any]] = {}
    for e in expenses:
        if e.category not in by_category:
            by_category[e.category] = {"count": 0, "total": 0.0, "avg": 0.0}
        by_category[e.category]["count"] += 1
        by_category[e.category]["total"] = round(
            by_category[e.category]["total"] + e.amount, 2
        )
    for cat, data in by_category.items():
        data["avg"] = round(data["total"] / data["count"], 2) if data["count"] else 0.0

    total_budget = round(sum(b.limit for b in budgets), 2)
    total_spent = round(sum(e.amount for e in expenses), 2)

    # Sort expenses by date descending (most recent first)
    expenses.sort(key=lambda e: e.date, reverse=True)

    return FinancialSnapshot(
        budgets=budgets,
        expenses=expenses,
        total_budget=total_budget,
        total_spent=total_spent,
        overspent_categories=overspent,
        by_category=by_category,
        date=date,
    )


# ---------------------------------------------------------------------------
# Layer 3 — Write operations
# ---------------------------------------------------------------------------

def add_budget(
    store: Any,
    category: str,
    limit: float,
    period: str = "monthly",
) -> Budget:
    """Add or update a budget category.

    Returns the created budget. Raises FinanceError on invalid input.
    """
    cat_normal = category.lower().strip()
    if not cat_normal:
        raise FinanceError("category is required")
    if limit <= 0:
        raise FinanceError(f"budget limit must be positive, got {limit}")
    if period not in ("weekly", "monthly", "yearly"):
        raise FinanceError(f"invalid period: {period}")

    budget_id = f"budget:{cat_normal}"
    # Read existing expenses for this category to compute spent
    existing_expenses: list[Expense] = []
    if store is not None:
        try:
            facts = store.search(tag=EXPENSE_TAG)
            month_prefix = time.strftime("%Y-%m", time.gmtime())
            for f in facts:
                val = f.value
                if isinstance(val, dict) and val.get("category", "").lower() == cat_normal:
                    if val.get("date", "").startswith(month_prefix):
                        existing_expenses.append(Expense.from_dict(val))
                elif isinstance(val, dict) and val.get("category") == cat_normal:
                    pass
        except Exception:
            pass

    spent = round(sum(e.amount for e in existing_expenses), 2)

    budget = Budget(category=cat_normal, limit=limit, period=period, spent=spent)
    try:
        store.remember(budget_id, budget.to_dict(), tags={BUDGET_TAG, FINANCE_TAG})
    except Exception as exc:
        raise FinanceError(f"failed to save budget: {exc}") from exc

    return budget


def _expense_id() -> str:
    """Generate a unique expense ID with a same-millisecond nonce."""
    now = time.time()
    nonce = random.randint(0, 9999)
    return f"exp:{int(now * 1000)}:{nonce}"


def add_expense(
    store: Any,
    category: str,
    amount: float,
    description: str = "",
    date: str | None = None,
) -> Expense:
    """Log an expense.

    Returns the created Expense. Raises FinanceError on invalid input.
    """
    cat_normal = category.lower().strip()
    if not cat_normal:
        raise FinanceError("category is required")
    if amount <= 0:
        raise FinanceError(f"expense amount must be positive, got {amount}")

    expense_date = date or time.strftime("%Y-%m-%d", time.gmtime())
    eid = _expense_id()
    expense = Expense(
        id=eid,
        category=cat_normal,
        amount=round(amount, 2),
        description=description,
        date=expense_date,
    )

    try:
        store.remember(eid, expense.to_dict(), tags={EXPENSE_TAG, FINANCE_TAG, f"cat:{cat_normal}"})
    except Exception as exc:
        raise FinanceError(f"failed to save expense: {exc}") from exc

    return expense


def deliver_finances(
    snapshot: FinancialSnapshot,
    *,
    store: Any = None,
) -> str:
    """Persist a financial snapshot to MemoryStore.

    Returns "memory" on success. No-store path works without crashing.
    """
    if store is not None:
        try:
            store.remember(
                f"finance:snapshot:{snapshot.date}",
                snapshot.to_dict(),
                tags={SNAPSHOT_TAG, FINANCE_TAG},
            )
        except Exception:
            pass  # non-fatal
    return "memory"
