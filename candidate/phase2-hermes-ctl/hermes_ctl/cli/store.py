"""Shared store helper for CLI commands."""

from __future__ import annotations

import os

from hermes_ctl.memory.store import MemoryStore


def _store() -> MemoryStore:
    """Create a MemoryStore pointed at HERMES_CTL_STORE or the default inbox path."""
    path = os.environ.get(
        "HERMES_CTL_STORE",
        os.path.join(os.path.dirname(__file__), "..", "..", ".comms", "inbox.json"),
    )
    path = os.path.abspath(path)
    return MemoryStore(persist_path=path)
