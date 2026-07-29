from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    PROPOSED = "proposed"
    READY = "ready"
    LEASED = "leased"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PROPOSED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset({TaskStatus.LEASED, TaskStatus.CANCELLED}),
    TaskStatus.LEASED: frozenset({TaskStatus.RUNNING, TaskStatus.READY, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.AWAITING_REVIEW, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.AWAITING_REVIEW: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.REJECTED, TaskStatus.FAILED}
    ),
    TaskStatus.REJECTED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.CANCELLED: frozenset(),
}


class InvalidTaskTransition(RuntimeError):
    pass


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    milestone_id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PROPOSED
    assigned_party: int = Field(default=1, ge=1, le=2)
    acceptance_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str | None = None
    version: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def transition(
        self,
        target: TaskStatus,
        *,
        expected_version: int,
        workspace_id: str | None = None,
    ) -> TaskRecord:
        if expected_version != self.version:
            raise InvalidTaskTransition(
                "optimistic concurrency conflict: "
                f"expected {expected_version}, actual {self.version}"
            )
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTaskTransition(f"invalid task transition: {self.status} -> {target}")
        return self.model_copy(
            update={
                "status": target,
                "workspace_id": workspace_id if workspace_id is not None else self.workspace_id,
                "version": self.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )


def transition_is_allowed(current: TaskStatus, target: TaskStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]
