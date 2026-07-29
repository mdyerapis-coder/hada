"""Tests for Android Stage 1 — versioned API contracts, auth seam, adult/child roles.

TDD sequence (RED → GREEN → REFACTOR):
1. Tests written to cover every requirement from the contract docs.
2. Initially run against unimplemented modules to confirm failures (RED).
3. Implementation is written until all tests pass (GREEN).
4. Refactor if needed while keeping tests green.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

# ── Module-level imports (will fail in RED phase) ────────────────────

from android.contracts import (
    CURRENT_API_VERSION,
    MIN_API_VERSION,
    SUPPORTED_VERSIONS,
    ApiVersionInfo,
    HouseholdStatus,
    Member,
    MemberListData,
    MemberListResponse,
    Notification,
    NotificationListData,
    NotificationListResponse,
    ScheduleEntry,
    ScheduleListData,
    ScheduleListResponse,
    Task,
    TaskListData,
    TaskListResponse,
    VersionedError,
    VersionedResponse,
    error_response,
    is_version_compatible,
    negotiate_version,
    parse_version,
)
from android.auth import (
    DEFAULT_TTL,
    HmacTokenSeam,
    AuthResult,
    default_ttl_for_role,
)
from android.roles import (
    ADULT_PERMISSIONS,
    CHILD_PERMISSIONS,
    Permission,
    Role,
    all_permissions,
    authorize,
    get_permissions,
    has_permission,
    role_from_string,
)


# ═══════════════════════════════════════════════════════════════════════
# Part 1: Versioned API Contract Validation
# ═══════════════════════════════════════════════════════════════════════


class TestVersionParsing:
    """parse_version must correctly parse and reject version strings."""

    def test_parse_valid_semver(self) -> None:
        v = parse_version("1.2.3")
        assert v == (1, 2, 3)

    def test_parse_major_minor_patch(self) -> None:
        v = parse_version("0.0.0")
        assert v == (0, 0, 0)

    def test_parse_large_numbers(self) -> None:
        v = parse_version("999.888.777")
        assert v == (999, 888, 777)

    def test_parse_rejects_missing_patch(self) -> None:
        with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
            parse_version("1.0")

    def test_parse_rejects_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
            parse_version("1.a.0")

    def test_parse_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
            parse_version("")

    def test_parse_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            parse_version("not-a-version")


class TestVersionCompatibility:
    """is_version_compatible correctly checks client vs server versions."""

    def test_exact_match(self) -> None:
        assert is_version_compatible("1.0.0") is True

    def test_minor_ahead_compatible(self) -> None:
        assert is_version_compatible("1.1.0", supported=["1.0.0", "1.1.0"]) is True

    def test_below_min_returns_false(self) -> None:
        assert is_version_compatible("0.9.0", min_version="1.0.0") is False

    def test_major_mismatch_returns_false(self) -> None:
        assert is_version_compatible("2.0.0", supported=["1.0.0"]) is False

    def test_invalid_client_version_returns_false(self) -> None:
        assert is_version_compatible("bogus") is False

    def test_compatible_with_multiple_supported(self) -> None:
        assert (
            is_version_compatible("1.5.0", supported=["1.0.0", "1.5.0", "2.0.0"])
            is True
        )

    def test_exactly_min_is_compatible(self) -> None:
        assert is_version_compatible("1.0.0", min_version="1.0.0") is True


class TestVersionNegotiation:
    """negotiate_version selects the correct server version."""

    def test_no_client_version_returns_latest(self) -> None:
        assert negotiate_version(None) == "1.0.0"

    def test_compatible_client_version_accepted(self) -> None:
        assert negotiate_version("1.0.0") == "1.0.0"

    def test_incompatible_client_version_raises(self) -> None:
        with pytest.raises(ValueError, match="not compatible"):
            negotiate_version("2.0.0")

    def test_too_old_client_version_raises(self) -> None:
        with pytest.raises(ValueError, match="not compatible"):
            negotiate_version("0.1.0")

    def test_client_version_with_newer_minor_accepted(self) -> None:
        supported = ["1.0.0", "1.1.0"]
        result = negotiate_version("1.1.0", supported=supported)
        assert result == "1.1.0"


class TestVersionConstants:
    """The module-level version constants are self-consistent."""

    def test_current_is_supported(self) -> None:
        assert CURRENT_API_VERSION in SUPPORTED_VERSIONS

    def test_current_is_not_below_min(self) -> None:
        c = parse_version(CURRENT_API_VERSION)
        m = parse_version(MIN_API_VERSION)
        assert c >= m

    def test_supported_versions_are_valid_semver(self) -> None:
        for v in SUPPORTED_VERSIONS:
            parts = parse_version(v)
            assert len(parts) == 3


class TestResponseEnvelope:
    """VersionedResponse wraps data/error correctly."""

    def test_success_response_has_no_error(self) -> None:
        resp = VersionedResponse(data={"ok": True})
        assert resp.api_version == CURRENT_API_VERSION
        assert resp.data == {"ok": True}
        assert resp.error is None

    def test_error_response_has_no_data(self) -> None:
        resp = error_response("NOT_FOUND", "Task not found")
        assert resp.data is None
        assert resp.error is not None
        assert resp.error.code == "NOT_FOUND"
        assert resp.error.message == "Task not found"

    def test_error_details_are_optional(self) -> None:
        resp = error_response("BAD_REQUEST", "bad", details={"field": "name"})
        assert resp.error is not None
        assert resp.error.details == {"field": "name"}

    def test_custom_api_version_on_error(self) -> None:
        resp = error_response("ERR", "msg", api_version="1.1.0")
        assert resp.api_version == "1.1.0"


class TestApiVersionInfo:
    """GET /api/v1/version response model."""

    def test_defaults_match_module_constants(self) -> None:
        info = ApiVersionInfo()
        assert info.api_version == CURRENT_API_VERSION
        assert info.min_version == MIN_API_VERSION
        assert info.server_name == "hada-hermes-ctl"

    def test_supported_versions_includes_current(self) -> None:
        info = ApiVersionInfo()
        assert CURRENT_API_VERSION in info.supported_versions

    def test_frozen_dataclass(self) -> None:
        info = ApiVersionInfo()
        with pytest.raises(AttributeError):
            info.api_version = "2.0.0"  # type: ignore[misc]


class TestHouseholdStatus:
    """HouseholdStatus model."""

    def test_all_fields_present(self) -> None:
        now = datetime.now(timezone.utc)
        status = HouseholdStatus(
            household_name="Test Home",
            member_count=4,
            active_tasks=3,
            overdue_tasks=1,
            unread_notifications=2,
            updated_at=now,
        )
        assert status.household_name == "Test Home"
        assert status.member_count == 4
        assert status.active_tasks == 3
        assert status.overdue_tasks == 1
        assert status.unread_notifications == 2
        assert status.updated_at == now


class TestTaskModels:
    """Task, TaskListData, TaskListResponse models."""

    def test_task_minimal(self) -> None:
        t = Task(id="t-1", title="Do dishes", status="pending")
        assert t.priority == "medium"
        assert t.tags == ()

    def test_task_full(self) -> None:
        due = datetime(2026, 7, 31, 18, 0, 0, tzinfo=timezone.utc)
        t = Task(
            id="t-2",
            title="Take out trash",
            status="in_progress",
            assigned_to="member-01",
            created_by="member-02",
            due_date=due,
            priority="high",
            tags=("chore", "kitchen"),
        )
        assert t.assigned_to == "member-01"
        assert t.due_date == due
        assert t.tags == ("chore", "kitchen")

    def test_task_list_data(self) -> None:
        tasks = (
            Task(id="t-1", title="A", status="pending"),
            Task(id="t-2", title="B", status="completed"),
        )
        data = TaskListData(items=tasks, total=2, limit=50, offset=0)
        assert data.total == 2
        assert len(data.items) == 2

    def test_task_list_response_envelope(self) -> None:
        tasks = (Task(id="t-1", title="A", status="pending"),)
        data = TaskListData(items=tasks, total=1)
        resp = TaskListResponse(data=data)
        assert resp.api_version == CURRENT_API_VERSION
        assert resp.data is not None
        assert resp.data.total == 1
        assert resp.error is None


class TestMemberModels:
    """Member models."""

    def test_member_minimal(self) -> None:
        m = Member(id="m-1", name="Alice", role="adult")
        assert m.is_online is False
        assert m.avatar_url is None

    def test_member_full(self) -> None:
        m = Member(id="m-2", name="Bob", role="child", avatar_url="https://av.at/a", is_online=True)
        assert m.is_online is True

    def test_member_list_response(self) -> None:
        members = (Member(id="m-1", name="A", role="adult"),)
        data = MemberListData(items=members, total=1)
        resp = MemberListResponse(data=data)
        assert resp.data is not None
        assert resp.data.total == 1


class TestScheduleModels:
    """ScheduleEntry models."""

    def test_schedule_minimal(self) -> None:
        start = datetime(2026, 7, 31, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 31, 15, 0, 0, tzinfo=timezone.utc)
        s = ScheduleEntry(id="s-1", title="Appt", start_time=start, end_time=end)
        assert s.recurrence is None
        assert s.location is None

    def test_schedule_list_response(self) -> None:
        start = datetime(2026, 7, 31, 14, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 31, 15, 0, 0, tzinfo=timezone.utc)
        items = (ScheduleEntry(id="s-1", title="A", start_time=start, end_time=end),)
        data = ScheduleListData(items=items, total=1)
        resp = ScheduleListResponse(data=data)
        assert resp.data is not None
        assert resp.data.total == 1


class TestNotificationModels:
    """Notification models."""

    def test_notification_minimal(self) -> None:
        n = Notification(id="n-1", type="reminder", title="Hey", body="Body")
        assert n.is_read is False

    def test_notification_list_response(self) -> None:
        items = (Notification(id="n-1", type="alert", title="X", body="Y"),)
        data = NotificationListData(items=items, total=1, unread_count=1)
        resp = NotificationListResponse(data=data)
        assert resp.data is not None
        assert resp.data.unread_count == 1


# ═══════════════════════════════════════════════════════════════════════
# Part 2: Auth Seam (Token Creation, Validation, Expiry)
# ═══════════════════════════════════════════════════════════════════════


class TestHmacTokenSeamInit:
    """HmacTokenSeam construction and secret resolution."""

    def test_create_with_explicit_secret(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        assert seam is not None

    def test_create_secret_too_short_ok(self) -> None:
        # The minimum length is advisory, not enforced for flexibility
        seam = HmacTokenSeam(secret="short")
        assert seam is not None


class TestHmacTokenSeamCreateAndValidate:
    """Token creation and round-trip validation."""

    def test_create_token_returns_string(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult")
        assert isinstance(token, str)
        assert "." in token

    def test_validate_own_token_succeeds(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult")
        result = seam.validate(token)
        assert result.success is True
        assert result.user_id == "member-01"
        assert result.role == "adult"

    def test_validate_returns_expires_at(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult", ttl_seconds=3600)
        result = seam.validate(token)
        assert result.success is True
        assert result.expires_at is not None
        assert result.expires_at.tzinfo is not None

    def test_token_with_child_role(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-02", "child")
        result = seam.validate(token)
        assert result.success is True
        assert result.role == "child"

    def test_different_secrets_produce_different_tokens(self) -> None:
        seam1 = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        seam2 = HmacTokenSeam(secret="another-different-32-char-secret-here!")
        token1 = seam1.create_token("m-1", "adult")
        token2 = seam2.create_token("m-1", "adult")
        assert token1 != token2


class TestHmacTokenExpiry:
    """Token expiry is enforced."""

    def test_expired_token_is_rejected(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        # Negative TTL: effectively expired on creation
        token = seam.create_token("member-01", "adult", ttl_seconds=-1)
        result = seam.validate(token)
        assert result.success is False
        assert result.reason == "token_expired"

    def test_zero_ttl_token_not_future(self) -> None:
        """A 0-TTL token has iat == exp; validate it cannot expire in the past."""
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult", ttl_seconds=0)
        result = seam.validate(token)
        # iat == exp means the token was valid only at creation instant.
        # In the rare case validation runs in the same clock-second, it may
        # still appear valid — but it should never be valid *after* that second.
        # At minimum, expires_at must equal iat, not be in the future.
        import time
        now = int(time.time())
        if result.success:
            # If we happen to land in the same second, the token is technically
            # still valid — but it expires immediately after. Check sanity.
            assert result.expires_at is not None
            assert int(result.expires_at.timestamp()) <= now + 1
        else:
            assert result.reason == "token_expired"

    def test_valid_token_not_yet_expired(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult", ttl_seconds=3600)
        result = seam.validate(token)
        assert result.success is True


class TestHmacTokenValidationErrors:
    """Invalid tokens are rejected with appropriate reasons."""

    def test_malformed_token_no_dot(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        result = seam.validate("not-a-valid-token")
        assert result.success is False
        assert result.reason == "malformed_token"

    def test_malformed_token_three_parts(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        result = seam.validate("part1.part2.part3")
        assert result.success is False
        assert result.reason == "malformed_token"

    def test_tampered_token_rejected(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult")
        tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
        result = seam.validate(tampered)
        assert result.success is False
        assert result.reason == "invalid_signature"

    def test_empty_token(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        result = seam.validate("")
        assert result.success is False
        assert result.reason == "malformed_token"


class TestDefaultTTL:
    """Default TTL values match the documented contract."""

    def test_adult_default_ttl(self) -> None:
        assert DEFAULT_TTL["adult"] == 86400  # 24 hours

    def test_child_default_ttl(self) -> None:
        assert DEFAULT_TTL["child"] == 14400  # 4 hours

    def test_default_ttl_for_role_helper(self) -> None:
        assert default_ttl_for_role("adult") == 86400
        assert default_ttl_for_role("child") == 14400

    def test_default_ttl_for_unknown_role(self) -> None:
        assert default_ttl_for_role("unknown") == 3600


class TestAuthResultDataclass:
    """AuthResult dataclass behaviour."""

    def test_success_result(self) -> None:
        r = AuthResult(success=True, user_id="u-1", role="adult")
        assert r.success is True
        assert r.reason is None

    def test_failure_result(self) -> None:
        r = AuthResult(success=False, reason="bad_token")
        assert r.user_id is None
        assert r.role is None

    def test_frozen(self) -> None:
        r = AuthResult(success=True)
        with pytest.raises(AttributeError):
            r.success = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════
# Part 3: Role Hierarchy (Adult, Child, Roles/Permissions)
# ═══════════════════════════════════════════════════════════════════════


class TestRoleEnum:
    """Role enum values and string representation."""

    def test_adult_value(self) -> None:
        assert Role.ADULT.value == "adult"

    def test_child_value(self) -> None:
        assert Role.CHILD.value == "child"

    def test_str_representation(self) -> None:
        assert str(Role.ADULT) == "adult"
        assert str(Role.CHILD) == "child"

    def test_role_from_string_valid(self) -> None:
        assert role_from_string("adult") == Role.ADULT
        assert role_from_string("child") == Role.CHILD

    def test_role_from_string_case_insensitive(self) -> None:
        assert role_from_string("ADULT") == Role.ADULT
        assert role_from_string("Child") == Role.CHILD

    def test_role_from_string_invalid(self) -> None:
        with pytest.raises(ValueError, match="Unknown role"):
            role_from_string("admin")


class TestPermissionEnum:
    """Permission enum values cover all documented permissions."""

    def test_household_read(self) -> None:
        assert Permission.HOUSEHOLD_READ.value == "household:read"

    def test_tasks_permissions(self) -> None:
        assert Permission.TASKS_READ_ALL.value == "tasks:read_all"
        assert Permission.TASKS_READ_OWN.value == "tasks:read_own"

    def test_members_permissions(self) -> None:
        assert Permission.MEMBERS_READ_ALL.value == "members:read_all"
        assert Permission.MEMBERS_READ_BASIC.value == "members:read_basic"
        assert Permission.MEMBER_READ_OWN.value == "member:read_own"

    def test_schedules_permissions(self) -> None:
        assert Permission.SCHEDULES_READ_ALL.value == "schedules:read_all"
        assert Permission.SCHEDULES_READ_FAMILY.value == "schedules:read_family"

    def test_notifications_permissions(self) -> None:
        assert Permission.NOTIFICATIONS_READ_OWN.value == "notifications:read_own"
        assert Permission.NOTIFICATIONS_READ_ALL.value == "notifications:read_all"

    def test_management_permissions(self) -> None:
        assert Permission.SETTINGS_MANAGE.value == "settings:manage"
        assert Permission.MEMBERS_MANAGE.value == "members:manage"
        assert Permission.AUDIT_READ.value == "audit:read"


class TestRolePermissionSets:
    """ADULT_PERMISSIONS and CHILD_PERMISSIONS contain the correct items."""

    def test_adult_has_household_read(self) -> None:
        assert Permission.HOUSEHOLD_READ in ADULT_PERMISSIONS

    def test_adult_has_all_tasks_read(self) -> None:
        assert Permission.TASKS_READ_ALL in ADULT_PERMISSIONS
        assert Permission.TASKS_READ_OWN in ADULT_PERMISSIONS

    def test_adult_has_all_members_read(self) -> None:
        assert Permission.MEMBERS_READ_ALL in ADULT_PERMISSIONS
        assert Permission.MEMBERS_READ_BASIC in ADULT_PERMISSIONS
        assert Permission.MEMBER_READ_OWN in ADULT_PERMISSIONS

    def test_adult_has_all_schedules(self) -> None:
        assert Permission.SCHEDULES_READ_ALL in ADULT_PERMISSIONS
        assert Permission.SCHEDULES_READ_FAMILY in ADULT_PERMISSIONS

    def test_adult_has_all_notifications_and_management(self) -> None:
        assert Permission.NOTIFICATIONS_READ_OWN in ADULT_PERMISSIONS
        assert Permission.NOTIFICATIONS_READ_ALL in ADULT_PERMISSIONS
        assert Permission.SETTINGS_MANAGE in ADULT_PERMISSIONS
        assert Permission.MEMBERS_MANAGE in ADULT_PERMISSIONS
        assert Permission.AUDIT_READ in ADULT_PERMISSIONS

    def test_child_has_household_read(self) -> None:
        assert Permission.HOUSEHOLD_READ in CHILD_PERMISSIONS

    def test_child_has_own_tasks_only(self) -> None:
        assert Permission.TASKS_READ_OWN in CHILD_PERMISSIONS
        assert Permission.TASKS_READ_ALL not in CHILD_PERMISSIONS

    def test_child_has_basic_members_only(self) -> None:
        assert Permission.MEMBERS_READ_BASIC in CHILD_PERMISSIONS
        assert Permission.MEMBER_READ_OWN in CHILD_PERMISSIONS
        assert Permission.MEMBERS_READ_ALL not in CHILD_PERMISSIONS

    def test_child_has_family_schedules(self) -> None:
        assert Permission.SCHEDULES_READ_FAMILY in CHILD_PERMISSIONS
        assert Permission.SCHEDULES_READ_ALL not in CHILD_PERMISSIONS

    def test_child_has_own_notifications_only(self) -> None:
        assert Permission.NOTIFICATIONS_READ_OWN in CHILD_PERMISSIONS
        assert Permission.NOTIFICATIONS_READ_ALL not in CHILD_PERMISSIONS

    def test_child_lacks_management_permissions(self) -> None:
        assert Permission.SETTINGS_MANAGE not in CHILD_PERMISSIONS
        assert Permission.MEMBERS_MANAGE not in CHILD_PERMISSIONS
        assert Permission.AUDIT_READ not in CHILD_PERMISSIONS

    def test_adult_count(self) -> None:
        assert len(ADULT_PERMISSIONS) == 13

    def test_child_count(self) -> None:
        assert len(CHILD_PERMISSIONS) == 6


class TestGetPermissions:
    """get_permissions returns the correct set per role."""

    def test_get_adult_permissions(self) -> None:
        perms = get_permissions(Role.ADULT)
        assert perms == ADULT_PERMISSIONS

    def test_get_child_permissions(self) -> None:
        perms = get_permissions(Role.CHILD)
        assert perms == CHILD_PERMISSIONS

    def test_get_permissions_unknown_role(self) -> None:
        with pytest.raises(KeyError):
            get_permissions("admin")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
# Part 4: Authorization Rules
# ═══════════════════════════════════════════════════════════════════════


class TestAuthorizeFunction:
    """authorize (has_permission) correctly gates actions per role."""

    def test_adult_can_read_household(self) -> None:
        assert authorize(Role.ADULT, Permission.HOUSEHOLD_READ) is True

    def test_child_can_read_household(self) -> None:
        assert authorize(Role.CHILD, Permission.HOUSEHOLD_READ) is True

    def test_adult_can_read_all_tasks(self) -> None:
        assert authorize(Role.ADULT, Permission.TASKS_READ_ALL) is True

    def test_child_cannot_read_all_tasks(self) -> None:
        assert authorize(Role.CHILD, Permission.TASKS_READ_ALL) is False

    def test_child_can_read_own_tasks(self) -> None:
        assert authorize(Role.CHILD, Permission.TASKS_READ_OWN) is True

    def test_adult_can_manage_settings(self) -> None:
        assert authorize(Role.ADULT, Permission.SETTINGS_MANAGE) is True

    def test_child_cannot_manage_settings(self) -> None:
        assert authorize(Role.CHILD, Permission.SETTINGS_MANAGE) is False

    def test_adult_can_manage_members(self) -> None:
        assert authorize(Role.ADULT, Permission.MEMBERS_MANAGE) is True

    def test_child_cannot_manage_members(self) -> None:
        assert authorize(Role.CHILD, Permission.MEMBERS_MANAGE) is False

    def test_adult_can_read_audit(self) -> None:
        assert authorize(Role.ADULT, Permission.AUDIT_READ) is True

    def test_child_cannot_read_audit(self) -> None:
        assert authorize(Role.CHILD, Permission.AUDIT_READ) is False

    def test_adult_can_read_own_member(self) -> None:
        assert authorize(Role.ADULT, Permission.MEMBER_READ_OWN) is True

    def test_child_can_read_own_member(self) -> None:
        assert authorize(Role.CHILD, Permission.MEMBER_READ_OWN) is True

    def test_adult_can_read_all_notifications(self) -> None:
        assert authorize(Role.ADULT, Permission.NOTIFICATIONS_READ_ALL) is True

    def test_child_cannot_read_all_notifications(self) -> None:
        assert authorize(Role.CHILD, Permission.NOTIFICATIONS_READ_ALL) is False

    def test_child_can_read_own_notifications(self) -> None:
        assert authorize(Role.CHILD, Permission.NOTIFICATIONS_READ_OWN) is True

    def test_adult_can_read_schedules_all(self) -> None:
        assert authorize(Role.ADULT, Permission.SCHEDULES_READ_ALL) is True

    def test_child_can_read_family_schedules(self) -> None:
        assert authorize(Role.CHILD, Permission.SCHEDULES_READ_FAMILY) is True

    def test_child_cannot_read_all_schedules(self) -> None:
        assert authorize(Role.CHILD, Permission.SCHEDULES_READ_ALL) is False

    def test_unknown_role_returns_false(self) -> None:
        """authorize with an unrecognised role returns False (fail-closed)."""
        # Use a valid permission but a non-Role value to test fail-closed
        from android.roles import has_permission as hp
        # A role string that doesn't match any Role enum
        assert hp("nonexistent", Permission.HOUSEHOLD_READ) is False  # type: ignore[arg-type]


class TestHasPermissionAlias:
    """has_permission is the canonical function; authorize is an alias."""

    def test_has_permission_and_authorize_are_same(self) -> None:
        assert has_permission is authorize


class TestAllPermissions:
    """all_permissions returns every known permission."""

    def test_all_permissions_contains_all_adult_permissions(self) -> None:
        all_p = all_permissions()
        for p in ADULT_PERMISSIONS:
            assert p in all_p

    def test_all_permissions_contains_all_child_permissions(self) -> None:
        all_p = all_permissions()
        for p in CHILD_PERMISSIONS:
            assert p in all_p

    def test_all_permissions_count(self) -> None:
        assert len(all_permissions()) == len(Permission)


# ═══════════════════════════════════════════════════════════════════════
# Part 5: Integration — Auth + Roles end-to-end
# ═══════════════════════════════════════════════════════════════════════


class TestAuthWithRolesIntegration:
    """Auth seam + roles module work together end-to-end."""

    def test_create_token_and_check_role_permission(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult")
        result = seam.validate(token)

        assert result.success is True
        role = Role(result.role)  # type: ignore[arg-type]
        assert authorize(role, Permission.SETTINGS_MANAGE) is True
        assert authorize(role, Permission.TASKS_READ_ALL) is True

    def test_child_token_restricted(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-02", "child")
        result = seam.validate(token)

        assert result.success is True
        role = Role(result.role)  # type: ignore[arg-type]
        assert authorize(role, Permission.TASKS_READ_OWN) is True
        assert authorize(role, Permission.TASKS_READ_ALL) is False
        assert authorize(role, Permission.SETTINGS_MANAGE) is False

    def test_expired_token_denies_everything(self) -> None:
        seam = HmacTokenSeam(secret="this-is-a-32-char-dev-secret-for-test!")
        token = seam.create_token("member-01", "adult", ttl_seconds=-1)
        result = seam.validate(token)
        assert result.success is False
        # No need to check authorization — auth failed at token level
