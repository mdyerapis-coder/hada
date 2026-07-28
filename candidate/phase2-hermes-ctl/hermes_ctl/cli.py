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
    store = _store()
    crm = ProductivityStore(store)
    if args.crm_action == "list":
        # list all entities via find by scanning (ProductivityStore has no list_all;
        # iterate by searching known names is not feasible, so expose find + add)
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

    pr_ = sub.add_parser("crm", help="CRM entities")
    crmsub = pr_.add_subparsers(dest="crm_action", required=True)
    crmsub.add_parser("list").set_defaults(func=_cmd_crm)
    cadd = crmsub.add_parser("add"); cadd.add_argument("name"); cadd.add_argument("--kind", default="person"); cadd.set_defaults(func=_cmd_crm)
    cfind = crmsub.add_parser("find"); cfind.add_argument("name"); cfind.set_defaults(func=_cmd_crm)

    ps = sub.add_parser("send", help="OUTBOUND message (gated: secrets + egress)")
    ssub = ps.add_subparsers(dest="send_channel", required=True)
    sem = ssub.add_parser("email"); sem.add_argument("--to", required=True); sem.add_argument("--subject", default="(no subject)"); sem.add_argument("--body", required=True); sem.set_defaults(func=_cmd_send)
    stg = ssub.add_parser("telegram"); stg.add_argument("--to", required=True, help="chat id"); stg.add_argument("--body", required=True); stg.set_defaults(func=_cmd_send)

    pb = sub.add_parser("brains", help="list configured llmfit brains (HADA inference backend)")
    pb.set_defaults(func=_cmd_brains)

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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
