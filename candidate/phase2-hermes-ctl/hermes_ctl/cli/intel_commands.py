"""Intelligence commands: brains, context, briefing, plan, remind."""

from __future__ import annotations

import argparse
import json
import os
import sys

from hermes_ctl.cli.store import _store
from hermes_ctl.intelligence.briefing import Briefing, BriefingError, generate_briefing, deliver_briefing
from hermes_ctl.intelligence.context import scan_context, deliver_context
from hermes_ctl.intelligence.finance import FinancialSnapshot, FinanceError, add_budget, add_expense, scan_finances, deliver_finances


def build_parser(sub) -> None:
    # brains
    pb = sub.add_parser("brains", help="list configured llmfit brains (HADA inference backend)")
    pb.set_defaults(func=_cmd_brains)

    # context
    pcx = sub.add_parser("context", help="show current system context snapshot")
    pcx.set_defaults(func=_cmd_context)

    # briefing
    pbr = sub.add_parser("briefing", help="Dream-style daily briefing (validate | run)")
    brsub = pbr.add_subparsers(dest="briefing_action", required=True)
    brv = brsub.add_parser("validate", help="check a briefing JSON against the strict schema (offline)")
    brv.add_argument("file", help="path to dream-{date}.json")
    brv.set_defaults(func=_cmd_briefing)
    brr = brsub.add_parser("run", help="generate + deliver today's briefing (gated: live inference)")
    brr.add_argument("--telegram", action="store_true", dest="briefing_telegram", help="also send summary to Telegram")
    brr.set_defaults(func=_cmd_briefing)

    # plan
    ppl = sub.add_parser("plan", help="daily plan from briefing + inbox (validate | run)")
    plsub = ppl.add_subparsers(dest="plan_action", required=True)
    plv = plsub.add_parser("validate", help="check a plan JSON against the strict schema (offline)")
    plv.add_argument("file", help="path to plan-{date}.json")
    plv.set_defaults(func=_cmd_plan)
    plr = plsub.add_parser("run", help="generate + deliver today's plan (gated: live inference)")
    plr.add_argument("--telegram", action="store_true", dest="plan_telegram", help="also send summary to Telegram")
    plr.set_defaults(func=_cmd_plan)

    # remind
    prm = sub.add_parser("remind", help="smart reminders from daily plan (remind run)")
    rmsub = prm.add_subparsers(dest="remind_action", required=True)
    rmr = rmsub.add_parser("run", help="check plan items due, send pending reminders to Telegram")
    rmr.set_defaults(func=_cmd_remind)


# ---------------------------------------------------------------------------
# brains
# ---------------------------------------------------------------------------
def _cmd_brains(args: argparse.Namespace) -> int:
    # Lazy import via cli module for test monkeypatch compatibility
    from hermes_ctl.cli import load_brains

    try:
        brains = load_brains()
    except (ValueError, FileNotFoundError) as exc:
        print(f"brains config error: {exc}", file=sys.stderr)
        return 1
    for b in brains:
        print(f"{b.role:7} {b.url}  model={b.model}")
    return 0


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------
def _cmd_context(args: argparse.Namespace) -> int:
    """Show current system context snapshot (read-only, no network)."""
    plans_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "dreams"))
    try:
        ctx = scan_context(store=_store(), plans_dir=plans_dir)
        deliver_context(ctx, store=_store())
    except Exception as exc:  # noqa: BLE001 - surface collection failures cleanly
        print(f"context scan failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(ctx.to_dict(), indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# briefing
# ---------------------------------------------------------------------------
def _cmd_briefing(args: argparse.Namespace) -> int:
    # Lazy import via cli module for test monkeypatch compatibility
    from hermes_ctl.cli import load_brains

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
        try:
            brains = load_brains()
        except (ValueError, FileNotFoundError) as exc:
            print(f"brains config error: {exc}", file=sys.stderr)
            return 1
        from hermes_ctl.intelligence.briefing import run_briefing
        from hermes_ctl.intelligence.http_router import HttpRouter

        try:
            dreams_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "dreams"))
            path = run_briefing(
                brains=HttpRouter(brains),
                store=_store(),
                dreams_dir=dreams_dir,
            )
        except Exception as exc:  # noqa: BLE001 - surface inference/delivery failures cleanly
            print(f"briefing run failed: {exc}", file=sys.stderr)
            return 1
        print(f"briefing delivered: {path}")
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


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------
def _cmd_plan(args: argparse.Namespace) -> int:
    # Lazy import via cli module for test monkeypatch compatibility
    from hermes_ctl.cli import load_brains

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
        try:
            brains = load_brains()
        except (ValueError, FileNotFoundError) as exc:
            print(f"brains config error: {exc}", file=sys.stderr)
            return 1
        from hermes_ctl.intelligence.plan import run_plan
        from hermes_ctl.intelligence.http_router import HttpRouter

        try:
            plans_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "dreams"))
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


# ---------------------------------------------------------------------------
# remind
# ---------------------------------------------------------------------------
def _cmd_remind(args: argparse.Namespace) -> int:
    if args.remind_action == "run":
        from hermes_ctl.intelligence.remind import run_remind

        try:
            plans_dir = os.environ.get("HERMES_DREAMS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "dreams"))
            telegram_chat = os.environ.get("HERMES_TELEGRAM_CHAT", "7620778176")
            count = run_remind(plans_dir=plans_dir, telegram_chat=telegram_chat, store=_store())
        except Exception as exc:  # noqa: BLE001
            print(f"remind run failed: {exc}", file=sys.stderr)
            return 1
        print(f"remind delivered: {count} reminder(s) sent")
        return 0
    return 2  # pragma: no cover
