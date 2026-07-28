"""Hermes CTL command-line interface (Phase 2 deployable surface).

Exposes the built foundation subsystems as offline, no-secret commands:
  hermesctl memory  <search|remember|forget>   # long-term + working memory
  hermesctl inbox   <list|show>                 # inbound SMS/Email/Telegram
  hermesctl identity <show|set-pref>            # profile + preferences
  hermesctl tasks   <list|add>                  # productivity task store

All state lives in the MemoryStore (JSON file). No network, no creds.
This is the "operating surface" that makes the foundation usable day-to-day.

Run:  python3 -m hermes_ctl.cli <subcommand> [args]
Env:  HERMES_CTL_STORE (default: .comms/inbox.json is the inbox; the store path
      is the same file — memory + inbox share one MemoryStore document).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from hermes_ctl.identity.profile import Identity
from hermes_ctl.memory.store import MemoryStore
from hermes_ctl.productivity.store import ProductivityStore, Task


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
    return 2


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hermesctl", description="Hermes CTL CLI (Phase 2 foundation surface)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("memory", help="long-term + working memory")
    msub = pm.add_subparsers(dest="memory_action", required=True)
    sp = msub.add_parser("search"); sp.add_argument("--tag"); sp.add_argument("--limit", type=int, default=20); sp.set_defaults(func=_cmd_memory)
    rp = msub.add_parser("remember"); rp.add_argument("key"); rp.add_argument("value"); rp.add_argument("--tag", action="append"); rp.set_defaults(func=_cmd_memory)
    fp = msub.add_parser("forget"); fp.add_argument("key"); fp.set_defaults(func=_cmd_memory)

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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
