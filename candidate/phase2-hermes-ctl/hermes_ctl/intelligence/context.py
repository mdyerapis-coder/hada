"""Hermes CTL — context awareness (Phase 3: Personal Intelligence).

Collects real-time system state from all available subsystems and builds
a structured context snapshot. This enriches briefing, planning, and other
Phase 3 features with a unified view of "what's happening right now".

Governance / safety (mirrors briefing.py, plan.py):
- Pure data model + collection (no network, no LLM at module level).
- ``scan_context`` reads from MemoryStore, inbox, plans — read-only.
- ``deliver_context`` persists to MemoryStore (tagged ``context``).
- Every field has a safe default — no crashes on missing data.
"""

from __future__ import annotations

import glob as g_mod
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any


class ContextError(Exception):
    """Raised when context snapshot collection or delivery fails."""


@dataclass
class ContextSnapshot:
    """Structured snapshot of the current system state.

    All fields have safe defaults so consumers never crash on missing data.
    """

    timestamp: str = ""
    date: str = ""
    inbox_count: int = 0
    recent_inbox: list[dict] = field(default_factory=list)
    open_tasks: list[dict] = field(default_factory=list)
    current_plan: dict | None = None
    latest_briefing: dict | None = None
    user_profile: dict | None = None
    context_facts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": self.date,
            "inboxCount": self.inbox_count,
            "recentInbox": list(self.recent_inbox),
            "openTasks": list(self.open_tasks),
            "currentPlan": self.current_plan,
            "latestBriefing": self.latest_briefing,
            "userProfile": self.user_profile,
            "contextFacts": list(self.context_facts),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ContextSnapshot":
        return cls(
            timestamp=d.get("timestamp", ""),
            date=d.get("date", ""),
            inbox_count=d.get("inboxCount", 0),
            recent_inbox=list(d.get("recentInbox", [])),
            open_tasks=list(d.get("openTasks", [])),
            current_plan=d.get("currentPlan"),
            latest_briefing=d.get("latestBriefing"),
            user_profile=d.get("userProfile"),
            context_facts=list(d.get("contextFacts", [])),
        )


# -- Helpers --


def _safe_str(val: Any) -> str:
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


def _dict_val(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        try:
            d = d[k]
        except (KeyError, TypeError):
            return default
    return d


# -- Collection --


def _collect_inbox(store: Any) -> tuple[int, list[dict]]:
    """Read the last 5 inbox entries from MemoryStore."""
    try:
        inbox = list(store.search(tag="inbox")) if store is not None else []
        inbox.sort(key=lambda f: getattr(f, "id", ""), reverse=True)
        recent = []
        for f in inbox[:5]:
            v = f.value if hasattr(f, "value") else {}
            recent.append({
                "channel": v.get("channel", "?"),
                "sender": v.get("sender", "?"),
                "body": _safe_str(v.get("body", ""))[:120],
                "time": v.get("timestamp", ""),
            })
        return len(inbox), recent
    except Exception:
        return 0, []


def _collect_open_tasks(store: Any) -> list[dict]:
    """Read open tasks from ProductivityStore (fallback: raw MemoryStore search)."""
    try:
        from hermes_ctl.productivity.store import ProductivityStore

        ps = ProductivityStore(store) if store is not None else None
        if ps is None:
            return []
        tasks = ps.list_tasks(only_open=True)
        return [
            {"id": t.id, "title": t.title, "priority": getattr(t, "priority", "medium")}
            for t in tasks
        ]
    except Exception:
        return []


def _collect_plan(plans_dir: str | None, date: str) -> dict | None:
    """Load today's plan file if it exists."""
    if not plans_dir or not os.path.isdir(plans_dir):
        return None
    path = os.path.join(plans_dir, f"plan-{date}.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
    # fallback: latest plan
    files = sorted(g_mod.glob(os.path.join(plans_dir, "plan-*.json")), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _collect_briefing(plans_dir: str | None) -> dict | None:
    """Load the latest briefing file if it exists."""
    if not plans_dir or not os.path.isdir(plans_dir):
        return None
    files = sorted(g_mod.glob(os.path.join(plans_dir, "dream-*.json")), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _collect_profile(store: Any) -> dict | None:
    """Read user profile from Identity subsystem."""
    try:
        from hermes_ctl.identity.profile import Identity

        ident = Identity(store) if store is not None else None
        if ident is None:
            return None
        profile = ident.get_profile()
        prefs = ident.all_preferences()
        return {"profile": profile, "preferences": prefs}
    except Exception:
        return None


def _collect_context_facts(store: Any) -> list[dict]:
    """Read recent context-tagged facts from MemoryStore."""
    try:
        if store is None:
            return []
        facts = list(store.search(tag="context"))
        facts.sort(key=lambda f: getattr(f, "id", ""), reverse=True)
        out = []
        for f in facts[:10]:
            v = f.value if hasattr(f, "value") else {}
            out.append({"id": getattr(f, "id", ""), "value": v})
        return out
    except Exception:
        return []


# -- Public API --


def scan_context(
    *,
    store: Any = None,
    plans_dir: str | None = None,
) -> ContextSnapshot:
    """Collect current system state from all available sources. Read-only.

    Args:
        store: A MemoryStore instance (or anything with search() that returns
               Fact-like objects).
        plans_dir: Optional path to the directory containing plan-*.json and
                   dream-*.json files.

    Returns:
        A populated ``ContextSnapshot``. Every field has a safe default — no
        crashes on missing subsystems.
    """
    date = time.strftime("%Y-%m-%d", time.gmtime())
    inbox_count, recent_inbox = _collect_inbox(store)
    return ContextSnapshot(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        date=date,
        inbox_count=inbox_count,
        recent_inbox=recent_inbox,
        open_tasks=_collect_open_tasks(store),
        current_plan=_collect_plan(plans_dir, date),
        latest_briefing=_collect_briefing(plans_dir),
        user_profile=_collect_profile(store),
        context_facts=_collect_context_facts(store),
    )


def deliver_context(
    snapshot: ContextSnapshot,
    *,
    store: Any = None,
) -> str:
    """Persist the context snapshot to MemoryStore (tagged ``context``).

    Args:
        snapshot: A ContextSnapshot to persist.
        store: A MemoryStore instance.

    Returns:
        ``"memory"`` on success.

    Raises:
        ContextError: if persistence fails.
    """
    payload = snapshot.to_dict()
    fact_id = f"context:{snapshot.date}:{int(time.time())}"
    if store is not None:
        try:
            store.remember(fact_id, payload, tags={"context", "snapshot"})
        except Exception as exc:
            raise ContextError(f"failed to persist context: {exc}") from exc
    return "memory"
