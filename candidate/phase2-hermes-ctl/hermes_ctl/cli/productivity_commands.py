"""Productivity commands: tasks, notes, calendar."""

from __future__ import annotations

import argparse
import uuid

from hermes_ctl.cli.store import _store
from hermes_ctl.productivity.store import ProductivityStore, Task, Note, Event


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
def _build_tasks_parser(sub) -> None:
    pt = sub.add_parser("tasks", help="productivity task store")
    tsub = pt.add_subparsers(dest="task_action", required=True)
    tsub.add_parser("list").set_defaults(func=_cmd_tasks)
    tap = tsub.add_parser("add")
    tap.add_argument("title")
    tap.set_defaults(func=_cmd_tasks)


def _cmd_tasks(args: argparse.Namespace) -> int:
    store = _store()
    tasks = ProductivityStore(store)
    if args.task_action == "list":
        for t in tasks.list_tasks(only_open=True):
            print(f"{t.id}\t[{'x' if t.done else ' '}]\t{t.title}")
        return 0
    if args.task_action == "add":
        task = Task(id=uuid.uuid4().hex[:8], title=args.title)
        tasks.add_task(task)
        print(f"added task {task.id}: {task.title}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------
def _build_notes_parser(sub) -> None:
    pn_ = sub.add_parser("notes", help="note store")
    ntsub = pn_.add_subparsers(dest="note_action", required=True)
    nlp = ntsub.add_parser("list")
    nlp.add_argument("--tag")
    nlp.set_defaults(func=_cmd_notes)
    nap = ntsub.add_parser("add")
    nap.add_argument("title")
    nap.add_argument("--body")
    nap.set_defaults(func=_cmd_notes)


def _cmd_notes(args: argparse.Namespace) -> int:
    store = _store()
    notes = ProductivityStore(store)
    if args.note_action == "list":
        for n in notes.search_notes(tag=args.tag):
            print(f"{n.id}\t{n.title}")
        return 0
    if args.note_action == "add":
        note = Note(id=uuid.uuid4().hex[:8], title=args.title, body=args.body or "")
        notes.add_note(note)
        print(f"added note {note.id}: {note.title}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------
def _build_calendar_parser(sub) -> None:
    pc = sub.add_parser("calendar", help="calendar events")
    calsub = pc.add_subparsers(dest="cal_action", required=True)
    cup = calsub.add_parser("upcoming")
    cup.add_argument("--within", type=float, default=None)
    cup.set_defaults(func=_cmd_calendar)
    cap = calsub.add_parser("add")
    cap.add_argument("title")
    cap.add_argument("--in-days", type=float, default=1.0)
    cap.set_defaults(func=_cmd_calendar)


def _cmd_calendar(args: argparse.Namespace) -> int:
    store = _store()
    cal = ProductivityStore(store)
    if args.cal_action == "upcoming":
        for e in cal.upcoming_events(within=args.within):
            print(f"{e.id}\t{e.title}\t{__import__('time').ctime(e.start)}")
        return 0
    if args.cal_action == "add":
        import time

        start = time.time() + (args.in_days * 86400)
        ev = Event(id=uuid.uuid4().hex[:8], title=args.title, start=start, end=start + 3600)
        cal.add_event(ev)
        print(f"added event {ev.id}: {ev.title}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# aggregate builder
# ---------------------------------------------------------------------------
def build_parser(sub) -> None:
    _build_tasks_parser(sub)
    _build_notes_parser(sub)
    _build_calendar_parser(sub)
