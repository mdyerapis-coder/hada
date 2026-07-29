"""Information subsystem commands: index, search, status.

Wires the FileIndex into the CLI for local file metadata + content hash indexing.
"""

from __future__ import annotations

import argparse
import os

from hermes_ctl.cli.store import _store


def build_parser(sub) -> None:
    pi = sub.add_parser("information", help="local file indexing and search (offline)")
    isub = pi.add_subparsers(dest="info_action", required=True)

    ip = isub.add_parser("index", help="index a file or directory into MemoryStore")
    ip.add_argument("path", help="file or directory path to index")
    ip.add_argument("--recursive", action="store_true", default=False, help="recurse into subdirectories")
    ip.set_defaults(func=_cmd_information)

    sp = isub.add_parser("search", help="search indexed file records")
    sp.add_argument("query", help="search terms")
    sp.set_defaults(func=_cmd_information)

    stp = isub.add_parser("status", help="show file index stats")
    stp.set_defaults(func=_cmd_information)


def _cmd_information(args: argparse.Namespace) -> int:
    from hermes_ctl.information.index import FileIndex, SearchIndex

    store = _store()
    fi = FileIndex(store)
    si = SearchIndex(store)

    if args.info_action == "index":
        path = args.path
        if not os.path.exists(path):
            print(f"path not found: {path}", file=__import__("sys").stderr)
            return 1

        targets = []
        if os.path.isfile(path):
            targets = [path]
        elif os.path.isdir(path):
            if args.recursive:
                for root, _dirs, files in os.walk(path):
                    for f in files:
                        targets.append(os.path.join(root, f))
            else:
                targets = [os.path.join(path, f) for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]

        indexed = 0
        errors = 0
        for fp in targets:
            try:
                rec = fi.index_file(fp)
                si.index(rec.path, rec.path)
                indexed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  error indexing {fp}: {exc}", file=__import__("sys").stderr)
                errors += 1

        print(f"indexed {indexed} file(s) ({errors} error(s))")
        return 0 if errors == 0 else 1

    if args.info_action == "search":
        results = si.search(args.query)
        if not results:
            print("(no results)")
            return 0
        for r in results:
            rec = fi.get(r)
            if rec:
                size_str = f"{rec.size:,} bytes" if rec.size < 1024 else f"{rec.size / 1024:.1f} KB"
                print(f"  {rec.path:60s} {size_str:15s} {rec.sha256[:16]}...")
            else:
                print(f"  {r}")
        print(f"  ({len(results)} result(s))")
        return 0

    if args.info_action == "status":
        all_files = fi.all()
        total = len(all_files)
        total_size = sum(f.size for f in all_files)
        size_str = f"{total_size:,} bytes" if total_size < 1024 * 1024 else f"{total_size / (1024 * 1024):.1f} MB"
        print(f"File Index Status")
        print(f"  Total files: {total}")
        print(f"  Total size:  {size_str}")
        if all_files:
            print(f"  Latest file: {max(all_files, key=lambda f: f.mtime).path}")
        si_results = si.search("")
        print(f"  Search terms: {len(si_results)}")
        return 0

    return 2
