"""Hermes CTL — load brain definitions from the llmfit brains.yaml.

The `llmfit` brain config (`~/.config/hermes/brains.yaml`) is the canonical
source of truth for which models serve which role (fast/agent/max). This
module adapts that config into the `Brain` descriptors used by `HttpRouter`,
so HADA's intelligence layer is driven by the same llmfit brains that the
desktop GUI uses.

Brain endpoint format in brains.yaml:
    brains:
      fast:
        endpoint: http://127.0.0.1:8080/v1/chat/completions
        model: /models/model.gguf
`Brain.url` is the base (endpoint with `/chat/completions` stripped) because
`HttpRouter` appends `/chat/completions` itself.

Env override: `HERMES_BRAIN_HOST` rewrites a loopback host in the endpoint to
a reachable host (e.g. the Mac's Tailscale IP) so the hada box can reach brains
served on another machine. Fail-closed: missing roles raise ValueError.
"""

from __future__ import annotations

import os
from typing import Any

from hermes_ctl.intelligence.router import Brain, BrainRole

DEFAULT_BRAINS_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "hermes", "brains.yaml"
)
_BRAIN_ROLES: tuple[BrainRole, ...] = ("fast", "agent", "max")


def _strip_endpoint(endpoint: str) -> str:
    """Return the base URL (without the trailing /chat/completions)."""
    return endpoint.replace("/chat/completions", "").rstrip("/")


def _apply_host_override(endpoint: str, host: str) -> str:
    """Replace a loopback host with `host` so remote brains are reachable."""
    for lb in ("127.0.0.1", "localhost", "0.0.0.0"):
        if endpoint.startswith(f"http://{lb}") or endpoint.startswith(f"https://{lb}"):
            return endpoint.replace(f"://{lb}", f"://{host}", 1)
    return endpoint


def load_brains(path: str | None = None) -> list[Brain]:
    """Load brain descriptors from the llmfit brains.yaml.

    `path` defaults to ~/.config/hermes/brains.yaml. Raises ValueError if a
    required role (fast/agent/max) is missing.
    """
    import yaml  # deferred: stdlib has no yaml; llmfit env provides it

    path = path or os.environ.get("HERMES_BRAINS_PATH", DEFAULT_BRAINS_PATH)
    with open(path, "r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}

    roles = doc.get("brains", doc)
    host_override = os.environ.get("HERMES_BRAIN_HOST")
    brains: list[Brain] = []
    for role in _BRAIN_ROLES:
        entry = roles.get(role)
        if not entry or "endpoint" not in entry:
            raise ValueError(f"brains.yaml missing role '{role}' (need endpoint+model)")
        endpoint = entry["endpoint"]
        if host_override:
            endpoint = _apply_host_override(endpoint, host_override)
        brains.append(
            Brain(
                name=role,
                role=role,
                url=_strip_endpoint(endpoint),
                model=entry.get("model", role),
                auth_header=None,
            )
        )
    return brains
