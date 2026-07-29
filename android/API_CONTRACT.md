# Android API Contract — Versioned Read-Only Schema

> **Stage:** Phase 4 — Android Stage 1
> **Status:** Draft
> **Version:** 1.0.0

## 1. Overview

This document defines the versioned read-only API contract that the HADA
backend exposes for the Android client. All endpoints are server-rendered
(`hermes_ctl` module) and return JSON. The Android app never mutates state
through these endpoints — this is a read-only contract layer.

## 2. Base URL

```
https://<hada-host>/api/v1
```

All requests must include:

```
Authorization: Bearer <token>
Content-Type: application/json
Accept: application/json
```

## 3. Version Negotiation

### `GET /api/v1/version`

Returns the set of API versions the server supports and the preferred
default. The Android client **must** call this during startup and pick
the highest mutually-supported version.

**Response `200 OK`:**

```json
{
  "api_version": "1.0.0",
  "supported_versions": ["1.0.0"],
  "min_version": "1.0.0",
  "server_name": "hada-hermes-ctl"
}
```

**Version compatibility rule:** If the client's requested version is
below `min_version` the server responds `426 Upgrade Required`. If the
version is higher than any `supported_versions` entry, the server
responds `400 Bad Request` with a `supported_versions` hint.

---

## 4. Endpoints (Read-Only)

### 4.1 Household Status

#### `GET /api/v1/household/status`

Returns a lightweight status snapshot of the household.

**Scopes:** `household:read`
**Roles:** `adult`, `child`

**Response `200 OK`:**

```json
{
  "api_version": "1.0.0",
  "data": {
    "household_name": "Our Home",
    "member_count": 4,
    "active_tasks": 3,
    "overdue_tasks": 1,
    "unread_notifications": 2,
    "updated_at": "2026-07-30T09:00:00Z"
  }
}
```

---

### 4.2 Tasks

#### `GET /api/v1/tasks`

Lists household tasks, optionally filtered.

**Query parameters:**

| Param     | Type   | Required | Default | Description                           |
|-----------|--------|----------|---------|---------------------------------------|
| `status`  | string | no       | all     | `pending`, `in_progress`, `completed` |
| `assigned_to` | string | no   | all     | member ID or `me`                     |
| `limit`   | int    | no       | 50      | max results (1–200)                   |
| `offset`  | int    | no       | 0       | pagination offset                     |

**Scopes:** `tasks:read`
**Roles:** `adult` (all tasks), `child` (own tasks only unless `family_view` enabled)

**Response `200 OK`:**

```json
{
  "api_version": "1.0.0",
  "data": {
    "items": [
      {
        "id": "task-001",
        "title": "Take out recycling",
        "status": "pending",
        "assigned_to": "member-01",
        "created_by": "member-02",
        "due_date": "2026-07-31T18:00:00Z",
        "priority": "medium",
        "tags": ["chore", "kitchen"]
      }
    ],
    "total": 42,
    "limit": 50,
    "offset": 0
  }
}
```

#### `GET /api/v1/tasks/{task_id}`

**Scopes:** `tasks:read`
**Roles:** `adult`, `child` (own tasks only)

**Response `200 OK`:** Same item shape as above (singular `data` object).

**Response `404 Not Found`:**

```json
{
  "api_version": "1.0.0",
  "error": {
    "code": "NOT_FOUND",
    "message": "Task task-999 not found"
  }
}
```

---

### 4.3 Members

#### `GET /api/v1/members`

Lists household members.

**Scopes:** `members:read`
**Roles:** `adult` (full details), `child` (name + avatar only)

**Response `200 OK`:**

```json
{
  "api_version": "1.0.0",
  "data": {
    "items": [
      {
        "id": "member-01",
        "name": "Alice",
        "role": "adult",
        "avatar_url": "https://...",
        "is_online": true
      }
    ],
    "total": 4
  }
}
```

#### `GET /api/v1/members/{member_id}`

**Scopes:** `members:read`
**Roles:** `adult` (full detail), `child` (own profile only)

---

### 4.4 Schedules

#### `GET /api/v1/schedules`

Lists upcoming schedule entries.

**Query parameters:**

| Param  | Type   | Required | Default      | Description             |
|--------|--------|----------|--------------|-------------------------|
| `from` | string | no       | today        | ISO-8601 start date     |
| `to`   | string | no       | +7 days      | ISO-8601 end date       |
| `limit`| int    | no       | 50           | max results             |

**Scopes:** `schedules:read`
**Roles:** `adult`, `child`

**Response `200 OK`:**

```json
{
  "api_version": "1.0.0",
  "data": {
    "items": [
      {
        "id": "sched-001",
        "title": "Dentist appointment",
        "start_time": "2026-07-31T14:00:00Z",
        "end_time": "2026-07-31T15:00:00Z",
        "assigned_to": ["member-01"],
        "location": "123 Main St",
        "recurrence": null
      }
    ],
    "total": 12
  }
}
```

---

### 4.5 Notifications

#### `GET /api/v1/notifications`

Lists recent notifications for the authenticated user.

**Query parameters:**

| Param  | Type   | Required | Default | Description                        |
|--------|--------|----------|---------|------------------------------------|
| `limit`| int    | no       | 20      | max results                        |
| `unread_only` | bool | no  | false   | filter to unread only              |

**Scopes:** `notifications:read`
**Roles:** `adult`, `child` (own notifications only)

**Response `200 OK`:**

```json
{
  "api_version": "1.0.0",
  "data": {
    "items": [
      {
        "id": "notif-001",
        "type": "task_reminder",
        "title": "Task overdue: Take out recycling",
        "body": "This task was due yesterday.",
        "is_read": false,
        "created_at": "2026-07-30T08:00:00Z",
        "target_link": "/api/v1/tasks/task-001"
      }
    ],
    "total": 5,
    "unread_count": 2
  }
}
```

---

## 5. Error Responses

All error responses share this envelope:

```json
{
  "api_version": "1.0.0",
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {}
  }
}
```

### Standard error codes

| HTTP Code | Error Code             | Meaning                              |
|-----------|------------------------|--------------------------------------|
| 400       | `BAD_REQUEST`          | Malformed request or unsupported API version |
| 401       | `UNAUTHORIZED`         | Missing or invalid token             |
| 403       | `FORBIDDEN`            | Token valid but role lacks permission |
| 404       | `NOT_FOUND`            | Resource not found                   |
| 426       | `UPGRADE_REQUIRED`     | Client version too old               |
| 429       | `RATE_LIMITED`         | Too many requests                    |
| 500       | `INTERNAL_ERROR`       | Server error                         |

---

## 6. Auth Requirements

| Aspect            | Requirement                                         |
|-------------------|-----------------------------------------------------|
| **Scheme**        | Bearer token via `Authorization` header             |
| **Token type**    | HMAC-signed JWT-like token (see `AUTH_SEAM.md`)     |
| **Token claims**  | `sub` (user ID), `role`, `iat`, `exp`, `jti`        |
| **Token expiry**  | Adults: 24h / Children: 4h (configurable)           |
| **Rate limit**    | 60 req/min per token (adult), 20 req/min (child)    |
| **Audit**         | Every request is logged with `user_id`, `role`, endpoint |

---

## 7. Versioning Strategy

| Scheme               | Value                     |
|----------------------|---------------------------|
| Format               | `MAJOR.MINOR.PATCH`       |
| Breaking changes     | Increment MAJOR           |
| Backward-compatible  | Increment MINOR           |
| Bugfix / patch       | Increment PATCH           |
| Server advertises    | `supported_versions[]`    |
| Client request       | `Accept-Version` header or query param |

The server **always** returns the negotiated version in `api_version` on
every response so the client can detect drift.
