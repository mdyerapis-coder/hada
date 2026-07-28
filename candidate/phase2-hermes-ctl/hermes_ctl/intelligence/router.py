"""Hermes CTL — Intelligence subsystem (Phase 2).

Foundation interface for model routing: local LLM routing, cloud fallback,
and the seam for voice/mobile. Per the governance boundary, this module makes
NO live model calls and holds NO credentials. It defines:

  - `Brain`: a model endpoint descriptor (url, model name, role, auth header
    name) — the auth *header name* is configured, never the secret value.
  - `Router` (ABC): select a brain for a request.
  - `LocalRouter`: rule-based selection (fast/agent/max) usable offline and
    fully testable. A future `HttpRouter` can target the running llmfit-gui
    service (external to this repo) without changing callers.

Real inference wiring (loading GGUF, GPU/CPU scheduling, cloud API keys) is
Phase 6 (Infrastructure) and requires human approval — it is intentionally
out of scope here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

BrainRole = Literal["fast", "agent", "max"]


@dataclass
class Brain:
    """A model endpoint descriptor. `auth_header` names the header to send;
    the secret value is supplied at request time, never stored here."""

    name: str
    role: BrainRole
    url: str
    model: str
    auth_header: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "url": self.url,
            "model": self.model,
            "auth_header": self.auth_header,
        }


class Router(ABC):
    """Selects a brain for a request."""

    @abstractmethod
    def select(self, role: BrainRole, *, complexity: float = 0.0) -> Brain:
        """Return the brain to use. Raises if no brain satisfies the request."""


class LocalRouter(Router):
    """Rule-based, offline router. No network, no credentials."""

    def __init__(self, brains: list[Brain]) -> None:
        self._brains = {b.role: b for b in brains}

    def select(self, role: BrainRole, *, complexity: float = 0.0) -> Brain:
        brain = self._brains.get(role)
        if brain is None:
            raise KeyError(f"no brain registered for role: {role}")
        # complexity is accepted for interface completeness; LocalRouter maps
        # role -> brain directly. A future router can use it to fall back.
        return brain

    def register(self, brain: Brain) -> None:
        self._brains[brain.role] = brain


def default_brains() -> list[Brain]:
    """The three-brain layout matching the deployed llmfit-gui router.

    auth_header names the header the HTTP transport must set; the value is
    injected at request time from the environment, never persisted.
    """
    return [
        Brain(name="fast", role="fast", url="http://localhost:8080/v1", model="qwen3b", auth_header="X-Hermes-Fast-Key"),
        Brain(name="agent", role="agent", url="http://localhost:8081/v1", model="hermes-7b", auth_header="X-Hermes-Agent-Key"),
        Brain(name="max", role="max", url="http://localhost:8081/v1", model="hermes-7b", auth_header="X-Hermes-Max-Key"),
    ]
