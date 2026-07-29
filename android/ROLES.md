# Adult/Child Role Definitions

> **Stage:** Phase 4 — Android Stage 1
> **Status:** Draft
> **Version:** 1.0.0

## 1. Role Model

The HADA Android app supports two built-in roles: **Adult** and **Child**.
Roles determine what data a user can read and which actions they can
perform.

```
                  ┌──────────────┐
                  │    Adult     │  (administrative user)
                  │  (full read) │
                  └──────┬───────┘
                         │
                         │ (subset)
                         │
                  ┌──────▼───────┐
                  │    Child     │  (restricted read)
                  │ (limited RX) │
                  └──────────────┘
```

**Relationships:**
- Adults can read all household data.
- Children read only their own tasks, own notifications, and basic
  household info.
- Household settings and member management are adult-only.

## 2. Permission Catalog

Each permission is a string constant in `SCREAMING_SNAKE_CASE`.

| Permission                        | Code                        | Adult | Child | Description                              |
|-----------------------------------|-----------------------------|:-----:|:-----:|------------------------------------------|
| View household status & name      | `HOUSEHOLD_READ`            | ✅    | ✅    | Dashboard summary, household name        |
| View all tasks                    | `TASKS_READ_ALL`            | ✅    | ❌    | Every task in the household              |
| View own tasks                    | `TASKS_READ_OWN`            | ✅    | ✅    | Tasks where `assigned_to == current user`|
| View all members                  | `MEMBERS_READ_ALL`          | ✅    | ❌    | Full member details (contact, role)      |
| View basic member info            | `MEMBERS_READ_BASIC`        | ✅    | ✅    | Name and avatar only                     |
| View own member profile (full)    | `MEMBER_READ_OWN`           | ✅    | ✅    | Full own profile                         |
| View all schedules                | `SCHEDULES_READ_ALL`        | ✅    | ❌    | Every schedule entry                     |
| View family schedules             | `SCHEDULES_READ_FAMILY`     | ✅    | ✅    | Schedules visible to children            |
| View own notifications            | `NOTIFICATIONS_READ_OWN`    | ✅    | ✅    | Notifications addressed to current user  |
| View all notifications            | `NOTIFICATIONS_READ_ALL`    | ✅    | ❌    | Every notification in the household      |
| Manage household settings         | `SETTINGS_MANAGE`           | ✅    | ❌    | Update household name, preferences       |
| Manage members                    | `MEMBERS_MANAGE`            | ✅    | ❌    | Add/remove members, change roles         |
| View activity log                 | `AUDIT_READ`                | ✅    | ❌    | Audit trail of changes                   |

> **Note:** The `child` role **always implies** `TASKS_READ_OWN` even if
> `TASKS_READ_ALL` is denied. The authorization layer checks the most
> specific permission first.

## 3. Role → Permission Mapping

```python
# Adult inherits everything
ADULT_PERMISSIONS: set[Permission] = {
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
}

# Child gets a restricted subset
CHILD_PERMISSIONS: set[Permission] = {
    Permission.HOUSEHOLD_READ,
    Permission.TASKS_READ_OWN,
    Permission.MEMBERS_READ_BASIC,
    Permission.MEMBER_READ_OWN,
    Permission.SCHEDULES_READ_FAMILY,
    Permission.NOTIFICATIONS_READ_OWN,
}
```

## 4. Authorization Rules

### Rule 1 — Exact Match
If the action's permission is directly in the role's permission set,
authorize.

### Rule 2 — Adult Override
Adults always have `Permission.TASKS_READ_OWN` implicitly even though
they also have `Permission.TASKS_READ_ALL`. The system checks the more
specific permission first.

### Rule 3 — Child Scoping
When a child requests a list endpoint (e.g. `GET /api/v1/tasks`), the
**data layer** must filter results to only include items where
`assigned_to == current_user`. The auth layer only grants/denies access.

### Rule 4 — Fallback Deny
If no rule matches, deny. There is no implicit inheritance from a
"higher" role — Adult and Child have independent permission sets.

## 5. Usage in Code

### Server-side guard (FastAPI-style)

```python
from android.roles import authorize, Permission, Role

def get_current_user(auth=Depends(authenticate)) -> AuthResult:
    if not auth.success:
        raise HTTPException(status_code=401, detail=auth.reason)
    return auth

def require(permission: Permission):
    def dep(auth=Depends(get_current_user)):
        if not authorize(Role(auth.role), permission):
            raise HTTPException(status_code=403, detail="forbidden")
        return auth
    return dep

@app.get("/api/v1/household/status")
async def household_status(
    auth=Depends(require(Permission.HOUSEHOLD_READ)),
):
    ...
```

### Client-side hint

```python
# The Android app stores the decoded role from the token.
# UI elements can be hidden/shown based on role without
# a server round-trip:
if user_role == Role.ADULT:
    show_settings_button()
```

## 6. Future Extensions

- **Custom roles** with user-defined permission sets.
- **Family View toggle** for children: opt-in to see all family tasks.
- **Time-based restrictions** (child cannot access after 9 PM).
- **Feature flags** per household (some households may want children to
  have broader access).
