"""Hermes CTL — governed secret retrieval seam (Phase 2, gated integration).

Provides a fail-closed interface for obtaining secrets at runtime WITHOUT
persisting them. Channels depend on `SecretStore.get(name)` rather than reading
`os.environ` ad-hoc, so secret access is explicit, mockable, and auditable.

Backends:
  - EnvSecretStore   : reads from process env / contact.env (current deploy).
  - DictSecretStore  : in-memory (tests, runtime injection).
  - BitwardenSecretStore : resolves via `bw get` with an injected session
                           (manual unlock step; never stores the secret).

Fail-closed: every backend raises SecretError on a missing secret. Nothing
here writes a secret to disk.
"""

from __future__ import annotations

import abc
import os
from typing import Any


class SecretError(Exception):
    """Raised when a requested secret is unavailable (fail-closed)."""


class SecretStore(abc.ABC):
    """Typed, fail-closed secret source."""

    @abc.abstractmethod
    def get(self, name: str) -> str:
        """Return the secret value, or raise SecretError if absent."""


class EnvSecretStore(SecretStore):
    """Reads secrets from the process environment (contact.env via EnvironmentFile)."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._env = env if env is not None else os.environ

    def get(self, name: str) -> str:
        value = self._env.get(name)
        if not value:
            raise SecretError(f"missing secret: {name}")
        return value


class DictSecretStore(SecretStore):
    """In-memory store (tests + runtime injection)."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def get(self, name: str) -> str:
        if name not in self._secrets:
            raise SecretError(f"missing secret: {name}")
        return self._secrets[name]


class BitwardenSecretStore(SecretStore):
    """Resolves secrets from Bitwarden via the `bw` CLI with an injected session.

    The mapping from a logical secret name (e.g. ``GMAIL_APP_PASSWORD``) to a
    Bitwarden item is provided by ``resolver`` — keeping BW item ids out of code.
    Requires the vault to be unlocked (session injected at runtime, never stored).
    """

    def __init__(
        self,
        resolver,  # callable(str) -> str  (name -> bw item id)
        session: str | None = None,
        bw_bin: str = "bw",
    ) -> None:
        self._resolver = resolver
        self._session = session
        self._bw = bw_bin

    def get(self, name: str) -> str:
        import subprocess

        item_id = self._resolver(name)
        env = dict(os.environ)
        if self._session:
            env["BW_SESSION"] = self._session
        try:
            out = subprocess.run(
                [self._bw, "get", "password", item_id],
                capture_output=True, text=True, timeout=20, env=env, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise SecretError(f"bitwarden lookup failed for {name}: {exc}") from exc
        value = out.stdout.strip()
        if not value:
            raise SecretError(f"empty secret from bitwarden for {name}")
        return value
