"""Inbox commands: list, show."""

from __future__ import annotations

import argparse
import json

from hermes_ctl.cli.store import _store


def build_parser(sub) -> None:
    pi = sub.add_parser("inbox", help="inbound SMS/Email/Telegram")
    isub = pi.add_subparsers(dest="inbox_action", required=True)

    lp = isub.add_parser("list")
    lp.add_argument("--channel")
    lp.add_argument("--limit", type=int, default=20)
    lp.set_defaults(func=_cmd_inbox)

    sp2 = isub.add_parser("show")
    sp2.add_argument("--limit", type=int, default=1)
    sp2.add_argument("--channel")
    sp2.set_defaults(func=_cmd_inbox)


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
