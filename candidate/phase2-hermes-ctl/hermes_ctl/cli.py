"""Hermes CTL command-line interface (Phase 2 deployable surface).

Exposes the built foundation subsystems as operator commands:
  hermesctl memory  <search|remember|forget>   # long-term + working memory
  hermesctl inbox   <list|show>                 # inbound SMS/Email/Telegram
  hermesctl identity <show|set-pref>            # profile + preferences
  hermesctl tasks   <list|add>                  # productivity task store
  hermesctl notes   <add|list>                  # knowledge notes
  hermesctl calendar <add|upcoming>             # events
  hermesctl crm     <add|find>                  # entities
  hermesctl send    <email|telegram> --to X --body Y [--subject Z]
                                                # OUTBOUND (gated: secrets + egress)

Inbound state lives in the MemoryStore (JSON file). The `send` command reads
credentials from the SecretStore and checks egress via NetworkPolicy before
talking to the network — fail-closed.

Run:  python3 -m hermes_ctl.cli <subcommand> [args]
Env:  HERMES_CTL_STORE (store/inbox path)
      contact.env vars (GMAIL_SMTP_USER, GMAIL_APP_PASSWORD, TELEGRAM_BOT_TOKEN)
      for outbound send.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any
from hermes_ctl.communications.channels import Message
from hermes_ctl.communications.email_channel import EmailChannel
from hermes_ctl.communications.telegram import TelegramChannel
from hermes_ctl.identity.profile import Identity
from hermes_ctl.memory.store import MemoryStore
from hermes_ctl.productivity.store import ProductivityStore, Task
from hermes_ctl.secrets import (
    EnvSecretStore,
    SecretError,
    NetworkDenied,
    default_contact_policy,
)
from hermes_ctl.intelligence.brains import load_brains
from hermes_ctl.intelligence.briefing import (
    Briefing,
    BriefingError,
    generate_briefing,
    deliver_briefing,
)
from hermes_ctl.intelligence.finance import (
    FinancialSnapshot,
    FinanceError,
    add_budget,
    add_expense,
    scan_finances,
    deliver_finances,
)


def _store() -> MemoryStore:
    path = os.environ.get("HERMES_CTL_STORE", os.path.join(os.path.dirname(__file__), "..", ".comms", "inbox.json"))
    path = os.path.abspath(path)
    return MemoryStore(persist_path=path)


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------
def _cmd_memory(args: argparse.Namespace) -> int:
    store = _store()
    if args.memory_action == "search":
        facts = store.search(tag=args.tag) if args.tag else store.search()
        for f in facts[-args.limit :]:
            print(f"{f.id}\t{sorted(f.tags)}\t{json.dumps(f.value, ensure_ascii=False)[:120]}")
        return 0
    if args.memory_action == "remember":
        store.remember(args.key, json.loads(args.value), tags=tuple(args.tag or []))
        print(f"remembered {args.key}")
        return 0
    if args.memory_action == "forget":
        store.forget(args.key)
        print(f"forgot {args.key}")
        return 0
    if args.memory_action == "curate":
        return _cmd_memory_curate(store, args)
    if args.memory_action == "consolidate":
        return _cmd_memory_consolidate(store, args)
    return 2


def _cmd_memory_curate(store: Any, args: argparse.Namespace) -> int:
    """Scan facts and print curation suggestions."""
    from hermes_ctl.intelligence.curation import curate

    try:
        suggestions = curate(
            store,
            keep_threshold=args.curate_keep_threshold,
            archive_threshold=args.curate_archive_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"curation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Curation suggestions ({len(suggestions)} facts):")
    for s in suggestions:
        icon = {"keep": "✅", "review": "⚠️", "archive": "🗑️"}.get(s.suggestion, "❓")
        print(f"  {icon} {s.fact_id:30s} {s.composite_score:.2f}  {s.reason}")
    return 0


def _cmd_memory_consolidate(store: Any, args: argparse.Namespace) -> int:
    """Scan facts and suggest consolidations."""
    from hermes_ctl.intelligence.curation import consolidate

    try:
        actions = consolidate(
            store,
            similarity_threshold=args.consolidate_threshold,
            max_groups=args.consolidate_max_groups,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"consolidation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Consolidation suggestions ({len(actions)} group(s)):")
    for a in actions:
        print(f"  🔗 {a.relation}: {a.target_id} <- {', '.join(a.source_ids)}")
        print(f"     {a.description[:100]}")
    return 0


# ---------------------------------------------------------------------------
# inbox
# ---------------------------------------------------------------------------
def _cmd_inbox(args: argparse.Namespace) -> int:
    store = _store()
    inbox = store.search(tag="inbox")
    if args.channel:
        inbox = [f for f in inbox if f.value.get("channel") == args.channel]
    inbox = inbox[-args.limit :]
    if args.inbox_action == "list":
        for f in inbox:
            v = f.value
            print(f"[{v.get('channel')}] {v.get('sender')}: {v.get('body','')[:60]}")
        return 0
    if args.inbox_action == "show":
        if not inbox:
            print("(empty)")
            return 0
        print(json.dumps(inbox[-1].value, indent=2, ensure_ascii=False))
        return 0
    return 2


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------
def _cmd_identity(args: argparse.Namespace) -> int:
    store = _store()
    ident = Identity(store)
    if args.identity_action == "show":
        out = {
            "profile": ident.get_profile(),
            "preferences": ident.all_preferences(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    if args.identity_action == "set-pref":
        ident.set_preference(args.key, args.value)
        print(f"pref {args.key} = {args.value}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
def _cmd_tasks(args: argparse.Namespace) -> int:
    store = _store()
    tasks = ProductivityStore(store)
    if args.task_action == "list":
        for t in tasks.list_tasks(only_open=True):
            print(f"{t.id}\t[{'x' if t.done else ' '}]\t{t.title}")
        return 0
    if args.task_action == "add":
        import uuid
        task = Task(id=uuid.uuid4().hex[:8], title=args.title)
        tasks.add_task(task)
        print(f"added task {task.id}: {task.title}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------
def _cmd_notes(args: argparse.Namespace) -> int:
    store = _store()
    notes = ProductivityStore(store)
    if args.note_action == "list":
        for n in notes.search_notes(tag=args.tag):
            print(f"{n.id}\t{n.title}")
        return 0
    if args.note_action == "add":
        import uuid
        from hermes_ctl.productivity.store import Note
        note = Note(id=uuid.uuid4().hex[:8], title=args.title, body=args.body or "")
        notes.add_note(note)
        print(f"added note {note.id}: {note.title}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------
def _cmd_calendar(args: argparse.Namespace) -> int:
    store = _store()
    cal = ProductivityStore(store)
    if args.cal_action == "upcoming":
        for e in cal.upcoming_events(within=args.within):
            print(f"{e.id}\t{e.title}\t{__import__('time').ctime(e.start)}")
        return 0
    if args.cal_action == "add":
        import time
        import uuid
        from hermes_ctl.productivity.store import Event
        start = time.time() + (args.in_days * 86400)
        ev = Event(id=uuid.uuid4().hex[:8], title=args.title, start=start, end=start + 3600)
        cal.add_event(ev)
        print(f"added event {ev.id}: {ev.title}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# crm
# ---------------------------------------------------------------------------
def _cmd_crm(args: argparse.Namespace) -> int:
    from hermes_ctl.intelligence.relationships import Relationships
    store = _store()
    crm = ProductivityStore(store)
    rel = Relationships(store)
    if args.crm_action == "list":
        print("(use 'crm find <name>' to look up; entities stored on demand)")
        return 0
    if args.crm_action == "add":
        import uuid
        from hermes_ctl.productivity.store import Entity
        ent = Entity(id=uuid.uuid4().hex[:8], name=args.name, kind=args.kind, fields={})
        crm.add_entity(ent)
        print(f"added entity {ent.id}: {ent.name} ({ent.kind})")
        return 0
    if args.crm_action == "find":
        ent = crm.find_entity(args.name)
        if ent:
            print(json.dumps(ent.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"(no entity named {args.name})")
        return 0
    if args.crm_action == "rel-add":
        try:
            r = rel.add(args.name, args.rel_type, notes=args.rel_notes or "")
        except Exception as exc:  # noqa: BLE001
            print(f"failed: {exc}", file=sys.stderr)
            return 1
        print(f"relationship added: {r.person} ({r.relation})")
        return 0
    if args.crm_action == "rel-list":
        items = rel.list(relation=getattr(args, "rel_filter", None))
        if not items:
            print("(no relationships)")
            return 0
        for r in items:
            since = time.strftime("%Y-%m-%d", time.gmtime(r.since)) if r.since else "?"
            print(f"  {r.person:20s} {r.relation:12s} since {since}  {r.notes}")
            if r.important_dates:
                for label, d in r.important_dates.items():
                    print(f"    {label}: {d}")
        return 0
    if args.crm_action == "rel-log":
        try:
            i = rel.log_interaction(args.name, channel=args.rel_channel or "", summary=args.rel_summary or "")
        except Exception as exc:  # noqa: BLE001
            print(f"failed: {exc}", file=sys.stderr)
            return 1
        print(f"interaction logged: {i.person} ({i.channel})")
        return 0
    if args.crm_action == "rel-recent":
        items = rel.interactions(person=args.name, limit=args.rel_limit)
        if not items:
            print(f"(no interactions for {args.name})")
            return 0
        for i in items:
            when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(i.timestamp))
            print(f"  [{when}] {i.channel or '?'}: {i.summary}")
        return 0
    if args.crm_action == "rel-dates":
        items = rel.upcoming_dates(within_days=args.rel_within)
        if not items:
            print("(no upcoming dates)")
            return 0
        for d in items:
            print(f"  {d['person']:20s} {d['label']:12s} {d['date']:15s} in {d['daysUntil']} day(s)")
        return 0
    return 2


# ---------------------------------------------------------------------------
# send (OUTBOUND — gated by secrets + egress policy)
# ---------------------------------------------------------------------------
def _cmd_send(args: argparse.Namespace) -> int:
    secrets = EnvSecretStore()
    net = default_contact_policy()
    try:
        if args.send_channel == "email":
            net.require("smtps://smtp.gmail.com:465")
            user = secrets.get("GMAIL_SMTP_USER")
            pw = secrets.get("GMAIL_APP_PASSWORD")
            ch = EmailChannel(user=user, password=pw)
            msg = Message(channel="email", sender=user, recipient=args.to, subject=args.subject, body=args.body)
        elif args.send_channel == "telegram":
            net.require("https://api.telegram.org:443")
            token = secrets.get("TELEGRAM_BOT_TOKEN")
            ch = TelegramChannel(token=token)
            msg = Message(channel="telegram", sender="bot", recipient=args.to, body=args.body)
        else:  # pragma: no cover - argparse enforces choices
            print(f"unknown send channel: {args.send_channel}", file=sys.stderr)
            return 2
    except (SecretError, NetworkDenied) as exc:
        print(f"send blocked: {exc}", file=sys.stderr)
        return 1

    try:
        ref = ch.send(msg)
    except Exception as exc:  # noqa: BLE001 - surface the network failure clearly
        print(f"send failed: {exc}", file=sys.stderr)
        return 1
    print(f"sent [{args.send_channel}] -> {args.to} (ref {ref})")
    return 0


def _cmd_brains(args: argparse.Namespace) -> int:
    try:
        brains = load_brains()
    except (ValueError, FileNotFoundError) as exc:
        print(f"brains config error: {exc}", file=sys.stderr)
        return 1
    for b in brains:
        print(f"{b.role:7} {b.url}  model={b.model}")
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    """Show current system context snapshot (read-only, no network)."""
    from hermes_ctl.intelligence.context import scan_context, deliver_context

    plans_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "dreams"))
    try:
        ctx = scan_context(store=_store(), plans_dir=plans_dir)
        # persist the snapshot for downstream consumers
        deliver_context(ctx, store=_store())
    except Exception as exc:  # noqa: BLE001 - surface collection failures cleanly
        print(f"context scan failed: {exc}", file=sys.stderr)
        return 1
    import json as _json
    print(_json.dumps(ctx.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _cmd_briefing(args: argparse.Namespace) -> int:
    if args.briefing_action == "validate":
        try:
            data = json.load(open(args.file, encoding="utf-8"))
            b = Briefing.from_dict(data)
            from hermes_ctl.intelligence.briefing import validate_briefing
            validate_briefing(b)  # raises BriefingError on schema violation
        except (BriefingError, KeyError, ValueError) as exc:
            print(f"INVALID briefing: {exc}", file=sys.stderr)
            return 1
        print("OK: briefing schema valid")
        return 0
    if args.briefing_action == "run":
        # Gated: requires a live brain (Phase 3 inference).
        try:
            brains = load_brains()
        except (ValueError, FileNotFoundError) as exc:
            print(f"brains config error: {exc}", file=sys.stderr)
            return 1
        from hermes_ctl.intelligence.briefing import run_briefing
        from hermes_ctl.intelligence.http_router import HttpRouter
        try:
            dreams_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "dreams"))
            path = run_briefing(
                brains=HttpRouter(brains),
                store=_store(),
                dreams_dir=dreams_dir,
            )
        except Exception as exc:  # noqa: BLE001 - surface inference/delivery failures cleanly
            print(f"briefing run failed: {exc}", file=sys.stderr)
            return 1
        print(f"briefing delivered: {path}")
        # Telegram summary if requested
        if getattr(args, "briefing_telegram", False):
            _deliver_briefing_telegram(dreams_dir, path)
        return 0
    return 2  # pragma: no cover


def _deliver_briefing_telegram(dreams_dir: str, path: str) -> None:
    """Send a briefing summary to Telegram Home channel."""
    import glob
    try:
        from hermes_ctl.communications.telegram import TelegramChannel
        from hermes_ctl.communications.channels import Message
        # Use the delivered path or find latest dream
        fp = path
        if not fp or fp == "memory":
            files = sorted(glob.glob(os.path.join(dreams_dir, "dream-*.json")), reverse=True)
            if not files:
                return
            fp = files[0]
        if not os.path.isfile(fp):
            return
        data = json.load(open(fp))
        chat = os.environ.get("HERMES_TELEGRAM_CHAT", "7620778176")
        lines = [f"*Daily Briefing — {data.get('date', '?')}*"]
        for p in data.get("prescriptions", []):
            lines.append(f"\n*{p.get('cat', '?')}*: {p.get('headline', '')}")
        TelegramChannel().send(Message(channel="briefing", sender="hada", recipient=chat, body="\n".join(lines)))
    except Exception as exc:
        print(f"telegram delivery skipped: {exc}", file=sys.stderr)


def _cmd_plan(args: argparse.Namespace) -> int:
    if args.plan_action == "validate":
        try:
            data = json.load(open(args.file, encoding="utf-8"))
            from hermes_ctl.intelligence.plan import Plan, validate_plan
            validate_plan(Plan.from_dict(data))
        except Exception as exc:  # noqa: BLE001
            print(f"INVALID plan: {exc}", file=sys.stderr)
            return 1
        print("OK: plan schema valid")
        return 0
    if args.plan_action == "run":
        # Gated: requires a live brain (Phase 3 inference).
        try:
            brains = load_brains()
        except (ValueError, FileNotFoundError) as exc:
            print(f"brains config error: {exc}", file=sys.stderr)
            return 1
        from hermes_ctl.intelligence.plan import run_plan
        from hermes_ctl.intelligence.http_router import HttpRouter
        try:
            plans_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "dreams"))
            path = run_plan(
                brains=HttpRouter(brains),
                store=_store(),
                plans_dir=plans_dir,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"plan run failed: {exc}", file=sys.stderr)
            return 1
        print(f"plan delivered: {path}")
        if getattr(args, "plan_telegram", False):
            _deliver_plan_telegram(plans_dir, path)
        return 0
    return 2  # pragma: no cover


def _deliver_plan_telegram(plans_dir: str, path: str) -> None:
    """Send a plan summary to Telegram Home channel."""
    import glob
    try:
        from hermes_ctl.communications.telegram import TelegramChannel
        from hermes_ctl.communications.channels import Message
        fp = path
        if not fp or fp == "memory":
            files = sorted(glob.glob(os.path.join(plans_dir, "plan-*.json")), reverse=True)
            if not files:
                return
            fp = files[0]
        if not os.path.isfile(fp):
            return
        data = json.load(open(fp))
        chat = os.environ.get("HERMES_TELEGRAM_CHAT", "7620778176")
        lines = [f"*Daily Plan — {data.get('date', '?')}*\n{data.get('headline', '')}"]
        for item in data.get("items", []):
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.get("priority", ""), "⚪")
            lines.append(f"\n{icon} {item.get('time', 'anytime')} — {item.get('task', '')}")
        TelegramChannel().send(Message(channel="plan", sender="hada", recipient=chat, body="\n".join(lines)))
    except Exception as exc:
        print(f"telegram delivery skipped: {exc}", file=sys.stderr)


def _cmd_remind(args: argparse.Namespace) -> int:
    if args.remind_action == "run":
        from hermes_ctl.intelligence.remind import run_remind
        try:
            plans_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "dreams"))
            telegram_chat = os.environ.get("HERMES_TELEGRAM_CHAT", "7620778176")
            count = run_remind(plans_dir=plans_dir, telegram_chat=telegram_chat, store=_store())
        except Exception as exc:  # noqa: BLE001
            print(f"remind run failed: {exc}", file=sys.stderr)
            return 1
        print(f"remind delivered: {count} reminder(s) sent")
        return 0
    return 2  # pragma: no cover


# ---------------------------------------------------------------------------
# relationship
# ---------------------------------------------------------------------------
def _cmd_relationship(args: argparse.Namespace) -> int:
    store = _store()
    from hermes_ctl.intelligence.relationships import (
        scan_relationships,
        update_relationship,
        record_interaction,
    )

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
# shopping
# ---------------------------------------------------------------------------
def _cmd_shopping(args: argparse.Namespace) -> int:
    store = _store()
    from hermes_ctl.intelligence.shopping import (
        ShoppingSnapshot,
        add_item,
        remove_item,
        mark_purchased,
        clear_purchased,
        scan_shopping,
    )

    if args.shop_action == "list":
        snap = scan_shopping(
            store=store,
            list_name=args.list,
            active_only=args.active_only,
        )
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
        print(f"(no item named {args.name} in list {args.list or 'main'})", file=sys.stderr)
        return 1

    if args.shop_action == "buy":
        ok = mark_purchased(store, args.name, list_name=args.list or "main", purchased=True)
        if ok:
            print(f"marked purchased: {args.name}")
            return 0
        print(f"(no item named {args.name})", file=sys.stderr)
        return 1

    if args.shop_action == "clear":
        count = clear_purchased(store, list_name=args.list)
        print(f"cleared {count} purchased item(s)")
        return 0

# travel
# ---------------------------------------------------------------------------
def _cmd_travel(args: argparse.Namespace) -> int:
    store = _store()
    from hermes_ctl.intelligence.travel import (
        TravelTrip,
        add_itinerary,
        add_trip,
        scan_trips,
        update_trip_status,
    )

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
        print(f"(no trip with id {args.trip_id})", file=sys.stderr)
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
        print(f"(no trip with id {args.trip_id})", file=sys.stderr)
        return 1

# finance
# ---------------------------------------------------------------------------
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
            print(f"budget error: {exc}", file=sys.stderr)
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
            print(f"expense error: {exc}", file=sys.stderr)
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

    return 2  # pragma: no cover


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hermesctl", description="Hermes CTL CLI (Phase 2 foundation surface)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("memory", help="long-term + working memory")
    msub = pm.add_subparsers(dest="memory_action", required=True)
    sp = msub.add_parser("search"); sp.add_argument("--tag"); sp.add_argument("--limit", type=int, default=20); sp.set_defaults(func=_cmd_memory)
    rp = msub.add_parser("remember"); rp.add_argument("key"); rp.add_argument("value"); rp.add_argument("--tag", action="append"); rp.set_defaults(func=_cmd_memory)
    fp = msub.add_parser("forget"); fp.add_argument("key"); fp.set_defaults(func=_cmd_memory)
    cp = msub.add_parser("curate", help="scan facts and rank by importance")
    cp.add_argument("--keep-threshold", type=float, default=0.5, dest="curate_keep_threshold")
    cp.add_argument("--archive-threshold", type=float, default=0.2, dest="curate_archive_threshold")
    cp.set_defaults(func=_cmd_memory)
    csol = msub.add_parser("consolidate", help="find similar facts and suggest merges")
    csol.add_argument("--threshold", type=float, default=0.7, dest="consolidate_threshold")
    csol.add_argument("--max-groups", type=int, default=10, dest="consolidate_max_groups")
    csol.set_defaults(func=_cmd_memory)
    pi = sub.add_parser("inbox", help="inbound SMS/Email/Telegram")
    isub = pi.add_subparsers(dest="inbox_action", required=True)
    lp = isub.add_parser("list"); lp.add_argument("--channel"); lp.add_argument("--limit", type=int, default=20); lp.set_defaults(func=_cmd_inbox)
    sp2 = isub.add_parser("show"); sp2.add_argument("--limit", type=int, default=1); sp2.add_argument("--channel"); sp2.set_defaults(func=_cmd_inbox)

    pn = sub.add_parser("identity", help="profile + preferences")
    nsub = pn.add_subparsers(dest="identity_action", required=True)
    nsub.add_parser("show").set_defaults(func=_cmd_identity)
    spp = nsub.add_parser("set-pref"); spp.add_argument("key"); spp.add_argument("value"); spp.set_defaults(func=_cmd_identity)

    pt = sub.add_parser("tasks", help="productivity task store")
    tsub = pt.add_subparsers(dest="task_action", required=True)
    tsub.add_parser("list").set_defaults(func=_cmd_tasks)
    tap = tsub.add_parser("add"); tap.add_argument("title"); tap.set_defaults(func=_cmd_tasks)

    pn_ = sub.add_parser("notes", help="note store")
    ntsub = pn_.add_subparsers(dest="note_action", required=True)
    nlp = ntsub.add_parser("list"); nlp.add_argument("--tag"); nlp.set_defaults(func=_cmd_notes)
    nap = ntsub.add_parser("add"); nap.add_argument("title"); nap.add_argument("--body"); nap.set_defaults(func=_cmd_notes)

    pc = sub.add_parser("calendar", help="calendar events")
    calsub = pc.add_subparsers(dest="cal_action", required=True)
    cup = calsub.add_parser("upcoming"); cup.add_argument("--within", type=float, default=None); cup.set_defaults(func=_cmd_calendar)
    cap = calsub.add_parser("add"); cap.add_argument("title"); cap.add_argument("--in-days", type=float, default=1.0); cap.set_defaults(func=_cmd_calendar)

    pr_ = sub.add_parser("crm", help="CRM entities + relationships")
    crmsub = pr_.add_subparsers(dest="crm_action", required=True)
    crmsub.add_parser("list").set_defaults(func=_cmd_crm)
    cadd = crmsub.add_parser("add"); cadd.add_argument("name"); cadd.add_argument("--kind", default="person"); cadd.set_defaults(func=_cmd_crm)
    cfind = crmsub.add_parser("find"); cfind.add_argument("name"); cfind.set_defaults(func=_cmd_crm)
    # Relationship subcommands
    r_add = crmsub.add_parser("rel-add", help="add a relationship")
    r_add.add_argument("name"); r_add.add_argument("rel_type"); r_add.add_argument("--notes", dest="rel_notes", default="")
    r_add.set_defaults(func=_cmd_crm)
    r_list = crmsub.add_parser("rel-list", help="list relationships")
    r_list.add_argument("--type", dest="rel_filter", default=None); r_list.set_defaults(func=_cmd_crm)
    r_log = crmsub.add_parser("rel-log", help="log an interaction")
    r_log.add_argument("name"); r_log.add_argument("--channel", dest="rel_channel", default=""); r_log.add_argument("--summary", dest="rel_summary", default="")
    r_log.set_defaults(func=_cmd_crm)
    r_rec = crmsub.add_parser("rel-recent", help="show recent interactions")
    r_rec.add_argument("name"); r_rec.add_argument("--limit", type=int, default=10, dest="rel_limit")
    r_rec.set_defaults(func=_cmd_crm)
    r_dates = crmsub.add_parser("rel-dates", help="show upcoming important dates")
    r_dates.add_argument("--within", type=float, default=30, dest="rel_within")
    r_dates.set_defaults(func=_cmd_crm)

    ps = sub.add_parser("send", help="OUTBOUND message (gated: secrets + egress)")
    ssub = ps.add_subparsers(dest="send_channel", required=True)
    sem = ssub.add_parser("email"); sem.add_argument("--to", required=True); sem.add_argument("--subject", default="(no subject)"); sem.add_argument("--body", required=True); sem.set_defaults(func=_cmd_send)
    stg = ssub.add_parser("telegram"); stg.add_argument("--to", required=True, help="chat id"); stg.add_argument("--body", required=True); stg.set_defaults(func=_cmd_send)

    pb = sub.add_parser("brains", help="list configured llmfit brains (HADA inference backend)")
    pb.set_defaults(func=_cmd_brains)

    pcx = sub.add_parser("context", help="show current system context snapshot")
    pcx.set_defaults(func=_cmd_context)

    pbr = sub.add_parser("briefing", help="Dream-style daily briefing (validate | run)")
    brsub = pbr.add_subparsers(dest="briefing_action", required=True)
    brv = brsub.add_parser("validate", help="check a briefing JSON against the strict schema (offline)")
    brv.add_argument("file", help="path to dream-{date}.json")
    brv.set_defaults(func=_cmd_briefing)
    brr = brsub.add_parser("run", help="generate + deliver today's briefing (gated: live inference)")
    brr.add_argument("--telegram", action="store_true", dest="briefing_telegram", help="also send summary to Telegram")
    brr.set_defaults(func=_cmd_briefing)

    ppl = sub.add_parser("plan", help="daily plan from briefing + inbox (validate | run)")
    plsub = ppl.add_subparsers(dest="plan_action", required=True)
    plv = plsub.add_parser("validate", help="check a plan JSON against the strict schema (offline)")
    plv.add_argument("file", help="path to plan-{date}.json")
    plv.set_defaults(func=_cmd_plan)
    plr = plsub.add_parser("run", help="generate + deliver today's plan (gated: live inference)")
    plr.add_argument("--telegram", action="store_true", dest="plan_telegram", help="also send summary to Telegram")
    plr.set_defaults(func=_cmd_plan)

    prm = sub.add_parser("remind", help="smart reminders from daily plan (remind run)")
    rmsub = prm.add_subparsers(dest="remind_action", required=True)
    rmr = rmsub.add_parser("run", help="check plan items due, send pending reminders to Telegram")
    rmr.set_defaults(func=_cmd_remind)

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

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
