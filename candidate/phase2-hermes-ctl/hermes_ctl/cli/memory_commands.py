"""Memory commands: search, remember, forget, curate, consolidate."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from hermes_ctl.cli.store import _store


def build_parser(sub) -> None:
    pm = sub.add_parser("memory", help="long-term + working memory")
    msub = pm.add_subparsers(dest="memory_action", required=True)

    sp = msub.add_parser("search")
    sp.add_argument("--tag")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=_cmd_memory)

    rp = msub.add_parser("remember")
    rp.add_argument("key")
    rp.add_argument("value")
    rp.add_argument("--tag", action="append")
    rp.set_defaults(func=_cmd_memory)

    fp = msub.add_parser("forget")
    fp.add_argument("key")
    fp.set_defaults(func=_cmd_memory)

    cp = msub.add_parser("curate", help="scan facts and rank by importance")
    cp.add_argument("--keep-threshold", type=float, default=0.5, dest="curate_keep_threshold")
    cp.add_argument("--archive-threshold", type=float, default=0.2, dest="curate_archive_threshold")
    cp.set_defaults(func=_cmd_memory)

    csol = msub.add_parser("consolidate", help="find similar facts and suggest merges")
    csol.add_argument("--threshold", type=float, default=0.7, dest="consolidate_threshold")
    csol.add_argument("--max-groups", type=int, default=10, dest="consolidate_max_groups")
    csol.set_defaults(func=_cmd_memory)


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
