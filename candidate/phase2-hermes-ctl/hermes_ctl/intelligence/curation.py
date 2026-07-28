"""Hermes CTL — long-term memory curation (Phase 3: Personal Intelligence).

Provides importance scoring, consolidation, and curation management for facts
stored in the MemoryStore. This controls memory growth by identifying what's
valuable, merging near-duplicates, and suggesting candidates for archival.

Governance / safety:
- Pure data model + scoring (no network, no LLM at module level).
- ``curate()`` scans all facts and returns curation suggestions (read-only).
- ``consolidate()`` finds related facts and returns merge candidates.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CurationError(Exception):
    """Raised when curation or consolidation operations fail."""


# ---------------------------------------------------------------------------
# Scoring data models
# ---------------------------------------------------------------------------


@dataclass
class CurationScore:
    """Importance score for a single fact.

    All components range from 0.0 (low/old/forgettable) to 1.0 (high/fresh/valuable).
    """

    fact_id: str
    recency_score: float = 0.0
    frequency_score: float = 0.0
    tag_boost: float = 0.0
    composite: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "factId": self.fact_id,
            "recencyScore": round(self.recency_score, 3),
            "frequencyScore": round(self.frequency_score, 3),
            "tagBoost": round(self.tag_boost, 3),
            "composite": round(self.composite, 3),
        }


@dataclass
class CurationSuggestion:
    """A curation action suggestion for a single fact."""

    fact_id: str
    composite_score: float
    suggestion: str  # "keep" | "review" | "archive"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "factId": self.fact_id,
            "compositeScore": round(self.composite_score, 3),
            "suggestion": self.suggestion,
            "reason": self.reason,
        }


@dataclass
class ConsolidationAction:
    """A suggested merge of related facts into one consolidated fact."""

    source_ids: list[str] = field(default_factory=list)
    target_id: str = ""
    relation: str = "related"  # "duplicate" | "related" | "superseded"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceIds": list(self.source_ids),
            "targetId": self.target_id,
            "relation": self.relation,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

_NOW: float | None = None  # overridable in tests


def _now() -> float:
    return _NOW if _NOW is not None else time.time()


def _days_ago(ts: float) -> float:
    """Return fractional days since *ts*."""
    return (_now() - ts) / 86400.0


# Tags that imply higher importance (can be overridden per call).
# These are common in the Phase 2 contact daemon and productivity subsystems.
_HIGH_IMPORTANCE_TAGS: set[str] = {"inbox", "context", "plan", "briefing", "reminder"}


def score_fact(
    fact: Any,
    all_facts: list[Any],
    *,
    high_importance_tags: set[str] | None = None,
) -> CurationScore:
    """Compute an importance score for a single fact.

    Args:
        fact: A ``Fact``-like object with ``id``, ``created_at``, ``tags``.
        all_facts: All facts in the store (for frequency computation).
        high_importance_tags: Tags that boost importance. Defaults to
            ``_HIGH_IMPORTANCE_TAGS``.

    Returns:
        A ``CurationScore`` with per-component and composite scores.
    """
    now = _now()
    hi_tags = high_importance_tags or _HIGH_IMPORTANCE_TAGS

    # -- Recency: score decays from 1.0 (now) to 0.0 (>90 days ago) --
    age_days = (now - fact.created_at) / 86400.0 if hasattr(fact, "created_at") else 365.0
    recency_score = max(0.0, 1.0 - (age_days / 90.0))

    # -- Frequency: how many other facts share tags with this one --
    fact_tags = set(getattr(fact, "tags", set()) or set())
    if not fact_tags or not all_facts:
        frequency_score = 0.0
    else:
        related = sum(
            1
            for f in all_facts
            if f.id != fact.id and (set(getattr(f, "tags", set()) or set()) & fact_tags)
        )
        frequency_score = min(1.0, related / max(len(all_facts), 1) * 5.0)

    # -- Tag boost: does this fact carry high-importance tags? --
    if fact_tags & hi_tags:
        tag_boost = 0.5 if fact_tags & {"inbox", "context"} else 0.3
    else:
        tag_boost = 0.0

    # -- Composite: weighted sum --
    composite = (recency_score * 0.4) + (frequency_score * 0.3) + (tag_boost * 0.3)
    composite = max(0.0, min(1.0, composite))

    return CurationScore(
        fact_id=fact.id,
        recency_score=recency_score,
        frequency_score=frequency_score,
        tag_boost=tag_boost,
        composite=composite,
    )


# ---------------------------------------------------------------------------
# Curation (scan all facts, return suggestions)
# ---------------------------------------------------------------------------


def curate(
    store: Any,
    *,
    keep_threshold: float = 0.5,
    archive_threshold: float = 0.2,
    high_importance_tags: set[str] | None = None,
) -> list[CurationSuggestion]:
    """Scan all facts in the store and return curation suggestions.

    Args:
        store: A ``MemoryStore`` instance with ``search()`` returning facts.
        keep_threshold: Facts with composite >= this are suggested ``"keep"``.
        archive_threshold: Facts with composite < this are suggested
            ``"archive"``. Intermediate values get ``"review"``.
        high_importance_tags: Passed through to ``score_fact()``.

    Returns:
        A list of ``CurationSuggestion`` objects, ordered by lowest composite
        first (most archival-candidate facts first).
    """
    try:
        all_facts = list(store.search() if store is not None else [])
    except Exception:
        return []

    suggestions: list[CurationSuggestion] = []
    for fact in all_facts:
        score = score_fact(fact, all_facts, high_importance_tags=high_importance_tags)
        sc = score.composite

        if sc >= keep_threshold:
            suggestion = "keep"
            reason = _keep_reason(fact, score)
        elif sc < archive_threshold:
            suggestion = "archive"
            reason = _archive_reason(fact, score)
        else:
            suggestion = "review"
            reason = _review_reason(fact, score)

        suggestions.append(
            CurationSuggestion(
                fact_id=fact.id,
                composite_score=sc,
                suggestion=suggestion,
                reason=reason,
            )
        )

    # Lowest score first — most forgettable at the top
    suggestions.sort(key=lambda s: s.composite_score)
    return suggestions


def _keep_reason(fact: Any, score: CurationScore) -> str:
    parts = []
    if score.recency_score > 0.7:
        parts.append("recent")
    if score.frequency_score > 0.3:
        parts.append("frequently-referenced")
    if score.tag_boost > 0:
        parts.append("high-importance tag")
    return f"keep ({', '.join(parts)})" if parts else "keep (above threshold)"


def _archive_reason(fact: Any, score: CurationScore) -> str:
    parts = []
    if score.recency_score < 0.3:
        parts.append("old")
    if score.frequency_score < 0.1:
        parts.append("rarely-referenced")
    return f"archive ({', '.join(parts)})" if parts else "archive (below threshold)"


def _review_reason(fact: Any, score: CurationScore) -> str:
    return "review (borderline importance)"


# ---------------------------------------------------------------------------
# Consolidation (find related facts and suggest merges)
# ---------------------------------------------------------------------------


def _text_similarity(a: str, b: str) -> float:
    """Very simple token-overlap similarity (0.0–1.0).

    No NLP dependency, no network. Useful for detecting near-duplicate
    inbox entries or similar notes.
    """
    tokens_a = set(re.findall(r"\w+", a.lower()))
    tokens_b = set(re.findall(r"\w+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / max(len(union), 1)


def consolidate(
    store: Any,
    *,
    similarity_threshold: float = 0.7,
    max_groups: int = 10,
) -> list[ConsolidationAction]:
    """Scan all facts and suggest consolidations for similar entries.

    Uses token-overlap similarity on fact values (text-only). Detects:
    - Near-duplicate inbox messages (same body).
    - Related facts with shared tags + similar value content.

    Args:
        store: A ``MemoryStore`` instance with ``search()`` returning facts.
        similarity_threshold: Token-overlap score above which two facts are
            considered similar enough to consolidate (0.0–1.0).
        max_groups: Maximum number of consolidation groups to return.

    Returns:
        A list of ``ConsolidationAction`` objects, highest similarity first.
    """
    try:
        all_facts = list(store.search() if store is not None else [])
    except Exception:
        return []

    if len(all_facts) < 2:
        return []

    # Compare every pair (O(n²) but bounded: only a few hundred facts).
    pairs: list[tuple[float, Any, Any]] = []
    for i, fa in enumerate(all_facts):
        for fb in all_facts[i + 1 :]:
            sim = _fact_similarity(fa, fb)
            if sim >= similarity_threshold:
                pairs.append((sim, fa, fb))

    if not pairs:
        return []

    # Sort by similarity descending, take top groups
    pairs.sort(key=lambda x: x[0], reverse=True)

    # Greedy clustering: once a fact is in a group, skip it
    grouped_ids: set[str] = set()
    actions: list[ConsolidationAction] = []

    for sim, fa, fb in pairs:
        if fa.id in grouped_ids or fb.id in grouped_ids:
            continue
        target_id = fa.id if fa.created_at <= fb.created_at else fb.id
        source_id = fb.id if target_id == fa.id else fa.id
        relation = "duplicate" if sim > 0.9 else "related"
        # Build a human-readable description
        desc = _consolidation_desc(fa, fb, sim, relation)

        actions.append(
            ConsolidationAction(
                source_ids=[source_id],
                target_id=target_id,
                relation=relation,
                description=desc,
            )
        )
        grouped_ids.add(fa.id)
        grouped_ids.add(fb.id)

        if len(actions) >= max_groups:
            break

    return actions


def _fact_similarity(fa: Any, fb: Any) -> float:
    """Compute pairwise similarity between two facts.

    Combines tag overlap and text-value similarity.
    """
    tags_a = set(getattr(fa, "tags", set()) or set())
    tags_b = set(getattr(fb, "tags", set()) or set())

    # Tag overlap
    tag_sim = 0.0
    if tags_a and tags_b:
        tag_sim = len(tags_a & tags_b) / max(len(tags_a | tags_b), 1)

    # Text value similarity
    val_a = _fact_text(fa)
    val_b = _fact_text(fb)
    text_sim = _text_similarity(val_a, val_b) if val_a and val_b else 0.0

    # Weighted combination
    return (tag_sim * 0.3) + (text_sim * 0.7)


def _fact_text(fact: Any) -> str:
    """Extract a flat text representation from a fact's value for comparison."""
    val = getattr(fact, "value", None)
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        # Common fields in the Phase 2 contact daemon
        parts = []
        for k in ("body", "subject", "title", "description", "name", "sender"):
            v = val.get(k)
            if v:
                parts.append(str(v))
        return " ".join(parts)
    return str(val)


def _consolidation_desc(fa: Any, fb: Any, sim: float, relation: str) -> str:
    """Build a human-readable consolidation description."""
    tags_a = sorted(getattr(fa, "tags", set()) or set())
    tags_b = sorted(getattr(fb, "tags", set()) or set())
    tag_info = f"tags {tags_a} vs {tags_b}" if tags_a or tags_b else ""
    val_a = _fact_text(fa)[:60]
    val_b = _fact_text(fb)[:60]
    text_info = f"\"{val_a}\" <-> \"{val_b}\""
    extra = f" [{tag_info}]" if tag_info else ""
    return f"{relation} ({sim:.0%} similar): {text_info}{extra}"


# ---------------------------------------------------------------------------
# Apply suggestions (write operations on the store)
# ---------------------------------------------------------------------------


def apply_suggestions(
    store: Any,
    suggestions: list[CurationSuggestion],
    *,
    max_forget: int = 0,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply curation suggestions to the store.

    By default a dry-run that reports what *would* happen. Pass
    ``dry_run=False`` and ``max_forget=N`` to actually archive.

    Args:
        store: A ``MemoryStore`` instance.
        suggestions: Curation suggestions from ``curate()``.
        max_forget: Max number of ``"archive"`` suggestions to apply (0 = none).
        dry_run: If True, only report — do not modify the store.

    Returns:
        A results dict with keys ``archived``, ``kept``, ``errors``.
    """
    archived: list[str] = []
    kept: list[str] = []
    errors: list[str] = []

    forget_count = 0
    for s in suggestions:
        if s.suggestion == "archive" and forget_count < max_forget:
            if dry_run:
                archived.append(s.fact_id)
                forget_count += 1
            else:
                try:
                    store.forget(s.fact_id)
                    archived.append(s.fact_id)
                    forget_count += 1
                except Exception as exc:
                    errors.append(f"{s.fact_id}: {exc}")
        else:
            kept.append(s.fact_id)

    return {
        "dryRun": dry_run,
        "archived": archived,
        "kept": kept,
        "errors": errors,
        "totalArchived": len(archived),
        "totalKept": len(kept),
        "totalErrors": len(errors),
    }


# ---------------------------------------------------------------------------
# Override _NOW for testing
# ---------------------------------------------------------------------------


def _set_now(ts: float | None) -> None:
    """Override internal clock (for testing)."""
    global _NOW  # noqa: PLW0603
    _NOW = ts
