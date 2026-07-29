"""Lifestyle commands: shopping, travel, finance, relationship."""

from __future__ import annotations

import argparse
import json
import time

from hermes_ctl.cli.store import _store
from hermes_ctl.intelligence.finance import (
    FinancialSnapshot,
    FinanceError,
    add_budget,
    add_expense,
    scan_finances,
    deliver_finances,
)


def build_parser(sub) -> None:
    _build_relationship_parser(sub)
    _build_shopping_parser(sub)
    _build_travel_parser(sub)
    _build_finance_parser(sub)
    _build_family_task_parser(sub)


# ---------------------------------------------------------------------------
# relationship
# ---------------------------------------------------------------------------
def _build_relationship_parser(sub) -> None:
    prel = sub.add_parser("relationship", help="relationship management (track contacts, strength, interactions)")
    rsub = prel.add_subparsers(dest="rel_action", required=True)

    rl = rsub.add_parser("list", help="list all tracked relationships with type and strength")
    rl.set_defaults(func=_cmd_relationship)

    rs = rsub.add_parser("show", help="show details for a specific person")
    rs.add_argument("person", help="person id or name to look up")
    rs.set_defaults(func=_cmd_relationship)

    ru = rsub.add_parser("update", help="create or update a relationship record")
    ru.add_argument("person", help="person identifier (handle or contact key)")
    ru.add_argument("--name", help="display name")
    ru.add_argument("--type", dest="rel_type", help="relationship type (family, partner, friend, colleague, acquaintance, service, other)")
    ru.add_argument("--strength", type=float, help="relationship strength 0.0–1.0")
    ru.add_argument("--notes", help="free-text notes")
    ru.add_argument("--tag", action="append", help="grouping tags (repeatable)")
    ru.add_argument("--channel", action="append", help="contact channels used (repeatable)")
    ru.set_defaults(func=_cmd_relationship)

    ri = rsub.add_parser("interact", help="record an interaction (increments contact count, updates recency)")
    ri.add_argument("person", help="person identifier")
    ri.add_argument("--name", help="display name (used on first contact)")
    ri.add_argument("--channel", help="channel this interaction came on (telegram, sms, email)")
    ri.add_argument("--type", dest="rel_type", help="relationship type")
    ri.set_defaults(func=_cmd_relationship)


def _cmd_relationship(args: argparse.Namespace) -> int:
    from hermes_ctl.intelligence.relationships import (
        scan_relationships,
        update_relationship,
        record_interaction,
    )

    store = _store()

    if args.rel_action == "list":
        snap = scan_relationships(store=store)
        print(f"Relationships ({snap.total_count} total, by type: {json.dumps(snap.by_type)}):")
        for r in snap.relationships:
            when = time.strftime("%Y-%m-%d", time.gmtime(r.last_contacted)) if r.last_contacted > 0 else "never"
            print(f"  {r.person_id:20s} {r.strength:.2f}  {r.relationship_type:15s} contacted:{when}")
        return 0

    if args.rel_action == "show":
        snap = scan_relationships(store=store)
        matches = [r for r in snap.relationships if r.person_id == args.person or r.name == args.person]
        if not matches:
            print(f"(no relationship found for {args.person})")
            return 1
        for r in matches:
            print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.rel_action == "update":
        rel = update_relationship(
            store,
            args.person,
            name=args.name or "",
            relationship_type=args.rel_type,
            strength=args.strength,
            notes=args.notes,
            tags=args.tag,
            channels=args.channel,
        )
        print(f"updated relationship: {rel.person_id} ({rel.relationship_type}, strength={rel.strength:.2f})")
        return 0

    if args.rel_action == "interact":
        rel = record_interaction(
            store,
            args.person,
            name=args.name or "",
            channel=args.channel or "",
            relationship_type=args.rel_type,
        )
        print(f"recorded interaction: {rel.person_id} (count={rel.contact_count}, strength={rel.strength:.2f})")
        return 0

    return 2


# ---------------------------------------------------------------------------
# shopping
# ---------------------------------------------------------------------------
def _build_shopping_parser(sub) -> None:
    psh = sub.add_parser("shopping", help="shopping list management (add, list, buy, clear)")
    shsub = psh.add_subparsers(dest="shop_action", required=True)

    shl = shsub.add_parser("list", help="list shopping items (active-only with --active)")
    shl.add_argument("--list", dest="list", default=None, help="filter by list name")
    shl.add_argument("--active-only", action="store_true", default=False, help="show only active (unpurchased) items")
    shl.set_defaults(func=_cmd_shopping)

    sha = shsub.add_parser("add", help="add an item to a shopping list")
    sha.add_argument("name", help="item name (e.g. 'milk')")
    sha.add_argument("--quantity", type=float, default=1.0, help="how many (default: 1)")
    sha.add_argument("--unit", help="unit (L, kg, pack, loaf)")
    sha.add_argument("--category", default="general", help="category (dairy, produce, meat, pantry, household)")
    sha.add_argument("--list", dest="list", default="main", help="shopping list name (default: main)")
    sha.add_argument("--priority", default="medium", choices=["low", "medium", "high"], help="priority")
    sha.add_argument("--store", help="preferred store")
    sha.add_argument("--notes", help="free-text notes")
    sha.add_argument("--added-by", default="", help="who added this item")
    sha.set_defaults(func=_cmd_shopping)

    shr = shsub.add_parser("remove", help="remove an item from a shopping list")
    shr.add_argument("name", help="item name to remove")
    shr.add_argument("--list", dest="list", default="main", help="which list (default: main)")
    shr.set_defaults(func=_cmd_shopping)

    shb = shsub.add_parser("buy", help="mark an item as purchased")
    shb.add_argument("name", help="item name to mark purchased")
    shb.add_argument("--list", dest="list", default="main", help="which list (default: main)")
    shb.set_defaults(func=_cmd_shopping)

    shc = shsub.add_parser("clear", help="remove all purchased items")
    shc.add_argument("--list", dest="list", default=None, help="which list (default: all lists)")
    shc.set_defaults(func=_cmd_shopping)


def _cmd_shopping(args: argparse.Namespace) -> int:
    from hermes_ctl.intelligence.shopping import (
        add_item,
        remove_item,
        mark_purchased,
        clear_purchased,
        scan_shopping,
    )

    store = _store()

    if args.shop_action == "list":
        snap = scan_shopping(store=store, list_name=args.list, active_only=args.active_only)
        print(f"Shopping items ({snap.active_count} active, {snap.purchased_count} purchased, across {len(snap.by_list)} list(s)):")
        print(f"  Categories: {json.dumps(snap.by_category)}")
        for item in snap.items:
            status = "✅" if item.purchased else "⬜"
            qty = f"{item.quantity}{item.unit}" if item.unit else str(int(item.quantity) if item.quantity == int(item.quantity) else item.quantity)
            print(f"  {status} {item.name:30s} {qty:8s} [{item.category:12s}] {item.list_name}")
        return 0

    if args.shop_action == "add":
        item = add_item(
            store,
            args.name,
            quantity=args.quantity,
            unit=args.unit or "",
            category=args.category or "general",
            list_name=args.list or "main",
            priority=args.priority or "medium",
            store_name=args.store or "",
            notes=args.notes or "",
            added_by=args.added_by or "",
        )
        print(f"added: {item.name} (x{item.quantity}, {item.list_name})")
        return 0

    if args.shop_action == "remove":
        ok = remove_item(store, args.name, list_name=args.list or "main")
        if ok:
            print(f"removed: {args.name}")
            return 0
        print(f"(no item named {args.name} in list {args.list or 'main'})", file=__import__("sys").stderr)
        return 1

    if args.shop_action == "buy":
        ok = mark_purchased(store, args.name, list_name=args.list or "main", purchased=True)
        if ok:
            print(f"marked purchased: {args.name}")
            return 0
        print(f"(no item named {args.name})", file=__import__("sys").stderr)
        return 1

    if args.shop_action == "clear":
        count = clear_purchased(store, list_name=args.list)
        print(f"cleared {count} purchased item(s)")
        return 0

    return 2


# ---------------------------------------------------------------------------
# travel
# ---------------------------------------------------------------------------
def _build_travel_parser(sub) -> None:
    ptr = sub.add_parser("travel", help="travel planning (trips, destinations, itineraries)")
    trsub = ptr.add_subparsers(dest="travel_action", required=True)

    trl = trsub.add_parser("list", help="list all trips (optionally filter by status)")
    trl.add_argument("--status", default=None, choices=["planned", "active", "completed", "cancelled"], help="filter by status")
    trl.set_defaults(func=_cmd_travel)

    tra = trsub.add_parser("add", help="add a new trip")
    tra.add_argument("destination", help="trip destination (city, address, region)")
    tra.add_argument("--start-date", dest="start_date", help="start date YYYY-MM-DD")
    tra.add_argument("--end-date", dest="end_date", help="end date YYYY-MM-DD")
    tra.add_argument("--type", dest="trip_type", default="personal", choices=["personal", "work", "holiday", "family", "medical", "other"], help="trip type")
    tra.add_argument("--notes", help="free-text notes")
    tra.set_defaults(func=_cmd_travel)

    trs = trsub.add_parser("status", help="update trip status")
    trs.add_argument("trip_id", help="trip identifier")
    trs.add_argument("status", choices=["planned", "active", "completed", "cancelled"], help="new status")
    trs.set_defaults(func=_cmd_travel)

    tri = trsub.add_parser("itinerary", help="add an itinerary item to a trip")
    tri.add_argument("trip_id", help="trip identifier")
    tri.add_argument("activity", help="activity description")
    tri.add_argument("--day", type=int, default=1, help="day of trip (1-indexed)")
    tri.add_argument("--time", dest="time", help="time (e.g. '09:00', 'afternoon')")
    tri.add_argument("--location", help="where the activity takes place")
    tri.add_argument("--notes", help="notes for this activity")
    tri.set_defaults(func=_cmd_travel)


def _cmd_travel(args: argparse.Namespace) -> int:
    from hermes_ctl.intelligence.travel import (
        add_itinerary,
        add_trip,
        scan_trips,
        update_trip_status,
    )

    store = _store()

    if args.travel_action == "list":
        snap = scan_trips(store=store, status=args.status)
        print(f"Trips ({snap.total_count} total: {snap.planned_count} planned, {snap.active_count} active, {snap.completed_count} completed):")
        for t in snap.trips:
            dates = f"{t.start_date or '?'} → {t.end_date or '?'}"
            icon = {"planned": "📋", "active": "✈️", "completed": "✅", "cancelled": "❌"}.get(t.status, "📋")
            print(f"  {icon} {t.destination:30s} {t.status:12s} {dates}")
        if snap.upcoming:
            print(f"  Upcoming: {', '.join(t.destination for t in snap.upcoming)}")
        return 0

    if args.travel_action == "add":
        trip = add_trip(
            store,
            args.destination,
            start_date=args.start_date or "",
            end_date=args.end_date or "",
            trip_type=args.trip_type or "personal",
            notes=args.notes or "",
        )
        print(f"added trip: {trip.destination} (id={trip.id})")
        return 0

    if args.travel_action == "status":
        trip = update_trip_status(store, args.trip_id, args.status)
        if trip:
            print(f"updated {trip.destination} → {trip.status}")
            return 0
        print(f"(no trip with id {args.trip_id})", file=__import__("sys").stderr)
        return 1

    if args.travel_action == "itinerary":
        trip = add_itinerary(
            store,
            args.trip_id,
            args.activity,
            day=args.day,
            time_str=args.time or "",
            location=args.location or "",
            notes=args.notes or "",
        )
        if trip:
            print(f"added itinerary item to {trip.destination} (day {args.day})")
            return 0
        print(f"(no trip with id {args.trip_id})", file=__import__("sys").stderr)
        return 1

    return 2


# ---------------------------------------------------------------------------
# finance
# ---------------------------------------------------------------------------
def _build_finance_parser(sub) -> None:
    pf = sub.add_parser("finance", help="financial awareness (budgets, expenses, spend analysis)")
    fsub = pf.add_subparsers(dest="finance_action", required=True)

    fba = fsub.add_parser("add-budget", help="add or update a budget category")
    fba.add_argument("category", help="budget category (groceries, dining, transport, etc.)")
    fba.add_argument("--limit", type=float, required=True, help="monthly/weekly budget limit in $")
    fba.add_argument("--period", default="monthly", choices=["weekly", "monthly", "yearly"], help="budget period")
    fba.set_defaults(func=_cmd_finance)

    fea = fsub.add_parser("add-expense", help="log an expense")
    fea.add_argument("category", help="expense category")
    fea.add_argument("amount", type=float, help="amount spent in $")
    fea.add_argument("--description", help="what the expense was for")
    fea.add_argument("--date", help="date YYYY-MM-DD (default: today)")
    fea.set_defaults(func=_cmd_finance)

    fl_ = fsub.add_parser("list", help="show budgets vs spend, category breakdown")
    fl_.add_argument("--date", help="month to view (YYYY-MM-DD, default: today)")
    fl_.add_argument("--budgets-only", action="store_true", default=False, help="only show budgets")
    fl_.set_defaults(func=_cmd_finance)


def _cmd_finance(args: argparse.Namespace) -> int:
    store = _store()

    if args.finance_action == "add-budget":
        try:
            budget = add_budget(
                store,
                args.category,
                args.limit,
                period=args.period or "monthly",
            )
        except FinanceError as exc:
            print(f"budget error: {exc}", file=__import__("sys").stderr)
            return 1
        print(f"budget set: {budget.category} = ${budget.limit:.2f}/{budget.period}")
        return 0

    if args.finance_action == "add-expense":
        try:
            expense = add_expense(
                store,
                args.category,
                args.amount,
                description=args.description or "",
                date=args.date,
            )
        except FinanceError as exc:
            print(f"expense error: {exc}", file=__import__("sys").stderr)
            return 1
        print(f"expense logged: {expense.category} ${expense.amount:.2f} ({expense.date})")
        return 0

    if args.finance_action == "list":
        snap = scan_finances(
            store=store,
            date=args.date,
            budgets_only=args.budgets_only or False,
        )
        deliver_finances(snap, store=store)
        print(f"Financial Awareness — {snap.date}")
        print(f"  Budget: ${snap.total_budget:.2f} total")
        print(f"  Spent:  ${snap.total_spent:.2f} total")
        if snap.budgets:
            print(f"  Budgets ({len(snap.budgets)}):")
            for b in snap.budgets:
                flag = " ⚠️ OVER" if b.overspent else " ✅" if b.remaining > 0 else ""
                print(f"    {b.category:15s} ${b.spent:<8.2f} / ${b.limit:<8.2f}{flag}")
        if snap.overspent_categories:
            print(f"  ⚠️ Overspent: {', '.join(snap.overspent_categories)}")
        if snap.by_category:
            print(f"  By category ({len(snap.by_category)}):")
            for cat, data in sorted(snap.by_category.items()):
                print(f"    {cat:15s} ${data['total']:<8.2f} ({data['count']} txns, avg ${data['avg']:.2f})")
        if not snap.budgets and not snap.expenses:
            print("  (no financial data yet — add budgets and expenses)")
        return 0

# ---------------------------------------------------------------------------
# family-task
# ---------------------------------------------------------------------------


def _build_family_task_parser(sub) -> None:
    pft = sub.add_parser("family-task", help="family task management (list, add, complete, remove, update)")
    ftsub = pft.add_subparsers(dest="family_task_action", required=True)

    fl = ftsub.add_parser("list", help="list family tasks with optional filters")
    fl.add_argument("--category", help="filter by category (chore, errand, appointment, reminder, other)")
    fl.add_argument("--assignee", help="filter by assigned family member name")
    fl.add_argument("--overdue", action="store_true", default=False, help="show only overdue tasks")
    fl.add_argument("--due-today", action="store_true", default=False, help="show only tasks due today")
    fl.set_defaults(func=_cmd_family_task)

    fa = ftsub.add_parser("add", help="add a new family task")
    fa.add_argument("title", help="task title (required)")
    fa.add_argument("--desc", dest="description", help="longer description")
    fa.add_argument("--assignee", help="family member assigned to this task")
    fa.add_argument("--category", default="other", choices=["chore", "errand", "appointment", "reminder", "other"], help="task category")
    fa.add_argument("--priority", type=int, default=3, help="priority 1–5 (default: 3)")
    fa.add_argument("--due", type=int, default=0, help="due date as Unix timestamp")
    fa.add_argument("--recur", default="none", choices=["daily", "weekly", "monthly", "none"], help="recurrence pattern")
    fa.add_argument("--tag", action="append", help="tag (repeatable)")
    fa.set_defaults(func=_cmd_family_task)

    fc = ftsub.add_parser("complete", help="mark a family task as completed")
    fc.add_argument("task_id", help="task id to complete")
    fc.set_defaults(func=_cmd_family_task)

    fr = ftsub.add_parser("remove", help="delete a family task")
    fr.add_argument("task_id", help="task id to remove")
    fr.set_defaults(func=_cmd_family_task)

    fu = ftsub.add_parser("update", help="update fields on a family task")
    fu.add_argument("task_id", help="task id to update")
    fu.add_argument("--title", help="new title")
    fu.add_argument("--desc", dest="description", help="new description")
    fu.add_argument("--assignee", help="new assignee")
    fu.add_argument("--category", choices=["chore", "errand", "appointment", "reminder", "other"], help="new category")
    fu.add_argument("--priority", type=int, help="new priority 1–5")
    fu.add_argument("--due", type=int, help="new due date as Unix timestamp")
    fu.add_argument("--recur", choices=["daily", "weekly", "monthly", "none"], help="new recurrence pattern")
    fu.set_defaults(func=_cmd_family_task)


def _cmd_family_task(args: argparse.Namespace) -> int:
    from hermes_ctl.intelligence.family_tasks import (
        add_task,
        complete_task,
        deliver_family_tasks,
        remove_task,
        scan_family_tasks,
        update_task,
    )

    store = _store()
    action = args.family_task_action

    if action == "list":
        snap = scan_family_tasks(
            store=store,
            category=args.category,
            assignee=args.assignee,
            overdue_only=args.overdue or False,
            due_today_only=args.due_today or False,
        )
        print(f"Family tasks ({snap.total_count} total, {snap.overdue_count} overdue, {snap.due_today_count} due today):")
        print(f"  By category: {json.dumps(snap.by_category)}")
        print(f"  By assignee: {json.dumps(snap.by_assignee)}")
        print(f"  Completion rate: {snap.completion_rate:.0%}")
        for t in snap.tasks:
            status = "✅" if t.completed else "⬜"
            due = time.strftime("%Y-%m-%d", time.gmtime(t.due_date)) if t.due_date else "no date"
            assigned = f"  [{t.assigned_to}]" if t.assigned_to else ""
            print(f"  {status} {t.title:30s} pri={t.priority}  due={due}{assigned}  [{t.category}]")
        return 0

    if action == "add":
        task = add_task(
            store,
            args.title,
            description=args.description or "",
            assigned_to=args.assignee or "",
            category=args.category or "other",
            priority=args.priority or 3,
            due_date=args.due or 0,
            recurrence=args.recur or "none",
            tags=args.tag or [],
        )
        print(f"added family task: {task.title} (id={task.id})")
        return 0

    if action == "complete":
        task = complete_task(store, args.task_id)
        if task:
            print(f"completed: {task.title}")
            return 0
        print(f"(no task with id {args.task_id})", file=__import__("sys").stderr)
        return 1

    if action == "remove":
        ok = remove_task(store, args.task_id)
        if ok:
            print(f"removed task: {args.task_id}")
            return 0
        print(f"(no task with id {args.task_id})", file=__import__("sys").stderr)
        return 1

    if action == "update":
        kwargs = {}
        for key, attr in [("title", "title"), ("description", "description"),
                          ("assignee", "assigned_to"), ("category", "category"),
                          ("priority", "priority"), ("due", "due_date"),
                          ("recur", "recurrence")]:
            val = getattr(args, key, None)
            if val is not None:
                kwargs[attr] = val
        if not kwargs:
            print("(no fields to update — pass at least one --flag)", file=__import__("sys").stderr)
            return 1
        task = update_task(store, args.task_id, **kwargs)
        if task:
            print(f"updated: {task.title} (id={task.id})")
            return 0
        print(f"(no task with id {args.task_id})", file=__import__("sys").stderr)
        return 1

    return 2  # pragma: no cover
