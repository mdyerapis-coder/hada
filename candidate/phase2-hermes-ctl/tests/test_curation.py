"""Tests for the long-term memory curation module (offline, no network/LLM)."""

import time

import pytest

from hermes_ctl.intelligence.curation import (
    ConsolidationAction,
    CurationScore,
    CurationSuggestion,
    apply_suggestions,
    consolidate,
    curate,
    score_fact,
    _set_now,
)
from hermes_ctl.memory.store import Fact, MemoryStore


def _make_store(tmp_path) -> MemoryStore:
    return MemoryStore(persist_path=str(tmp_path / "mem.json"))


def _now() -> float:
    """Shorthand for the overridable clock."""
    from hermes_ctl.intelligence.curation import _now as inner_now
    return inner_now()


# =======================================================================
# score_fact
# =======================================================================


def test_score_fact_recent_high():
    """A fact created moments ago scores high on recency."""
    _set_now(time.time())
    fact = Fact(id="fresh", value="hello", tags={"test"}, created_at=_now() - 60)
    score = score_fact(fact, [fact])
    assert score.recency_score > 0.9
    assert score.fact_id == "fresh"
    _set_now(None)


def test_score_fact_old_low():
    """A fact created 180 days ago scores low on recency."""
    now = time.time()
    _set_now(now)
    fact = Fact(id="old", value="ancient", tags={"test"}, created_at=now - (180 * 86400))
    score = score_fact(fact, [fact])
    assert score.recency_score < 0.1
    _set_now(None)


def test_score_fact_inbox_boost():
    """Facts tagged with 'inbox' get a tag boost."""
    now = time.time()
    _set_now(now)
    inbox_fact = Fact(id="msg", value="urgent", tags={"inbox"}, created_at=now - 3600)
    normal_fact = Fact(id="norm", value="normal", tags={"test"}, created_at=now - 3600)

    inbox_score = score_fact(inbox_fact, [inbox_fact, normal_fact])
    normal_score = score_fact(normal_fact, [inbox_fact, normal_fact])

    assert inbox_score.tag_boost > 0
    assert normal_score.tag_boost == 0
    assert inbox_score.composite > normal_score.composite
    _set_now(None)


def test_score_fact_frequency_boost():
    """A fact sharing tags with many others scores higher frequency."""
    now = time.time()
    _set_now(now)
    popular = Fact(id="pop", value="popular", tags={"shared"}, created_at=now - 3600)
    related = Fact(id="rel1", value="rel1", tags={"shared"}, created_at=now - 7200)
    related2 = Fact(id="rel2", value="rel2", tags={"shared"}, created_at=now - 7200)
    loner = Fact(id="loner", value="loner", tags={"unique"}, created_at=now - 3600)

    all_facts = [popular, related, related2, loner]
    pop_score = score_fact(popular, all_facts)
    loner_score = score_fact(loner, all_facts)

    assert pop_score.frequency_score > loner_score.frequency_score
    _set_now(None)


def test_score_fact_empty_tags():
    """A fact with no tags scores 0 on frequency and tag boost."""
    now = time.time()
    _set_now(now)
    fact = Fact(id="notag", value="x", tags=set(), created_at=now - 3600)
    score = score_fact(fact, [fact])
    assert score.frequency_score == 0.0
    assert score.tag_boost == 0.0
    assert score.recency_score > 0.5
    _set_now(None)


def test_score_fact_custom_high_importance_tags():
    """Custom high-importance tags can be passed in."""
    now = time.time()
    _set_now(now)
    fact = Fact(id="custom", value="x", tags={"priority"}, created_at=now - 3600)
    score = score_fact(fact, [fact], high_importance_tags={"priority"})
    assert score.tag_boost > 0
    _set_now(None)


# =======================================================================
# CurationScore to_dict
# =======================================================================


def test_curation_score_to_dict():
    score = CurationScore(fact_id="f:1", recency_score=0.8, frequency_score=0.3, tag_boost=0.5, composite=0.6)
    d = score.to_dict()
    assert d["factId"] == "f:1"
    assert d["recencyScore"] == 0.8
    assert d["composite"] == 0.6


# =======================================================================
# curate
# =======================================================================


def test_curate_empty_store(tmp_path):
    """curate on empty store returns empty list."""
    store = _make_store(tmp_path)
    result = curate(store)
    assert result == []


def test_curate_suggests_keep_for_recent(tmp_path):
    """Recent facts get 'keep' suggestion."""
    store = _make_store(tmp_path)
    now = time.time()
    _set_now(now)
    # Add a recent fact with high-importance tags
    store.remember("fresh", {"body": "fresh fact"}, tags={"inbox"}, ttl=None)
    # Add some older facts
    for i in range(3):
        old_fact = Fact(
            id=f"old:{i}", value={"body": f"old data {i}"}, tags={"stale"},
            created_at=now - (180 * 86400)
        )
        store._facts[f"old:{i}"] = old_fact
    store._save()

    suggestions = curate(store, keep_threshold=0.4)
    keeps = {s.fact_id for s in suggestions if s.suggestion == "keep"}
    assert "fresh" in keeps
    _set_now(None)


def test_curate_suggests_archive_for_old(tmp_path):
    """Very old facts with no important tags get 'archive' suggestion."""
    store = _make_store(tmp_path)
    now = time.time()
    _set_now(now)
    # Add a very old fact
    old_fact = Fact(
        id="ancient", value={"body": "old data"}, tags={"stale"},
        created_at=now - (200 * 86400)
    )
    store._facts["ancient"] = old_fact
    store._save()

    suggestions = curate(store, archive_threshold=0.2)
    archived = [s for s in suggestions if s.suggestion == "archive"]
    assert len(archived) >= 1
    assert archived[0].fact_id == "ancient"
    _set_now(None)


def test_curate_inbox_facts_kept(tmp_path):
    """Inbox-tagged facts are typically kept (not archived)."""
    store = _make_store(tmp_path)
    now = time.time()
    _set_now(now)
    # Add inbox facts
    store.remember("inbox:0", {"body": "Incoming msg"}, tags={"inbox", "sms"}, ttl=None)
    store.remember("inbox:1", {"body": "Another msg"}, tags={"inbox"}, ttl=None)
    # Add old stale fact (should be archival candidate)
    old_fact = Fact(
        id="stale:1", value={"body": "old"}, tags={"stale"},
        created_at=now - (200 * 86400)
    )
    store._facts["stale:1"] = old_fact
    store._save()

    suggestions = curate(store, keep_threshold=0.4, archive_threshold=0.15)
    archived_ids = {s.fact_id for s in suggestions if s.suggestion == "archive"}
    assert not any("inbox:" in fid for fid in archived_ids)
    _set_now(None)


def test_curate_with_none_store():
    """curate with store=None returns empty list."""
    result = curate(None)
    assert result == []


# =======================================================================
# CurationSuggestion to_dict
# =======================================================================


def test_curation_suggestion_to_dict():
    s = CurationSuggestion(fact_id="f:1", composite_score=0.9, suggestion="keep", reason="recent")
    d = s.to_dict()
    assert d["factId"] == "f:1"
    assert d["suggestion"] == "keep"
    assert d["reason"] == "recent"


# =======================================================================
# consolidate
# =======================================================================


def test_consolidate_empty_store(tmp_path):
    """consolidate on empty store returns empty list."""
    store = _make_store(tmp_path)
    result = consolidate(store)
    assert result == []


def test_consolidate_single_fact(tmp_path):
    """consolidate with only 1 fact returns empty list."""
    store = _make_store(tmp_path)
    store.remember("only", {"body": "lonely"}, tags={"test"}, ttl=None)
    result = consolidate(store)
    assert result == []


def test_consolidate_detects_duplicates(tmp_path):
    """Two facts with very similar bodies and shared tags are detected."""
    store = _make_store(tmp_path)
    store.remember(
        "dup:1",
        {"body": "Can you pick up milk and bread from the shop please"},
        tags={"inbox", "sms"}, ttl=None,
    )
    store.remember(
        "dup:2",
        {"body": "Please can you grab milk and bread from the shop"},
        tags={"inbox", "sms"}, ttl=None,
    )
    store.remember(
        "unique:1",
        {"body": "Totally unrelated message about something else"},
        tags={"inbox"}, ttl=None,
    )

    actions = consolidate(store, similarity_threshold=0.5)
    seen_ids = set()
    for a in actions:
        seen_ids.update(a.source_ids)
        seen_ids.add(a.target_id)
    assert "dup:1" in seen_ids
    assert "dup:2" in seen_ids


def test_consolidate_relation_label_duplicate(tmp_path):
    """Very similar facts get 'duplicate' relation."""
    store = _make_store(tmp_path)
    store.remember("a", {"body": "Pick up milk and bread"}, tags={"test"}, ttl=None)
    store.remember("b", {"body": "Pick up milk and bread"}, tags={"test"}, ttl=None)
    actions = consolidate(store, similarity_threshold=0.9)
    assert len(actions) >= 1
    assert actions[0].relation == "duplicate"


def test_consolidate_none_store():
    """consolidate with store=None returns empty list."""
    result = consolidate(None)
    assert result == []


def test_consolidate_respects_max_groups(tmp_path):
    """consolidate limits the number of returned groups."""
    store = _make_store(tmp_path)
    for i in range(5):
        store.remember(f"pair:{i}a", {"body": f"Message about topic {i}"}, tags={"test"}, ttl=None)
        store.remember(f"pair:{i}b", {"body": f"Regarding topic {i}"}, tags={"test"}, ttl=None)
    actions = consolidate(store, similarity_threshold=0.3, max_groups=2)
    assert len(actions) <= 2


# =======================================================================
# ConsolidationAction to_dict
# =======================================================================


def test_consolidation_action_to_dict():
    a = ConsolidationAction(source_ids=["f:1"], target_id="f:2", relation="duplicate", description="dup (90%)")
    d = a.to_dict()
    assert d["sourceIds"] == ["f:1"]
    assert d["targetId"] == "f:2"
    assert d["relation"] == "duplicate"


# =======================================================================
# apply_suggestions
# =======================================================================


def test_apply_suggestions_dry_run(tmp_path):
    """apply_suggestions with dry_run=True does not modify the store."""
    store = _make_store(tmp_path)
    now = time.time()
    _set_now(now)
    old_fact = Fact(id="old:1", value="old data", tags=set(), created_at=now - (200 * 86400))
    store._facts["old:1"] = old_fact
    store._save()

    suggestions = curate(store, archive_threshold=0.2)
    result = apply_suggestions(store, suggestions, max_forget=10, dry_run=True)
    assert result["dryRun"] is True
    assert len(result["archived"]) > 0
    assert len(store.search()) == 1
    _set_now(None)


def test_apply_suggestions_actual_forget(tmp_path):
    """apply_suggestions with dry_run=False actually forgets facts."""
    store = _make_store(tmp_path)
    now = time.time()
    _set_now(now)
    old_fact = Fact(id="old:1", value="old", tags=set(), created_at=now - (200 * 86400))
    keep_fact = Fact(id="keep:1", value="new", tags={"inbox"}, created_at=now - 60)
    store._facts["old:1"] = old_fact
    store._facts["keep:1"] = keep_fact
    store._save()

    suggestions = curate(store, keep_threshold=0.4, archive_threshold=0.15)
    result = apply_suggestions(store, suggestions, max_forget=10, dry_run=False)
    assert result["dryRun"] is False
    assert "old:1" in result["archived"]
    remaining = {f.id for f in store.search()}
    assert "old:1" not in remaining
    assert "keep:1" in remaining
    _set_now(None)


def test_apply_suggestions_max_forget_respected(tmp_path):
    """apply_suggestions only forgets up to max_forget."""
    store = _make_store(tmp_path)
    now = time.time()
    _set_now(now)
    for i in range(5):
        store._facts[f"old:{i}"] = Fact(
            id=f"old:{i}", value="stale", tags=set(), created_at=now - (200 * 86400)
        )
    store._save()

    suggestions = curate(store, archive_threshold=0.2)
    result = apply_suggestions(store, suggestions, max_forget=2, dry_run=False)
    assert len(result["archived"]) == 2
    _set_now(None)


# =======================================================================
# _set_now cleanup
# =======================================================================


def test_set_now_resets():
    """_set_now(None) restores real clock."""
    _set_now(12345.0)
    from hermes_ctl.intelligence.curation import _now as get_now
    assert get_now() == 12345.0
    _set_now(None)
    import time
    assert abs(get_now() - time.time()) < 2
