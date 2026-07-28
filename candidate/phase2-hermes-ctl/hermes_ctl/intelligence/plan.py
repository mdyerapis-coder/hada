"""Hermes CTL — daily plan generation (Phase 3: Personal Intelligence).

Compounds the daily briefing: turns the latest briefing + open inbox items
into a prioritized, time-ordered daily plan via live inference.

Governance / safety (mirrors briefing.py):
- Schema enforced by ``validate_plan``; raises ``PlanError`` on deviation.
- ``generate_plan`` is a PURE function over collected inputs (no network).
- ``deliver_plan`` persists to MemoryStore (tagged ``plan``) + writes an
  idempotent ``plan-{date}.json`` (overwrite on re-run).
- The LLM step (run_plan) is gated on a reachable ``brains`` router and
  fails closed on unparseable model output.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from hermes_ctl.intelligence.briefing import BriefingError, scan_signals


class PlanError(Exception):
    """Raised when a plan fails schema validation or generation."""


@dataclass
class PlanItem:
    time: str
    priority: str  # high | medium | low
    task: str

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time, "priority": self.priority, "task": self.task}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanItem":
        return cls(time=d["time"], priority=d["priority"], task=d["task"])


@dataclass
class Plan:
    date: str
    headline: str
    items: list[PlanItem] = field(default_factory=list)
    model: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "headline": self.headline,
            "items": [i.to_dict() for i in self.items],
            "model": self.model,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Plan":
        return cls(
            date=d["date"],
            headline=d["headline"],
            items=[PlanItem.from_dict(i) for i in d.get("items", [])],
            model=d.get("model", "unknown"),
        )


VALID_PRIORITIES = {"high", "medium", "low"}
PLAN_ROLE = "fast"  # Qwen2.5-3B: fast, enough for a prioritized checklist

_PROMPT_TEMPLATE = """You are the HADA daily-planning engine. Produce a prioritized, time-ordered daily plan.

Latest briefing prescriptions:
{briefing}

Open inbox items (last signals):
{inbox}

Return STRICT JSON only, no prose:
{{"headline": "<=120 char day theme>", "items": [{{"time": "HH:MM or 'anytime'", "priority": "high|medium|low", "task": "<concrete actionable task>"}}]}}

Include 3-6 items. Order by time. Be specific and honest; no confabulation. If inputs are empty, propose a light maintenance day."""


def _build_prompt(briefing_json: str, inbox_json: str) -> str:
    return _PROMPT_TEMPLATE.format(briefing=briefing_json[:1500], inbox=inbox_json[:1000])


def _parse_plan(raw: str, date: str) -> Plan:
    """Parse an LLM JSON reply into a schema-valid Plan (fail-closed)."""
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        headline = str(data.get("headline", "")).strip()
        items_raw = data.get("items") or []
        if not headline:
            raise PlanError("empty headline from LLM")
        if not isinstance(items_raw, list) or not items_raw:
            raise PlanError("no plan items from LLM")
        items: list[PlanItem] = []
        for it in items_raw:
            if not isinstance(it, dict):
                raise PlanError("plan item not an object")
            t = str(it.get("time", "anytime")).strip() or "anytime"
            p = str(it.get("priority", "medium")).strip().lower()
            if p not in VALID_PRIORITIES:
                p = "medium"
            task = str(it.get("task", "")).strip()
            if not task:
                raise PlanError("plan item missing task")
            items.append(PlanItem(time=t, priority=p, task=task))
        return Plan(date=date, headline=headline[:200], items=items)
    except (json.JSONDecodeError, TypeError, AttributeError, PlanError) as exc:
        raise PlanError(f"LLM returned unparseable plan: {exc}") from exc


def generate_plan(items: list[PlanItem], *, date: str, headline: str, model: str = "unknown") -> Plan:
    """Pure construction + validation of a Plan."""
    if not items:
        raise PlanError("plan must contain at least one item")
    if not headline.strip():
        raise PlanError("plan requires a headline")
    plan = Plan(date=date, headline=headline.strip(), items=items, model=model)
    validate_plan(plan)
    return plan


def validate_plan(plan: Plan) -> None:
    """Fail-closed schema check."""
    if not isinstance(plan, Plan):
        raise PlanError("not a Plan")
    if not plan.date or not plan.headline.strip():
        raise PlanError("plan missing date/headline")
    if not plan.items:
        raise PlanError("plan has no items")
    for it in plan.items:
        if it.priority not in VALID_PRIORITIES:
            raise PlanError(f"bad priority: {it.priority}")
        if not it.task.strip():
            raise PlanError("plan item missing task")


def deliver_plan(plan: Plan, *, store: Any = None, plans_dir: str | None = None, date: str | None = None) -> str:
    """Persist the plan (MemoryStore tagged 'plan') + idempotent plan-{date}.json."""
    validate_plan(plan)
    payload = plan.to_dict()
    fact_id = f"plan:{plan.date}"

    if store is not None:
        store.remember(fact_id, payload, tags={"plan", "dream"})

    if plans_dir:
        os.makedirs(plans_dir, exist_ok=True)
        path = os.path.join(plans_dir, f"plan-{plan.date}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
        return path

    return "memory"


def run_plan(
    *,
    brains: Any,
    store: Any = None,
    plans_dir: str | None = None,
    inbox_dir: str | None = None,
    date: str | None = None,
    model: str | None = None,
) -> str:
    """Generate + deliver today's plan via live inference.

    Gated step: requires a reachable ``brains`` router (HttpRouter). Reads the
    latest briefing + open inbox, asks the brain for a prioritized plan,
    validates fail-closed, delivers. Returns the written path (or 'memory').
    """
    from hermes_ctl.intelligence.http_router import HttpRouter

    if not hasattr(brains, "complete"):
        raise PlanError("brains must expose complete(role, prompt, *, max_tokens)")
    router: HttpRouter = brains

    date = date or time.strftime("%Y-%m-%d", time.gmtime())
    model = model or PLAN_ROLE
    signals = scan_signals(inbox_dir=inbox_dir, store=store)

    # latest briefing payload (for context)
    briefing_json = "{}"
    if store is not None:
        try:
            bfs = store.search(tag="briefing")
            if bfs:
                briefing_json = json.dumps(bfs[-1].to_dict().get("value", bfs[-1].to_dict()), ensure_ascii=False)
        except Exception:
            briefing_json = "{}"
    inbox_json = json.dumps(signals, ensure_ascii=False)

    prompt = _build_prompt(briefing_json, inbox_json)
    raw = router.complete(PLAN_ROLE, prompt, max_tokens=400)
    plan = _parse_plan(raw, date)
    return deliver_plan(plan, store=store, plans_dir=plans_dir, date=date)
