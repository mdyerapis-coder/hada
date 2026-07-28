"""Hermes CTL — smart reminders from daily plan (Phase 3: Personal Intelligence).

Reads today's plan, checks which items are due/overdue, and delivers
actionable reminders to Telegram (or configured channel). Tracks delivered
items in MemoryStore to avoid repeats.

Governance / safety:
- No-op if no plan file found (graceful, not an error).
- Fail-closed on bad plan JSON (raises RemindError).
- Telegram delivery gated on live token (graceful skip if absent).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from hermes_ctl.communications.channels import Message
from hermes_ctl.intelligence.plan import Plan, PlanItem, PlanError


class RemindError(Exception):
    """Raised when reminder generation or delivery fails."""


DEFAULT_TELEGRAM_CHAT = "7620778176"  # user's Home channel
REMIND_TAG = "reminded"


def _parse_current_time() -> tuple[int, int]:
    """Return (hour, minute) in UTC (matching plan times which are HH:MM UTC)."""
    now = time.gmtime()
    return now.tm_hour, now.tm_min


def _is_pending(item: PlanItem, stored: set[str], now_h: int, now_m: int) -> bool:
    """Check if a plan item is due/pending and not yet reminded."""
    # skip if already delivered
    if item.task in stored:
        return False
    t = (item.time or "").strip()
    if not t or t.lower() == "anytime":
        return True  # anytime items are always pending until reminded
    try:
        parts = t.split(":")
        h, m = int(parts[0]), int(parts[1])
        return h < now_h or (h == now_h and m <= now_m)
    except (ValueError, IndexError):
        # unparseable time → still pending
        return True


def _priority_value(p: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(p, 3)


def _load_plan_from_disk(plans_dir: str, date: str) -> Plan | None:
    """Load the first available plan file (exact date or latest)."""
    # try exact date
    path = os.path.join(plans_dir, f"plan-{date}.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return Plan.from_dict(json.load(fh))

    # fallback: latest plan file
    import glob as g_mod
    files = sorted(g_mod.glob(os.path.join(plans_dir, "plan-*.json")), reverse=True)
    if not files:
        return None
    with open(files[0], encoding="utf-8") as fh:
        return Plan.from_dict(json.load(fh))


def _load_reminded(store: Any) -> set[str]:
    """Load the set of already-reminded tasks from MemoryStore."""
    if store is None:
        return set()
    try:
        facts = store.search(tag=REMIND_TAG) or []
        out: set[str] = set()
        for f in facts:
            d = f.to_dict()
            val = d.get("value", d)
            if isinstance(val, dict):
                t = val.get("task", "")
            elif isinstance(val, str):
                t = val
            else:
                continue
            if t:
                out.add(t)
        return out
    except Exception:
        return set()


def _mark_reminded(task: str, store: Any) -> None:
    """Record a task as reminded in MemoryStore."""
    if store is None:
        return
    try:
        store.remember(f"reminded:{task}", {"task": task, "time": time.strftime("%H:%M UTC", time.gmtime())}, tags={REMIND_TAG})
    except Exception:
        pass  # non-fatal


def run_remind(
    *,
    plans_dir: str = ".",
    telegram_chat: str = DEFAULT_TELEGRAM_CHAT,
    store: Any = None,
    date: str | None = None,
) -> int:
    """Run reminders: read plan, find pending items, deliver to Telegram.

    Returns the number of reminders sent (0 = no-op, no error).
    Raises RemindError only on unrecoverable failures.
    """
    date = date or time.strftime("%Y-%m-%d", time.gmtime())
    now_h, now_m = _parse_current_time()

    # load plan
    plan = _load_plan_from_disk(plans_dir, date)
    if plan is None:
        return 0  # no plan yet = nothing to remind

    # load already-reminded set
    reminded = _load_reminded(store)

    # find pending items, sorted by priority
    pending = [it for it in plan.items if _is_pending(it, reminded, now_h, now_m)]
    if not pending:
        return 0

    pending.sort(key=lambda it: _priority_value(it.priority))

    # deliver via Telegram
    from hermes_ctl.communications.telegram import TelegramChannel

    try:
        tg = TelegramChannel()
        for item in pending:
            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.priority, "⚪")
            time_str = (item.time or "anytime").strip()
            body = f"{priority_icon} *{item.task}*\n⏰ {time_str} · priority {item.priority}"
            tg.send(Message(channel="reminder", sender="hada", recipient=telegram_chat, body=body))
            _mark_reminded(item.task, store)
        return len(pending)
    except (RuntimeError, OSError, Exception) as exc:
        raise RemindError(f"Telegram delivery failed: {exc}") from exc
