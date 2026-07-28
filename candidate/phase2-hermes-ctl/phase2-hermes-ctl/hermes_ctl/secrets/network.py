"""Hermes CTL — network egress policy seam (Phase 2, gated integration).

A fail-closed allowlist for outbound network destinations, so the governed
appliance only reaches explicitly-permitted hosts. Channels consult this before
opening a connection; anything not in the allowlist is refused (default-deny).

Offline-testable: the policy is a pure allowlist matcher, no sockets opened.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Endpoint:
    scheme: str
    host: str
    port: int

    @classmethod
    def from_url(cls, url: str) -> "Endpoint":
        p = urlparse(url)
        port = p.port or (443 if p.scheme == "https" else 80)
        return cls(scheme=p.scheme or "https", host=p.netloc.split(":")[0], port=port)

    def __str__(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


class NetworkPolicy:
    """Default-deny egress allowlist. Permits only registered endpoints/hosts."""

    def __init__(self, allowed: list[str] | None = None) -> None:
        # store as ("scheme", "host", port) tuples
        self._allowed: set[tuple[str, str, int]] = set()
        self._allowed_hosts: set[str] = set()
        for a in (allowed or []):
            self.register(a)

    def register(self, endpoint: str) -> None:
        ep = Endpoint.from_url(endpoint)
        self._allowed.add((ep.scheme, ep.host, ep.port))

    def register_host(self, host: str) -> None:
        """Allow ANY scheme/port for a host (broad; use sparingly)."""
        self._allowed_hosts.add(host)

    def allows(self, url: str) -> bool:
        ep = Endpoint.from_url(url)
        return (ep.scheme, ep.host, ep.port) in self._allowed or ep.host in self._allowed_hosts

    def require(self, url: str) -> None:
        """Raise NetworkDenied if the destination is not permitted."""
        if not self.allows(url):
            raise NetworkDenied(f"egress denied (not in allowlist): {url}")

    def endpoints(self) -> list[str]:
        return [f"{s}://{h}:{p}" for (s, h, p) in sorted(self._allowed)]


class NetworkDenied(Exception):
    """Raised when an egress destination is not permitted by the policy."""


# Default governed allowlist for the contact transports.
DEFAULT_CONTACT_ALLOWLIST = [
    "https://api.telegram.org:443",
    "imaps://imap.gmail.com:993",
    "smtps://smtp.gmail.com:465",
]


def default_contact_policy() -> NetworkPolicy:
    return NetworkPolicy(DEFAULT_CONTACT_ALLOWLIST)
