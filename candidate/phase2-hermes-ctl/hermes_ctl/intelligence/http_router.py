"""Hermes CTL — HTTP model router (Phase 2, gated integration).

Targets a running model-gateway (the llmfit-gui service) over HTTP, implementing
the `Router` seam. The per-brain auth header value is injected at request time
from the environment (key name from `Brain.auth_header`); the secret is never
stored in code or repo.

Stdlib-only (urllib). `complete()` makes a real chat completion call; tests
monkeypatch `_post` for offline verification.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from hermes_ctl.intelligence.router import Brain, LocalRouter, Router, BrainRole


class HttpRouter(Router):
    """Routes to a live gateway. `select()` is rule-based (inherits LocalRouter
    behaviour); `complete()` performs the real completion call."""

    def __init__(self, brains: list[Brain], *, token_resolver: Any = None) -> None:
        self._local = LocalRouter(brains)
        # token_resolver: callable(header_name) -> secret, or None -> os.environ
        self._token_resolver = token_resolver or (lambda h: os.environ.get(h or "") if h else None)

    def select(self, role: BrainRole, *, complexity: float = 0.0) -> Brain:
        return self._local.select(role, complexity=complexity)

    def register(self, brain: Brain) -> None:
        self._local.register(brain)

    def _auth_headers(self, brain: Brain) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if brain.auth_header:
            secret = self._token_resolver(brain.auth_header)
            if secret:
                headers[brain.auth_header] = secret
        return headers

    def _post(self, brain: Brain, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{brain.url.rstrip('/')}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._auth_headers(brain), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # pragma: no cover - network path
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"model call failed: {e.code} {body}") from e

    def complete(self, role: BrainRole, prompt: str, *, max_tokens: int = 512) -> str:
        brain = self.select(role)
        result = self._post(
            brain,
            {
                "model": brain.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
        )
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:  # pragma: no cover
            raise RuntimeError(f"unexpected model response: {result}") from e

    def complete_json(self, role: BrainRole, prompt: str, *, max_tokens: int = 1024) -> str:
        """Complete a prompt using the OpenAI JSON-object response contract.

        Structured HADA jobs use this path so local models cannot return prose
        or code fences. Plain-text callers continue to use ``complete``.
        """
        brain = self.select(role)
        result = self._post(
            brain,
            {
                "model": brain.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:  # pragma: no cover
            raise RuntimeError(f"unexpected model response: {result}") from e
