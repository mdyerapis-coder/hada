"""Authentication seam implementation for the HADA Android API.

Provides HMAC-signed bearer tokens, token validation, and the seam
interfaces (TokenProvider, TokenValidator) that allow the auth layer
to be swapped out without changing consumers.

Usage:
    >>> from android.auth import HmacTokenSeam
    >>> seam = HmacTokenSeam(secret="dev-secret-at-least-32-chars!!")
    >>> token = seam.create_token(user_id="member-01", role="adult")
    >>> result = seam.validate(token)
    >>> result.success
    True
    >>> result.role
    'adult'
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


# ── Data Objects ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthResult:
    """Result of a token validation attempt.

    Attributes:
        success: Whether the token is valid and not expired.
        user_id: The authenticated user's ID (only when *success* is True).
        role: The authenticated user's role string (only when *success* is True).
        reason: Human-readable failure reason (only when *success* is False).
        expires_at: Token expiry datetime (only when *success* is True).
    """

    success: bool
    user_id: str | None = None
    role: str | None = None
    reason: str | None = None
    expires_at: datetime | None = None


# ── Seam Protocols ───────────────────────────────────────────────────


class TokenProvider(Protocol):
    """Protocol for creating signed bearer tokens."""

    def create_token(
        self,
        user_id: str,
        role: str,
        ttl_seconds: int | None = None,
    ) -> str:
        """Create and return a signed bearer token string."""
        ...


class TokenValidator(Protocol):
    """Protocol for validating and decoding bearer tokens."""

    def validate(self, token: str) -> AuthResult:
        """Validate a token and return an AuthResult."""
        ...


# ── Default TTLs ────────────────────────────────────────────────────

DEFAULT_TTL: dict[str, int] = {
    "adult": 86400,    # 24 hours
    "child": 14400,    #  4 hours
}

_MIN_SECRET_LENGTH: int = 32


# ── Default HMAC Implementation ─────────────────────────────────────


class HmacTokenSeam:
    """HMAC-SHA256 based token seam for development and initial deployment.

    Creates and validates tokens using a shared secret. Token format::

        base64(payload) . base64(signature)

    where *payload* is a JSON object with ``sub``, ``role``, ``iat``,
    ``exp``, and ``jti`` claims, and *signature* is the HMAC-SHA256
    digest of the payload.

    Args:
        secret: HMAC key (must be at least 32 characters). If omitted,
            falls back to the ``HADA_TOKEN_SECRET`` environment variable.
            When ``HADA_ENV=development`` and no secret is set, a hardcoded
            development secret is used (never in production).

    Raises:
        ValueError: If no usable secret is found outside development mode.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = self._resolve_secret(secret)

    # ── TokenProvider ────────────────────────────────────────────────

    def create_token(
        self,
        user_id: str,
        role: str,
        ttl_seconds: int | None = None,
    ) -> str:
        """Create an HMAC-signed bearer token.

        Args:
            user_id: Unique identifier for the user.
            role: Role string (``"adult"`` or ``"child"``).
            ttl_seconds: Token lifetime in seconds. Defaults to the
                role-specific default (adult=86400, child=14400).

        Returns:
            A signed token string.
        """
        if ttl_seconds is None:
            ttl_seconds = DEFAULT_TTL.get(role, 3600)

        now = int(time.time())
        payload = {
            "sub": user_id,
            "role": role,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid.uuid4()),
        }

        payload_b64 = self._encode_b64(json.dumps(payload, separators=(",", ":")))
        signature = self._sign(payload_b64)
        return f"{payload_b64}.{signature}"

    # ── TokenValidator ───────────────────────────────────────────────

    def validate(self, token: str) -> AuthResult:
        """Validate a token and return the auth result.

        Checks: format, signature, expiry.
        """
        try:
            parts = token.split(".")
            if len(parts) != 2:
                return AuthResult(False, reason="malformed_token")

            payload_b64, signature_b64 = parts

            # Verify signature
            expected_sig = self._sign(payload_b64)
            if not hmac.compare_digest(expected_sig, signature_b64):
                return AuthResult(False, reason="invalid_signature")

            # Decode payload
            payload_bytes = self._decode_b64(payload_b64)
            payload: dict = json.loads(payload_bytes)

            # Check expiry
            exp = payload.get("exp", 0)
            now = int(time.time())
            if now > exp:
                return AuthResult(False, reason="token_expired")

            return AuthResult(
                success=True,
                user_id=payload.get("sub"),
                role=payload.get("role"),
                expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
            )

        except (ValueError, json.JSONDecodeError, KeyError):
            return AuthResult(False, reason="malformed_token")

    # ── Internal Helpers ─────────────────────────────────────────────

    def _sign(self, data: str) -> str:
        """Return the HMAC-SHA256 digest of *data* as base64."""
        digest = hmac.new(
            self._secret.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return self._encode_b64(digest)

    @staticmethod
    def _encode_b64(data: bytes | str) -> str:
        """URL-safe base64 encode (no padding)."""
        import base64

        if isinstance(data, str):
            data = data.encode("utf-8")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_b64(data: str) -> bytes:
        """URL-safe base64 decode (tolerates missing padding)."""
        import base64

        # Re-pad if necessary
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    @staticmethod
    def _resolve_secret(secret: str | None) -> str:
        """Resolve the HMAC secret from arg, env, or dev fallback."""
        if secret is not None:
            return secret

        env_secret = os.environ.get("HADA_TOKEN_SECRET")
        if env_secret:
            return env_secret

        env_mode = os.environ.get("HADA_ENV", "")
        if env_mode == "development":
            # Development-only secret — never use in production.
            return "dev-secret-do-not-use-in-production-32chr"

        raise ValueError(
            "No token secret configured. Set HADA_TOKEN_SECRET or "
            "HADA_ENV=development."
        )


# ── Helper: guess default ttl ───────────────────────────────────────


def default_ttl_for_role(role: str) -> int:
    """Return the default TTL (seconds) for a given role string."""
    return DEFAULT_TTL.get(role, 3600)
