"""Hermes CTL — Family tasks (Phase 4: Home Hub Integration).

Manages household task management with family-oriented features
(add, complete, update, remove, scan/filter, snapshot delivery).

Follows the established module pattern:
  Layer 1 — Dataclass models (FamilyTask, FamilyTaskSnapshot)
  Layer 2 — scan_family_tasks() reads from MemoryStore with in-memory filters
  Layer 3 — add_task() / update_task() / complete_task() / remove_task()
  Layer 4 — deliver_family_tasks() persists snapshot to MemoryStore
  Layer 5 — CLI at hermes_ctl/cli/lifestyle_commands.py

Governance / safety:
- Pure data model + store operations (no network, no LLM at module level).
- All operations wrap store calls in try/except for graceful degradation.
- Every field has a safe default — no crashes on empty or missing stores.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Module-level counter for unique sortable task IDs
# ---------------------------------------------------------------------------

_task_seq: int = 0


def _next_task_id() -> str:
    """Generate a sortable family task ID using time + monotonic counter."""
    global _task_seq
    _task_seq += 1
    ms = int(time.time() * 1000)
    return f"fam_task:{ms}:{_task_seq}"


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass models
# ---------------------------------------------------------------------------


@dataclass
class FamilyTask:
    """A single household task tracked for a family member.

    All fields have safe defaults so consumers never crash on missing data.
    """

    id: str = ""
    """Unique identifier (auto-generated as 'fam_task:<ms>:<seq>')."""

    title: str = ""
    """Task title / short description."""

    description: str = ""
    """Optional longer description of the task."""

    assigned_to: str = ""
    """Family member assigned to this task (e.g. 'Mason', 'Courtney')."""

    category: str = "other"
    """Task category: chore, errand, appointment, reminder, other."""

    priority: int = 3
    """Priority 1–5 (1=lowest, 5=highest)."""

    due_date: int = 0
    """Optional due date as Unix timestamp (0 = no due date)."""

    recurrence: str = "none"
    """Recurrence pattern: daily, weekly, monthly, none."""

    completed: bool = False
    """Whether the task has been completed."""

    completed_at: float = 0.0
    """Unix timestamp when completed (0 = not completed)."""

    created_at: float = field(default_factory=time.time)
    """Unix timestamp when the task was created."""

    tags: list[str] = field(default_factory=list)
    """Arbitrary tags for grouping / filtering."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "assignedTo": self.assigned_to,
            "assigned_to": self.assigned_to,
            "category": self.category,
            "priority": self.priority,
            "dueDate": self.due_date,
            "due_date": self.due_date,
            "recurrence": self.recurrence,
            "completed": self.completed,
            "completedAt": self.completed_at,
            "completed_at": self.completed_at,
            "createdAt": self.created_at,
            "created_at": self.created_at,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FamilyTask":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            assigned_to=d.get("assignedTo", d.get("assigned_to", "")),
            category=d.get("category", "other"),
            priority=d.get("priority", 3),
            due_date=d.get("dueDate", d.get("due_date", 0)),
            recurrence=d.get("recurrence", "none"),
            completed=d.get("completed", False),
            completed_at=d.get("completedAt", d.get("completed_at", 0.0)),
            created_at=d.get("createdAt", d.get("created_at", time.time())),
            tags=d.get("tags", []),
        )


@dataclass
class FamilyTaskSnapshot:
    """Collection view of family tasks with computed summaries."""

    tasks: list[FamilyTask] = field(default_factory=list)
    total_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_assignee: dict[str, int] = field(default_factory=dict)
    overdue_count: int = 0
    due_today_count: int = 0
    completion_rate: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "totalCount": self.total_count,
            "total_count": self.total_count,
            "byCategory": dict(self.by_category),
            "by_category": dict(self.by_category),
            "byAssignee": dict(self.by_assignee),
            "by_assignee": dict(self.by_assignee),
            "overdueCount": self.overdue_count,
            "overdue_count": self.overdue_count,
            "dueTodayCount": self.due_today_count,
            "due_today_count": self.due_today_count,
            "completionRate": self.completion_rate,
            "completion_rate": self.completion_rate,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FamilyTaskSnapshot":
        return cls(
            tasks=[FamilyTask.from_dict(t) for t in d.get("tasks", [])],
            total_count=d.get("totalCount", d.get("total_count", 0)),
            by_category=dict(d.get("byCategory", d.get("by_category", {}))),
            by_assignee=dict(d.get("byAssignee", d.get("by_assignee", {}))),
            overdue_count=d.get("overdueCount", d.get("overdue_count", 0)),
            due_today_count=d.get("dueTodayCount", d.get("due_today_count", 0)),
            completion_rate=d.get("completionRate", d.get("completion_rate", 0.0)),
            timestamp=d.get("timestamp", ""),
        )


# ---------------------------------------------------------------------------
# Layer 2 — Scan / read
# ---------------------------------------------------------------------------


def scan_family_tasks(
    *,
    store: Any = None,
    category: str | None = None,
    assignee: str | None = None,
    is_completed: bool | None = None,
    overdue_only: bool = False,
    due_today_only: bool = False,
    tag: str | None = None,
) -> FamilyTaskSnapshot:
    """Read all family tasks from MemoryStore with optional in-memory filters.

    Args:
        store: A MemoryStore instance.
        category: Filter by category (chore, errand, appointment, reminder, other).
        assignee: Filter by assigned family member name.
        is_completed: Filter by completion state (True=completed, False=pending, None=all).
        overdue_only: Only return tasks past their due_date and not completed.
        due_today_only: Only return tasks whose due_date is today.
        tag: Filter by tag (exact match on any tag in the task's tag list).

    Returns:
        A populated ``FamilyTaskSnapshot`` with computed summaries.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    now = time.time()
    today_start = _today_start()

    if store is None:
        return FamilyTaskSnapshot(timestamp=ts)

    try:
        facts = list(store.search(tag="family_task"))
    except Exception:
        return FamilyTaskSnapshot(timestamp=ts)

    tasks: list[FamilyTask] = []
    by_category: dict[str, int] = {}
    by_assignee: dict[str, int] = {}
    overdue_count = 0
    due_today_count = 0

    for fact in facts:
        val = fact.value if hasattr(fact, "value") else {}
        task = FamilyTask.from_dict(val)
        if not task.id:
            continue

        # Apply filters
        if category is not None and task.category != category:
            continue
        if assignee is not None and task.assigned_to != assignee:
            continue
        if is_completed is not None and task.completed != is_completed:
            continue
        if overdue_only and not (task.due_date > 0 and not task.completed and task.due_date < now):
            continue
        if due_today_only and not (task.due_date >= today_start and task.due_date < today_start + 86400):
            continue
        if tag is not None and tag not in task.tags:
            continue

        tasks.append(task)
        cat = task.category or "other"
        by_category[cat] = by_category.get(cat, 0) + 1
        if task.assigned_to:
            by_assignee[task.assigned_to] = by_assignee.get(task.assigned_to, 0) + 1

        # Count overdue (past due, not completed)
        if task.due_date > 0 and not task.completed and task.due_date < now:
            overdue_count += 1

        # Count due today
        if task.due_date >= today_start and task.due_date < today_start + 86400:
            due_today_count += 1

    # Sort: incomplete first, then by priority descending, then by title
    tasks.sort(key=lambda t: (t.completed, -t.priority if not t.completed else 0, t.title or ""))

    total = len(tasks)
    completed_count = sum(1 for t in tasks if t.completed)
    completion_rate = round(completed_count / total, 4) if total > 0 else 0.0

    return FamilyTaskSnapshot(
        tasks=tasks,
        total_count=total,
        by_category=by_category,
        by_assignee=by_assignee,
        overdue_count=overdue_count,
        due_today_count=due_today_count,
        completion_rate=completion_rate,
        timestamp=ts,
    )


def _today_start() -> float:
    """Return the Unix timestamp for the start of today (00:00:00 UTC)."""
    now = time.gmtime()
    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0))


# ---------------------------------------------------------------------------
# Layer 3 — Write operations
# ---------------------------------------------------------------------------


def _task_fact_id(task_id: str) -> str:
    """Normalise a task id into a MemoryStore fact key."""
    if task_id.startswith("fam_task:"):
        return task_id
    return f"fam_task:{task_id}"


def add_task(
    store: Any,
    title: str,
    *,
    description: str = "",
    assigned_to: str = "",
    category: str = "other",
    priority: int = 3,
    due_date: int = 0,
    recurrence: str = "none",
    tags: list[str] | None = None,
) -> FamilyTask:
    """Add a new family task to MemoryStore.

    Args:
        store: A MemoryStore instance.
        title: Task title (required).
        description: Optional longer description.
        assigned_to: Family member assigned to this task.
        category: Task category (chore, errand, appointment, reminder, other).
        priority: Priority 1–5.
        due_date: Unix timestamp for due date (0 = none).
        recurrence: Recurrence pattern (daily, weekly, monthly, none).
        tags: Optional list of tags.

    Returns:
        The created ``FamilyTask``.

    Raises:
        ValueError: If title is empty.
    """
    if not title or not title.strip():
        raise ValueError("task title is required")

    task_id = _next_task_id()
    now = time.time()

    task = FamilyTask(
        id=task_id,
        title=title.strip(),
        description=description,
        assigned_to=assigned_to,
        category=category or "other",
        priority=max(1, min(5, priority)),
        due_date=due_date,
        recurrence=recurrence or "none",
        created_at=now,
        tags=tags or [],
    )

    try:
        store.remember(task_id, task.to_dict(), tags={"family_task", f"cat:{task.category}"})
    except Exception as exc:
        raise RuntimeError(f"failed to add family task: {exc}") from exc

    return task


def update_task(store: Any, task_id: str, **kwargs: Any) -> FamilyTask | None:
    """Update fields on an existing family task. Preserves created_at.

    Args:
        store: A MemoryStore instance.
        task_id: The task ID to update.
        **kwargs: Fields to update (title, description, assigned_to, category,
                  priority, due_date, recurrence, tags).

    Returns:
        The updated ``FamilyTask``, or None if not found.
    """
    fact_id = _task_fact_id(task_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        return None

    if not val:
        return None

    task = FamilyTask.from_dict(val)

    # Apply updates, preserving created_at
    if "title" in kwargs and kwargs["title"]:
        task.title = kwargs["title"].strip()
    if "description" in kwargs:
        task.description = kwargs.get("description", "")
    if "assigned_to" in kwargs:
        task.assigned_to = kwargs.get("assigned_to", "")
    if "category" in kwargs:
        task.category = kwargs.get("category", "other")
    if "priority" in kwargs:
        task.priority = max(1, min(5, int(kwargs["priority"])))
    if "due_date" in kwargs:
        task.due_date = int(kwargs.get("due_date", 0))
    if "recurrence" in kwargs:
        task.recurrence = kwargs.get("recurrence", "none")
    if "tags" in kwargs:
        task.tags = list(kwargs.get("tags", []))

    try:
        store.remember(fact_id, task.to_dict(), tags={"family_task", f"cat:{task.category}"})
    except Exception as exc:
        raise RuntimeError(f"failed to update family task: {exc}") from exc

    return task


def complete_task(store: Any, task_id: str) -> FamilyTask | None:
    """Mark a family task as completed.

    Args:
        store: A MemoryStore instance.
        task_id: The task ID to mark complete.

    Returns:
        The updated ``FamilyTask``, or None if not found.
    """
    fact_id = _task_fact_id(task_id)

    try:
        val = store.recall(fact_id)
    except Exception:
        return None

    if not val:
        return None

    task = FamilyTask.from_dict(val)
    task.completed = True
    task.completed_at = time.time()

    try:
        store.remember(fact_id, task.to_dict(), tags={"family_task", f"cat:{task.category}"})
    except Exception as exc:
        raise RuntimeError(f"failed to complete family task: {exc}") from exc

    return task


def remove_task(store: Any, task_id: str) -> bool:
    """Remove a family task from MemoryStore.

    Args:
        store: A MemoryStore instance.
        task_id: The task ID to remove.

    Returns:
        True if removed, False if not found.
    """
    fact_id = _task_fact_id(task_id)

    try:
        # Check existence first
        try:
            store.recall(fact_id)
        except Exception:
            return False
        store.forget(fact_id)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Layer 4 — Snapshot delivery
# ---------------------------------------------------------------------------


def deliver_family_tasks(store: Any, snapshot: FamilyTaskSnapshot) -> str:
    """Persist a family task snapshot to MemoryStore.

    Args:
        store: A MemoryStore instance.
        snapshot: The snapshot to persist.

    Returns:
        'memory' on success (no-store path returns 'memory' without crashing).
    """
    if store is not None:
        try:
            ts = snapshot.timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            store.remember(
                f"fam_snap:{ts}",
                snapshot.to_dict(),
                tags={"family_task_snapshot", "family_task"},
            )
        except Exception:
            pass  # non-fatal
    return "memory"
