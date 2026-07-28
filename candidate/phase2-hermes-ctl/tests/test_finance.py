"""Tests for the financial awareness module (offline, no network)."""

from hermes_ctl.intelligence.finance import (
    Budget,
    Expense,
    FinancialSnapshot,
    FinanceError,
    add_budget,
    add_expense,
    scan_finances,
    deliver_finances,
)
from hermes_ctl.memory.store import MemoryStore


def _store() -> MemoryStore:
    return MemoryStore()


# ---------------------------------------------------------------------------
# Layer 1 — Data model
# ---------------------------------------------------------------------------

def test_budget_defaults():
    b = Budget()
    assert b.category == ""
    assert b.limit == 0.0
    assert b.spent == 0.0
    assert b.period == "monthly"
    assert b.remaining == 0.0
    assert not b.overspent


def test_budget_overspent():
    b = Budget(category="groceries", limit=100.0, spent=120.0)
    assert b.overspent
    assert b.remaining == 0.0


def test_budget_to_dict_roundtrip():
    b = Budget(category="dining", limit=200.0, spent=50.0, period="weekly")
    d = b.to_dict()
    assert d["category"] == "dining"
    assert d["limit"] == 200.0
    assert d["spent"] == 50.0
    assert d["period"] == "weekly"
    assert d["remaining"] == 150.0
    assert not d["overspent"]
    b2 = Budget.from_dict(d)
    assert b2.category == b.category
    assert b2.limit == b.limit
    assert b2.spent == b.spent


def test_expense_defaults():
    e = Expense()
    assert e.id == ""
    assert e.category == ""
    assert e.amount == 0.0


def test_expense_to_dict_roundtrip():
    e = Expense(id="exp:123", category="transport", amount=25.50, description="Uber", date="2026-07-30")
    d = e.to_dict()
    assert d["id"] == "exp:123"
    assert d["category"] == "transport"
    assert d["amount"] == 25.50
    e2 = Expense.from_dict(d)
    assert e2.category == e.category
    assert e2.amount == e.amount


def test_financial_snapshot_defaults():
    s = FinancialSnapshot()
    assert s.budgets == []
    assert s.expenses == []
    assert s.total_budget == 0.0
    assert s.total_spent == 0.0


def test_snapshot_to_dict_roundtrip():
    b = Budget(category="groceries", limit=300.0, spent=150.0)
    e = Expense(id="e1", category="groceries", amount=45.0, date="2026-07-30")
    s = FinancialSnapshot(
        budgets=[b],
        expenses=[e],
        total_budget=300.0,
        total_spent=45.0,
        date="2026-07-30",
    )
    d = s.to_dict()
    assert len(d["budgets"]) == 1
    assert len(d["expenses"]) == 1
    assert d["total_budget"] == 300.0
    s2 = FinancialSnapshot.from_dict(d)
    assert len(s2.budgets) == 1
    assert len(s2.expenses) == 1
    assert s2.budgets[0].category == "groceries"
    assert s2.expenses[0].category == "groceries"


# ---------------------------------------------------------------------------
# Layer 2 — Add budget
# ---------------------------------------------------------------------------

def test_add_budget():
    store = _store()
    b = add_budget(store, "groceries", 300.0)
    assert b.category == "groceries"
    assert b.limit == 300.0
    assert b.period == "monthly"

    # verify persisted
    facts = store.search(tag="finance:budget")
    assert len(facts) == 1
    assert facts[0].value["category"] == "groceries"


def test_add_budget_rejects_invalid():
    store = _store()
    try:
        add_budget(store, "", 100.0)
        assert False, "should reject empty category"
    except FinanceError:
        pass

    try:
        add_budget(store, "fun", 0.0)
        assert False, "should reject zero limit"
    except FinanceError:
        pass

    try:
        add_budget(store, "fun", 100.0, period="decade")
        assert False, "should reject invalid period"
    except FinanceError:
        pass


# ---------------------------------------------------------------------------
# Layer 3 — Add expense
# ---------------------------------------------------------------------------

def test_add_expense():
    store = _store()
    e = add_expense(store, "dining", 45.50, description="Lunch", date="2026-07-30")
    assert e.category == "dining"
    assert e.amount == 45.50
    assert e.description == "Lunch"
    assert e.date == "2026-07-30"
    assert e.id.startswith("exp:")

    # verify persisted
    facts = store.search(tag="finance:expense")
    assert len(facts) == 1
    assert facts[0].value["category"] == "dining"


def test_add_expense_rejects_invalid():
    store = _store()
    try:
        add_expense(store, "", 10.0)
        assert False, "should reject empty category"
    except FinanceError:
        pass

    try:
        add_expense(store, "fun", -5.0)
        assert False, "should reject negative amount"
    except FinanceError:
        pass

    try:
        add_expense(store, "fun", 0.0)
        assert False, "should reject zero amount"
    except FinanceError:
        pass


def test_add_many_expenses_generates_unique_ids():
    store = _store()
    ids = set()
    for i in range(20):
        e = add_expense(store, "groceries", float(i + 1), description=f"item {i}")
        assert e.id not in ids, f"duplicate id: {e.id}"
        ids.add(e.id)
    assert len(ids) == 20


def test_expense_id_within_same_ms():
    """Even multiple expenses in the same logical millisecond get unique IDs."""
    store = _store()
    ids = set()
    for _ in range(10):
        e = add_expense(store, "coffee", 4.50)
        ids.add(e.id)
    assert len(ids) == 10


# ---------------------------------------------------------------------------
# Layer 4 — Scan / list
# ---------------------------------------------------------------------------

def test_scan_finances_empty():
    store = _store()
    snap = scan_finances(store=store)
    assert snap.budgets == []
    assert snap.expenses == []
    assert snap.total_budget == 0.0
    assert snap.total_spent == 0.0


def test_scan_finances_with_budget():
    store = _store()
    add_budget(store, "groceries", 300.0)
    add_budget(store, "dining", 200.0)

    snap = scan_finances(store=store)
    assert len(snap.budgets) == 2
    assert snap.total_budget == 500.0
    # no expenses yet
    assert snap.total_spent == 0.0
    assert snap.overspent_categories == []


def test_scan_finances_with_expenses():
    store = _store()
    add_budget(store, "groceries", 300.0)
    add_budget(store, "dining", 200.0)
    add_expense(store, "groceries", 45.0, date="2026-07-30")
    add_expense(store, "groceries", 22.50, date="2026-07-30")
    add_expense(store, "dining", 35.0, date="2026-07-30")

    snap = scan_finances(store=store, date="2026-07-30")
    assert len(snap.budgets) == 2
    assert snap.total_budget == 500.0
    assert snap.total_spent == 102.50
    # budget spent amounts should be updated
    groceries_b = [b for b in snap.budgets if b.category == "groceries"][0]
    assert groceries_b.spent == 67.50
    dining_b = [b for b in snap.budgets if b.category == "dining"][0]
    assert dining_b.spent == 35.0

    # by-category breakdown
    assert "groceries" in snap.by_category
    assert snap.by_category["groceries"]["count"] == 2
    assert snap.by_category["groceries"]["total"] == 67.50
    assert "dining" in snap.by_category
    assert snap.by_category["dining"]["count"] == 1
    assert snap.by_category["dining"]["total"] == 35.0


def test_scan_finances_overspent():
    store = _store()
    add_budget(store, "groceries", 100.0)
    add_expense(store, "groceries", 110.0, date="2026-07-30")

    snap = scan_finances(store=store, date="2026-07-30")
    assert snap.overspent_categories == ["groceries"]


def test_scan_finances_only_current_month():
    """Expenses from a different month should not count toward current budget."""
    store = _store()
    add_budget(store, "groceries", 100.0)
    add_expense(store, "groceries", 50.0, date="2026-06-15")  # last month
    add_expense(store, "groceries", 30.0, date="2026-07-30")  # this month

    snap = scan_finances(store=store, date="2026-07-30")
    assert snap.total_spent == 30.0  # only this month's expense
    g = [b for b in snap.budgets if b.category == "groceries"][0]
    assert g.spent == 30.0


def test_scan_finances_no_store():
    """scan_finances should not crash when store is None."""
    snap = scan_finances(store=None)
    assert snap.total_budget == 0.0
    assert snap.total_spent == 0.0


# ---------------------------------------------------------------------------
# Layer 5 — Deliver
# ---------------------------------------------------------------------------

def test_deliver_finances():
    store = _store()
    add_budget(store, "groceries", 100.0)
    snap = scan_finances(store=store)

    result = deliver_finances(snap, store=store)
    assert result == "memory"

    # verify snapshot persisted
    facts = store.search(tag="finance:snapshot")
    assert len(facts) >= 1
    assert "budgets" in facts[-1].value


def test_deliver_finances_no_store():
    snap = FinancialSnapshot()
    result = deliver_finances(snap, store=None)
    assert result == "memory"


# ---------------------------------------------------------------------------
# Layer 6 — CLI smoke (import + parse only, no subprocess)
# ---------------------------------------------------------------------------

def test_cli_parser_has_finance():
    """Verify the finance subcommand is registered in the CLI parser."""
    from hermes_ctl.cli import build_parser
    parser = build_parser()
    for action in parser._actions:
        if action.dest == "cmd":
            choices = action.choices or {}
            assert "finance" in choices, "finance command not registered"
            return
    assert False, "cmd subparser not found"
