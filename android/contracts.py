"""Versioned API contract dataclass definitions for the HADA Android API.

Defines the request/response models that the hermes_ctl module uses to
communicate with the Android client. Every response carries the negotiated
API version for drift detection.

All models use frozen dataclasses for immutability and include basic
validation in ``post_init`` or factory methods.

Usage:
    >>> from android.contracts import (
    ...     ApiVersionInfo, Task, TaskListResponse, VersionedError,
    ...     parse_version, is_version_compatible,
    ... )
    >>> info = ApiVersionInfo()
    >>> info.api_version
    '1.0.0'
    >>> parse_version("1.0.0")
    (1, 0, 0)
    >>> is_version_compatible("1.0.0", min_version="1.0.0")
    True
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

# ── Versioning Constants ─────────────────────────────────────────────

CURRENT_API_VERSION: str = "1.0.0"
SUPPORTED_VERSIONS: tuple[str, ...] = ("1.0.0",)
MIN_API_VERSION: str = "1.0.0"
SERVER_NAME: str = "hada-hermes-ctl"

_VERSION_PATTERN: re.Pattern = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

TData = TypeVar("TData")


# ── Version Helpers ──────────────────────────────────────────────────


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse ``"MAJOR.MINOR.PATCH"`` into a tuple of ints.

    Raises ValueError if the string is not valid semver.
    """
    m = _VERSION_PATTERN.match(version_str.strip())
    if not m:
        raise ValueError(
            f"Invalid version string '{version_str}'. "
            f"Expected MAJOR.MINOR.PATCH (e.g. 1.0.0)."
        )
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def is_version_compatible(
    client_version: str,
    *,
    min_version: str = MIN_API_VERSION,
    supported: list[str] | None = None,
) -> bool:
    """Check whether *client_version* is compatible with the server.

    A version is compatible if:
    1. Its MAJOR matches the MAJOR of at least one supported version.
    2. It is >= *min_version*.

    Args:
        client_version: The version string the client sent.
        min_version: The minimum allowed version (default: ``MIN_API_VERSION``).
        supported: List of server-supported versions (default: ``SUPPORTED_VERSIONS``).

    Returns:
        True if the version is compatible, False otherwise.
    """
    if supported is None:
        supported = ["1.0.0"]

    try:
        client = parse_version(client_version)
        min_v = parse_version(min_version)
    except ValueError:
        return False

    # Must be >= minimum
    if client < min_v:
        return False

    # MAJOR must match at least one supported version
    client_major = client[0]
    for sv in supported:
        try:
            sv_parts = parse_version(sv)
        except ValueError:
            continue
        if sv_parts[0] == client_major:
            return True

    return False


def negotiate_version(
    client_version: str | None,
    *,
    supported: list[str] | None = None,
    min_version: str | None = None,
) -> str:
    """Negotiate the API version between client and server.

    Args:
        client_version: The version the client requested (or None).
        supported: Server-supported versions (default: ``SUPPORTED_VERSIONS``).
        min_version: Minimum acceptable version (default: ``MIN_API_VERSION``).

    Returns:
        The negotiated version string.

    Raises:
        ValueError: If negotiation fails (version incompatible).
    """
    if supported is None:
        supported = ["1.0.0"]
    if min_version is None:
        min_version = "1.0.0"

    if client_version is None:
        # Client didn't specify — return the latest supported
        return supported[-1]

    if not is_version_compatible(
        client_version, min_version=min_version, supported=supported
    ):
        raise ValueError(
            f"Version {client_version} is not compatible. "
            f"Supported: {supported}, min: {min_version}"
        )

    return client_version


# ── Response Envelope ────────────────────────────────────────────────


@dataclass(frozen=True)
class VersionedError:
    """Error payload returned inside a VersionedResponse."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VersionedResponse(Generic[TData]):
    """Top-level response envelope wrapping every API response.

    Attributes:
        api_version: The negotiated API version.
        data: The response payload (None when error is set).
        error: Optional error payload (None for success responses).
    """

    api_version: str = CURRENT_API_VERSION
    data: TData | None = None
    error: VersionedError | None = None


# ── Version Endpoint ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ApiVersionInfo:
    """Response model for ``GET /api/v1/version``."""

    api_version: str = CURRENT_API_VERSION
    supported_versions: tuple[str, ...] = tuple(SUPPORTED_VERSIONS)
    min_version: str = MIN_API_VERSION
    server_name: str = SERVER_NAME


# ── Household ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HouseholdStatus:
    """Lightweight household status snapshot."""

    household_name: str
    member_count: int
    active_tasks: int
    overdue_tasks: int
    unread_notifications: int
    updated_at: datetime


# ── Tasks ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Task:
    """A single household task."""

    id: str
    title: str
    status: str  # "pending" | "in_progress" | "completed"
    assigned_to: str | None = None
    created_by: str | None = None
    due_date: datetime | None = None
    priority: str = "medium"  # "low" | "medium" | "high"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskListData:
    """Paginated task list."""

    items: tuple[Task, ...]
    total: int
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class TaskListResponse(VersionedResponse[TaskListData]):
    """Full list response (envelope + task list)."""

    pass


@dataclass(frozen=True)
class TaskDetailResponse(VersionedResponse[Task]):
    """Single task detail response."""

    pass


# ── Members ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Member:
    """A household member."""

    id: str
    name: str
    role: str  # "adult" | "child"
    avatar_url: str | None = None
    is_online: bool = False


@dataclass(frozen=True)
class MemberListData:
    """Paginated member list."""

    items: tuple[Member, ...]
    total: int


@dataclass(frozen=True)
class MemberListResponse(VersionedResponse[MemberListData]):
    pass


@dataclass(frozen=True)
class MemberDetailResponse(VersionedResponse[Member]):
    pass


# ── Schedules ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScheduleEntry:
    """A single schedule entry."""

    id: str
    title: str
    start_time: datetime
    end_time: datetime
    assigned_to: tuple[str, ...] = ()
    location: str | None = None
    recurrence: str | None = None  # RRULE string or null


@dataclass(frozen=True)
class ScheduleListData:
    """Paginated schedule list."""

    items: tuple[ScheduleEntry, ...]
    total: int


@dataclass(frozen=True)
class ScheduleListResponse(VersionedResponse[ScheduleListData]):
    pass


# ── Notifications ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Notification:
    """A single notification for a user."""

    id: str
    type: str
    title: str
    body: str
    is_read: bool = False
    created_at: datetime | None = None
    target_link: str | None = None


@dataclass(frozen=True)
class NotificationListData:
    """Paginated notification list."""

    items: tuple[Notification, ...]
    total: int
    unread_count: int = 0


@dataclass(frozen=True)
class NotificationListResponse(VersionedResponse[NotificationListData]):
    pass


# ── Error Response Factories ─────────────────────────────────────────


def error_response(
    code: str,
    message: str,
    *,
    api_version: str = CURRENT_API_VERSION,
    details: dict[str, Any] | None = None,
) -> VersionedResponse:
    """Build a standard error response envelope."""
    return VersionedResponse(
        api_version=api_version,
        data=None,
        error=VersionedError(
            code=code,
            message=message,
            details=details or {},
        ),
    )
