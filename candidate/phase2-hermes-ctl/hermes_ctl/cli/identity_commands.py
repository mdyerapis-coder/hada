"""Identity commands: show, set-pref."""

from __future__ import annotations

import argparse
import json

from hermes_ctl.cli.store import _store
from hermes_ctl.identity.profile import Identity


def build_parser(sub) -> None:
    pn = sub.add_parser("identity", help="profile + preferences")
    nsub = pn.add_subparsers(dest="identity_action", required=True)
    nsub.add_parser("show").set_defaults(func=_cmd_identity)
    spp = nsub.add_parser("set-pref")
    spp.add_argument("key")
    spp.add_argument("value")
    spp.set_defaults(func=_cmd_identity)


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
