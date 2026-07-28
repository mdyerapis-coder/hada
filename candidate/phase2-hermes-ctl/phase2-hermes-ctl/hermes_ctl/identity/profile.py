"""Hermes CTL — Identity subsystem (Phase 2).

Builds the user profile / preferences / context surface on top of the
MemoryStore. This is the second foundation block from the Phase 2 roadmap
(Identity precedes Communications / Productivity / Intelligence because they
all need to know *who* the user is and what they prefer).

Stdlib-only. No network / secrets / infra.
"""

from __future__ import annotations

from typing import Any

from hermes_ctl.memory.store import MemoryStore


_PROFILE_ID = "identity.user_profile"
_PREFS_ID = "identity.preferences"
_CONTEXT_ID = "identity.context"


class IdentityError(Exception):
    """Raised on invalid identity operations."""


class Identity:
    """User identity: profile, preferences, and volatile context."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    # ---- profile ----
    def set_profile(self, **fields: Any) -> dict[str, Any]:
        """Merge profile fields (name, role, locale, timezone, ...)."""
        try:
            profile = dict(self._store.recall(_PROFILE_ID))
        except Exception:
            profile = {}
        profile.update(fields)
        self._store.remember(_PROFILE_ID, profile, tags=["identity", "profile"])
        return profile

    def get_profile(self) -> dict[str, Any]:
        try:
            return dict(self._store.recall(_PROFILE_ID))
        except Exception:
            return {}

    # ---- preferences ----
    def set_preference(self, key: str, value: Any) -> None:
        if not key:
            raise IdentityError("preference key must be non-empty")
        try:
            prefs = dict(self._store.recall(_PREFS_ID))
        except Exception:
            prefs = {}
        prefs[key] = value
        self._store.remember(_PREFS_ID, prefs, tags=["identity", "preferences"])

    def get_preference(self, key: str, default: Any = None) -> Any:
        try:
            prefs = self._store.recall(_PREFS_ID)
        except Exception:
            return default
        return prefs.get(key, default)

    def all_preferences(self) -> dict[str, Any]:
        try:
            return dict(self._store.recall(_PREFS_ID))
        except Exception:
            return {}

    # ---- context (working memory; volatile, not durable) ----
    def set_context(self, **fields: Any) -> None:
        try:
            ctx = dict(self._store.get_working(_CONTEXT_ID))
        except Exception:
            ctx = {}
        ctx.update(fields)
        self._store.put_working(_CONTEXT_ID, ctx)

    def get_context(self, key: str, default: Any = None) -> Any:
        try:
            ctx = self._store.get_working(_CONTEXT_ID)
        except Exception:
            return default
        return ctx.get(key, default)

    def clear_context(self) -> None:
        self._store.clear_working()
