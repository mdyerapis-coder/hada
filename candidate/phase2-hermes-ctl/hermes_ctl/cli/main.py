"""Main entry point: assembles all subcommand parsers and dispatches."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hermesctl", description="Hermes CTL CLI (Phase 2 unified surface)")
    sub = p.add_subparsers(dest="cmd", required=True)

    from hermes_ctl.cli.memory_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.inbox_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.identity_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.productivity_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.crm_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.comms_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.intel_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.lifestyle_commands import build_parser as bp
    bp(sub)

    from hermes_ctl.cli.information_commands import build_parser as bp
    bp(sub)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    import sys

    sys.exit(main())
