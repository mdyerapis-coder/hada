"""Hermes CTL — Dream-style daily briefing (Phase 3 enabler).

Ported from the Claude Code OS ``/dream`` contract: scan the operator's
recent signals across orthogonal buckets, then emit the **top 4
highest-impact prescriptions** as a strict JSON document.

Governance / safety:
- The schema is enforced. ``validate_briefing`` raises ``BriefingError`` on
  any deviation (wrong count, bad category/tone, missing fields). The caller
  must NOT deliver an invalid briefing — confabulation corrupts trust.
- ``generate_briefing`` is a PURE function over an already-collected
  ``signals`` dict. No network, no secrets, no LLM at call time — the LLM
  step that *produces* the prescriptions is the caller's job (and is gated
  on live inference). This module only models + validates + delivers.
- ``deliver_briefing`` persists to the MemoryStore (tagged ``briefing``) and
  writes an idempotent ``dream-{date}.json`` mirroring the upstream contract,
  so the same file can back a future dashboard.

The 4 output categories (v1) and their required tones:
    MEMORY  -> pink
    COST    -> orange
    SKILLS  -> blue
    WORKFLOW-> yellow
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

# v1 category -> required tone
CATEGORY_TONES: dict[str, str] = {
    "MEMORY": "pink",
    "COST": "orange",
    "SKILLS": "blue",
    "WORKFLOW": "yellow",
}
VALID_CATEGORIES = set(CATEGORY_TONES)
VALID_TONES = set(CATEGORY_TONES.values())

# Hard guard rails (ported from the Dream contract)
MAX_PRESCRIPTIONS = 4
HEADLINE_MAX = 120


class BriefingError(Exception):
    """Raised when a briefing fails schema or guard-rail validation."""


@dataclass
class Prescription:
    id: str
    cat: str
    tone: str
    headline: str
    prescription: str
    evidence: list[str]
    command: str
    dollar_impact: int | None = None
    time_impact_mins: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cat": self.cat,
            "tone": self.tone,
            "headline": self.headline,
            "prescription": self.prescription,
            "evidence": list(self.evidence),
            "command": self.command,
            "dollarImpact": self.dollar_impact,
            "timeImpactMins": self.time_impact_mins,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Prescription":
        return cls(
            id=d["id"],
            cat=d["cat"],
            tone=d["tone"],
            headline=d["headline"],
            prescription=d["prescription"],
            evidence=list(d.get("evidence", [])),
            command=d["command"],
            dollar_impact=d.get("dollarImpact"),
            time_impact_mins=d.get("timeImpactMins"),
        )


@dataclass
class Briefing:
    date: str
    model: str
    generated_at: str
    prescriptions: list[Prescription] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "date": self.date,
            "model": self.model,
            "generatedAt": self.generated_at,
            "prescriptions": [p.to_dict() for p in self.prescriptions],
        }
        if self.metadata:
            out["metadata"] = self.metadata
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Briefing":
        return cls(
            date=d["date"],
            model=d["model"],
            generated_at=d["generatedAt"],
            prescriptions=[Prescription.from_dict(p) for p in d.get("prescriptions", [])],
            metadata=d.get("metadata", {}),
        )


def validate_briefing(briefing: Briefing) -> None:
    """Fail-closed schema check. Raises BriefingError on any deviation."""
    if not briefing.date or not isinstance(briefing.date, str):
        raise BriefingError("briefing.date must be a non-empty string")
    if not briefing.model or not isinstance(briefing.model, str):
        raise BriefingError("briefing.model must be a non-empty string")
    if not briefing.generated_at or not isinstance(briefing.generated_at, str):
        raise BriefingError("briefing.generatedAt must be a non-empty string")

    n = len(briefing.prescriptions)
    if n == 0:
        raise BriefingError("briefing must contain at least 1 prescription (or omit entirely)")
    if n > MAX_PRESCRIPTIONS:
        raise BriefingError(f"briefing must have <= {MAX_PRESCRIPTIONS} prescriptions, got {n}")

    seen_ids: set[str] = set()
    for i, p in enumerate(briefing.prescriptions):
        where = f"prescription #{i + 1} ({p.id!r})"
        if not p.id or not isinstance(p.id, str):
            raise BriefingError(f"{where}: id must be a non-empty string")
        if p.id in seen_ids:
            raise BriefingError(f"{where}: duplicate id {p.id!r}")
        seen_ids.add(p.id)

        if p.cat not in VALID_CATEGORIES:
            raise BriefingError(f"{where}: cat must be one of {sorted(VALID_CATEGORIES)}, got {p.cat!r}")
        expected_tone = CATEGORY_TONES[p.cat]
        if p.tone != expected_tone:
            raise BriefingError(f"{where}: tone must be {expected_tone!r} for cat {p.cat!r}, got {p.tone!r}")

        if not p.headline or len(p.headline) > HEADLINE_MAX:
            raise BriefingError(f"{where}: headline must be 1..{HEADLINE_MAX} chars")
        if not p.prescription:
            raise BriefingError(f"{where}: prescription body required")
        if not isinstance(p.evidence, list) or len(p.evidence) != 3:
            raise BriefingError(f"{where}: evidence must be exactly 3 entries")
        if not p.command:
            raise BriefingError(f"{where}: command required")

        if p.dollar_impact is not None and not isinstance(p.dollar_impact, int):
            raise BriefingError(f"{where}: dollarImpact must be int or null")
        if p.time_impact_mins is not None and not isinstance(p.time_impact_mins, int):
            raise BriefingError(f"{where}: timeImpactMins must be int or null")


def generate_briefing(
    prescriptions: list[Prescription],
    *,
    date: str,
    model: str,
    generated_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Briefing:
    """Build + validate a Briefing from prescriptions. Fail-closed.

    ``prescriptions`` is the caller-produced list of <=4 prescriptions
    (typically the output of an LLM step over collected signals). This
    function does NOT generate content — it models + validates only.
    """
    briefing = Briefing(
        date=date,
        model=model,
        generated_at=generated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        prescriptions=list(prescriptions),
        metadata=metadata or {},
    )
    validate_briefing(briefing)
    return briefing


def deliver_briefing(
    briefing: Briefing,
    *,
    store: Any = None,
    dreams_dir: str | None = None,
) -> str:
    """Persist a validated briefing.

    - If ``store`` (a MemoryStore) is given, remembers it tagged ``briefing``.
    - If ``dreams_dir`` is given, writes idempotent ``dream-{date}.json``
      (mirrors the upstream contract; overwrite on re-run).
    Returns the path written (or 'memory' if only the store was used).
    """
    validate_briefing(briefing)
    payload = briefing.to_dict()
    fact_id = f"briefing:{briefing.date}"

    if store is not None:
        store.remember(fact_id, payload, tags={"briefing", "dream"})

    if dreams_dir:
        os.makedirs(dreams_dir, exist_ok=True)
        path = os.path.join(dreams_dir, f"dream-{briefing.date}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
        return path

    return "memory"


def scan_signals(*, inbox_dir: str | None = None, store: Any = None) -> dict[str, Any]:
    """Collect the last-24h signal sources HADA actually has.

    Read-only, no network. Returns a dict the LLM step can consume. Placeholder
    wiring: reads the MemoryStore inbox + recent facts if provided. The LLM
    production of prescriptions from these signals is a separate gated step.
    """
    signals: dict[str, Any] = {"buckets": []}
    if store is not None:
        try:
            signals["memory_facts"] = [f.to_dict() for f in store.search(tag="briefing")]
        except Exception:
            signals["memory_facts"] = []
    if inbox_dir and os.path.isdir(inbox_dir):
        signals["inbox_present"] = True
        signals["buckets"].append("conversation")
    return signals
