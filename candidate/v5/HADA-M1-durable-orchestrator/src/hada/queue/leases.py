from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class LeaseError(RuntimeError):
    pass


class LeaseBackend(Protocol):
    def acquire(self, key: str, value: str, ttl_milliseconds: int) -> bool: ...

    def renew(self, key: str, value: str, ttl_milliseconds: int) -> bool: ...

    def release(self, key: str, value: str) -> bool: ...


_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
else
  return 0
end
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
else
  return 0
end
"""


class RedisLeaseBackend:
    def __init__(self, url: str) -> None:
        try:
            import redis
        except ImportError as exc:
            raise LeaseError("redis package is required for Valkey leases") from exc
        self._client: Any = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

    def acquire(self, key: str, value: str, ttl_milliseconds: int) -> bool:
        return bool(self._client.set(key, value, nx=True, px=ttl_milliseconds))

    def renew(self, key: str, value: str, ttl_milliseconds: int) -> bool:
        return bool(self._client.eval(_RENEW_SCRIPT, 1, key, value, ttl_milliseconds))

    def release(self, key: str, value: str) -> bool:
        return bool(self._client.eval(_RELEASE_SCRIPT, 1, key, value))


class InMemoryLeaseBackend:
    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _purge(self, key: str) -> None:
        current = self._values.get(key)
        if current is not None and current[1] <= time.monotonic():
            del self._values[key]

    def acquire(self, key: str, value: str, ttl_milliseconds: int) -> bool:
        with self._lock:
            self._purge(key)
            if key in self._values:
                return False
            self._values[key] = (value, time.monotonic() + ttl_milliseconds / 1000)
            return True

    def renew(self, key: str, value: str, ttl_milliseconds: int) -> bool:
        with self._lock:
            self._purge(key)
            current = self._values.get(key)
            if current is None or current[0] != value:
                return False
            self._values[key] = (value, time.monotonic() + ttl_milliseconds / 1000)
            return True

    def release(self, key: str, value: str) -> bool:
        with self._lock:
            self._purge(key)
            current = self._values.get(key)
            if current is None or current[0] != value:
                return False
            del self._values[key]
            return True


class Lease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    owner: str
    token: str = Field(min_length=32)
    expires_at: datetime


class LeaseManager:
    def __init__(self, backend: LeaseBackend, *, namespace: str = "hada") -> None:
        self.backend = backend
        self.namespace = namespace

    def _key(self, name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,255}", name):
            raise LeaseError(f"invalid lease name: {name!r}")
        return f"{self.namespace}:lease:{name}"

    @staticmethod
    def _value(owner: str, token: str) -> str:
        return json.dumps({"owner": owner, "token": token}, sort_keys=True, separators=(",", ":"))

    def acquire(self, name: str, owner: str, *, ttl_seconds: int) -> Lease | None:
        if ttl_seconds < 1 or ttl_seconds > 86400:
            raise LeaseError("lease TTL must be between 1 and 86400 seconds")
        token = secrets.token_urlsafe(32)
        value = self._value(owner, token)
        if not self.backend.acquire(self._key(name), value, ttl_seconds * 1000):
            return None
        return Lease(
            name=name,
            owner=owner,
            token=token,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    def renew(self, lease: Lease, *, ttl_seconds: int) -> Lease:
        value = self._value(lease.owner, lease.token)
        if not self.backend.renew(self._key(lease.name), value, ttl_seconds * 1000):
            raise LeaseError("lease is no longer owned by this token")
        return lease.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(seconds=ttl_seconds)}
        )

    def release(self, lease: Lease) -> None:
        value = self._value(lease.owner, lease.token)
        if not self.backend.release(self._key(lease.name), value):
            raise LeaseError("lease is no longer owned by this token")
