# Authentication Seam Design

> **Stage:** Phase 4 — Android Stage 1
> **Status:** Draft
> **Version:** 1.0.0

## 1. Purpose

The authentication seam defines a swappable boundary between the HADA
backend's token verification logic and the rest of the system. It enables:

1. **Switching token providers** without changing callers (e.g. from
   local HMAC tokens to Firebase Auth, OAuth2, or a 3rd-party IdP).
2. **Unit testing** by injecting fake token providers or validators.
3. **Role-aware authorization** that is decoupled from token mechanics.

## 2. Design Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Android Client                       │
│  ┌──────────────┐   ┌───────────────────┐               │
│  │ Token Store   │──▶│ Auth Header       │               │
│  │ (encrypted)   │   │ (Authorization:   │               │
│  └──────────────┘   │  Bearer <token>)   │               │
│                     └────────┬──────────┘               │
└──────────────────────────────┼──────────────────────────┘
                               │ HTTP
                               ▼
┌─────────────────────────────────────────────────────────┐
│              HADA Backend (hermes_ctl)                   │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────┐           │
│  │   TokenProvider   │    │  TokenValidator  │  ◀── Seam │
│  │ (create tokens)   │    │ (verify tokens)  │           │
│  └────────┬─────────┘    └────────┬─────────┘           │
│           │                       │                      │
│           ▼                       ▼                      │
│  ┌──────────────────────────────────────────┐           │
│  │            Authorization Layer            │           │
│  │  ┌──────────┐  ┌──────────┐  ┌────────┐ │           │
│  │  │   Role   │  │Permission│  │  AuthZ │ │           │
│  │  │ Provider │  │   Check  │  │ Guard  │ │           │
│  │  └──────────┘  └──────────┘  └────────┘ │           │
│  └──────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

## 3. Seam Interfaces (Protocol)

The seam is defined as a **callable protocol** so that the runtime binding
can be swapped without inheritance.

### `TokenProvider`

```python
class TokenProvider(Protocol):
    """Creates signed tokens for authenticated users."""

    def create_token(self, user_id: str, role: str, ttl_seconds: int | None = None) -> str:
        """Create a signed bearer token with given claims."""
        ...
```

### `TokenValidator`

```python
class TokenValidator(Protocol):
    """Validates and decodes bearer tokens."""

    def validate(self, token: str) -> AuthResult:
        """Return AuthResult with user_id, role, expiry or error."""
        ...
```

### `AuthResult`

```python
@dataclass(frozen=True)
class AuthResult:
    success: bool
    user_id: str | None = None
    role: str | None = None
    reason: str | None = None  # Human-readable failure reason
    expires_at: datetime | None = None
```

## 4. Default Implementation: `HmacTokenSeam`

For the initial contract-creation phase the default implementation is
an HMAC-signed token seam.

### Token Structure

Base64-encoded JSON payload with an HMAC-SHA256 signature appended:

```
base64(payload) . base64(signature)
```

### Payload Claims

| Claim | Type   | Required | Description                            |
|-------|--------|----------|----------------------------------------|
| `sub` | string | yes      | User ID (e.g. `member-01`)             |
| `role`| string | yes      | `adult` or `child`                     |
| `iat` | int    | yes      | Issued-at Unix timestamp               |
| `exp` | int    | yes      | Expiry Unix timestamp                  |
| `jti` | string | yes      | Unique token ID (UUID v4)              |

### Key Management

- A `TOKEN_SECRET` environment variable or a `.env` file provides the
  HMAC key (min 32 bytes).
- During development a default key can be used **only** when
  `HADA_ENV=development`.
- Production must set `TOKEN_SECRET` to a strong random value.

### Token Lifespan

| Role   | Default TTL | Configurable? |
|--------|-------------|---------------|
| Adult  | 24 hours    | Yes           |
| Child  | 4 hours     | Yes           |

### Token Revocation

An optional `TokenBlacklist` protocol allows revoking tokens before
expiry. The default implementation uses an in-memory set (lost on
restart). Production deployments should use Valkey/Redis.

## 5. Dependency Injection

The seam is wired at startup:

```python
# In hermes_ctl bootstrap
from android.auth import HmacTokenSeam

seam = HmacTokenSeam(secret=os.environ["TOKEN_SECRET"])
# Inject into request pipeline
app.dependency_overrides[TokenValidator] = seam.validate
app.dependency_overrides[TokenProvider] = seam.create_token
```

For tests:

```python
# Inject a fake validator that always returns a known role
seam = FakeTokenSeam(allowed_role="adult")
```

## 6. Error Handling

| Situation                | `AuthResult.success` | `reason`                   |
|--------------------------|----------------------|----------------------------|
| Valid token              | `True`              | —                          |
| Expired token            | `False`             | `"token_expired"`          |
| Bad signature            | `False`             | `"invalid_signature"`      |
| Malformed token          | `False`             | `"malformed_token"`        |
| Revoked token            | `False`             | `"token_revoked"`          |
| Missing `Authorization`  | `False`             | `"missing_token"`          |

## 7. Migration Path

| Phase | Auth Mechanism               | Notes                    |
|-------|------------------------------|--------------------------|
| 1     | HMAC token (this seam)       | Contract + dev phase     |
| 2     | Firebase Auth integration    | Android native auth      |
| 3     | OAuth2 / OpenID Connect      | Production-grade         |

The seam protocol ensures no consumer code changes between phases.
