"""Adult/Child role definitions and authorization logic for the Android API.

This module defines the role model, granular permissions, and the
authorization check function used by the auth seam to determine whether
a given role is permitted to perform a specific action.

Usage:
    >>> from android.roles import Role, Permission, authorize
    >>> authorize(Role.ADULT, Permission.TASKS_READ_ALL)
    True
    >>> authorize(Role.CHILD, Permission.SETTINGS_MANAGE)
    False
"""

from __future__ import annotations

import enum
from typing import Final


class Role(str, enum.Enum):
    """The two built-in roles supported by the HADA Android API.

    Roles are hierarchical in purpose but have independent permission
    sets — there is no automatic inheritance.
    """

    ADULT = "adult"
    CHILD = "child"

    def __str__(self) -> str:
        return self.value


class Permission(str, enum.Enum):
    """Granular permission constants used in authorization checks.

    Each constant represents a single read or management action that a
    role may or may not be granted.
    """

    # Household
    HOUSEHOLD_READ = "household:read"

    # Tasks
    TASKS_READ_ALL = "tasks:read_all"
    TASKS_READ_OWN = "tasks:read_own"

    # Members
    MEMBERS_READ_ALL = "members:read_all"
    MEMBERS_READ_BASIC = "members:read_basic"
    MEMBER_READ_OWN = "member:read_own"

    # Schedules
    SCHEDULES_READ_ALL = "schedules:read_all"
    SCHEDULES_READ_FAMILY = "schedules:read_family"

    # Notifications
    NOTIFICATIONS_READ_OWN = "notifications:read_own"
    NOTIFICATIONS_READ_ALL = "notifications:read_all"

    # Management (adult-only)
    SETTINGS_MANAGE = "settings:manage"
    MEMBERS_MANAGE = "members:manage"
    AUDIT_READ = "audit:read"


# ── Permission Sets ──────────────────────────────────────────────────

ADULT_PERMISSIONS: Final[frozenset[Permission]] = frozenset({
    Permission.HOUSEHOLD_READ,
    Permission.TASKS_READ_ALL,
    Permission.TASKS_READ_OWN,
    Permission.MEMBERS_READ_ALL,
    Permission.MEMBERS_READ_BASIC,
    Permission.MEMBER_READ_OWN,
    Permission.SCHEDULES_READ_ALL,
    Permission.SCHEDULES_READ_FAMILY,
    Permission.NOTIFICATIONS_READ_OWN,
    Permission.NOTIFICATIONS_READ_ALL,
    Permission.SETTINGS_MANAGE,
    Permission.MEMBERS_MANAGE,
    Permission.AUDIT_READ,
})

CHILD_PERMISSIONS: Final[frozenset[Permission]] = frozenset({
    Permission.HOUSEHOLD_READ,
    Permission.TASKS_READ_OWN,
    Permission.MEMBERS_READ_BASIC,
    Permission.MEMBER_READ_OWN,
    Permission.SCHEDULES_READ_FAMILY,
    Permission.NOTIFICATIONS_READ_OWN,
})

# ── Role → Permission Lookup ────────────────────────────────────────

_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADULT: ADULT_PERMISSIONS,
    Role.CHILD: CHILD_PERMISSIONS,
}


def get_permissions(role: Role) -> frozenset[Permission]:
    """Return the immutable permission set for a given role.

    Raises KeyError if *role* is unknown.
    """
    return _ROLE_PERMISSIONS[role]


def has_permission(role: Role, permission: Permission) -> bool:
    """Check whether *role* is granted *permission*.

    This is the core authorization check. It returns ``True`` if the
    permission is present in the role's permission set, ``False``
    otherwise.

    Args:
        role: The role to check (Role.ADULT or Role.CHILD).
        permission: The permission to test.

    Returns:
        True if authorised, False if denied.
    """
    return permission in _ROLE_PERMISSIONS.get(role, frozenset())


# Convenience alias — ``authorize`` reads better in guard code.
authorize = has_permission


def all_permissions() -> frozenset[Permission]:
    """Return every known permission (union of all roles)."""
    return frozenset(Permission)


def role_from_string(value: str) -> Role:
    """Parse ``"adult"`` / ``"child"`` to a Role enum.

    Raises ValueError for unrecognised strings.
    """
    try:
        return Role(value.lower())
    except ValueError:
        valid = ", ".join(r.value for r in Role)
        raise ValueError(f"Unknown role '{value}'. Valid roles: {valid}")
