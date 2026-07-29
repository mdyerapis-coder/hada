"""CRM commands: entities (add, find, list) + relationships (rel-*)."""

from __future__ import annotations

import argparse
import json
import time
import uuid

from hermes_ctl.cli.store import _store
from hermes_ctl.productivity.store import ProductivityStore, Entity


def build_parser(sub) -> None:
    pr_ = sub.add_parser("crm", help="CRM entities + relationships")
    crmsub = pr_.add_subparsers(dest="crm_action", required=True)

    crmsub.add_parser("list").set_defaults(func=_cmd_crm)

    cadd = crmsub.add_parser("add")
    cadd.add_argument("name")
    cadd.add_argument("--kind", default="person")
    cadd.set_defaults(func=_cmd_crm)

    cfind = crmsub.add_parser("find")
    cfind.add_argument("name")
    cfind.set_defaults(func=_cmd_crm)

    # Relationship subcommands
    r_add = crmsub.add_parser("rel-add", help="add a relationship")
    r_add.add_argument("name")
    r_add.add_argument("rel_type")
    r_add.add_argument("--notes", dest="rel_notes", default="")
    r_add.set_defaults(func=_cmd_crm)

    r_list = crmsub.add_parser("rel-list", help="list relationships")
    r_list.add_argument("--type", dest="rel_filter", default=None)
    r_list.set_defaults(func=_cmd_crm)

    r_log = crmsub.add_parser("rel-log", help="log an interaction")
    r_log.add_argument("name")
    r_log.add_argument("--channel", dest="rel_channel", default="")
    r_log.add_argument("--summary", dest="rel_summary", default="")
    r_log.set_defaults(func=_cmd_crm)

    r_rec = crmsub.add_parser("rel-recent", help="show recent interactions")
    r_rec.add_argument("name")
    r_rec.add_argument("--limit", type=int, default=10, dest="rel_limit")
    r_rec.set_defaults(func=_cmd_crm)

    r_dates = crmsub.add_parser("rel-dates", help="show upcoming important dates")
    r_dates.add_argument("--within", type=float, default=30, dest="rel_within")
    r_dates.set_defaults(func=_cmd_crm)


def _cmd_crm(args: argparse.Namespace) -> int:
    from hermes_ctl.intelligence.relationships import Relationships

    store = _store()
    crm = ProductivityStore(store)
    rel = Relationships(store)

    if args.crm_action == "list":
        print("(use 'crm find <name>' to look up; entities stored on demand)")
        return 0

    if args.crm_action == "add":
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
            print(f"failed: {exc}", file=__import__("sys").stderr)
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
            print(f"failed: {exc}", file=__import__("sys").stderr)
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
