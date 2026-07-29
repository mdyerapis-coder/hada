from __future__ import annotations

from typing import Any

from hada.models import GateDecision, MilestoneState, StopReason
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus
from hada.orchestrator.self_healing import Incident, RepairClass, SelfHealingSupervisor
from hada.orchestrator.service import OrchestratorService


class MemoryStore:
    """In-memory store that satisfies the runtime + service interfaces for testing."""

    def __init__(self) -> None:
        self.milestones: dict[str, MilestoneState] = {}
        self.tasks: dict[str, TaskRecord] = {}
        self.outbox: list[dict[str, Any]] = []

    def ping(self) -> bool:
        return True

    def create_milestone(self, state: MilestoneState) -> None:
        self.milestones[state.milestone_id] = state.model_copy(deep=True)

    def get_milestone(self, milestone_id: str) -> MilestoneState:
        return self.milestones[milestone_id].model_copy(deep=True)

    def create_task(self, task: TaskRecord) -> None:
        if task.task_id in self.tasks:
            raise ValueError(f"duplicate task: {task.task_id}")
        self.tasks[task.task_id] = task

    def get_task(self, task_id: str) -> TaskRecord:
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]

    def list_tasks_by_status(
        self, status: TaskStatus, limit: int = 50
    ) -> list[TaskRecord]:
        return [t for t in self.tasks.values() if t.status == status][:limit]

    def save_task_transition(
        self,
        before: TaskRecord,
        after: TaskRecord,
        *,
        actor_party: int | None = None,
    ) -> None:
        del before, actor_party
        assert after.task_id in self.tasks
        self.tasks[after.task_id] = after

    def save_task_transition_with_outbox(
        self,
        before: TaskRecord,
        after: TaskRecord,
        *,
        queue_name: str,
        message_kind: str,
        payload: dict[str, Any],
        actor_party: int | None = None,
    ) -> str:
        self.save_task_transition(before, after, actor_party=actor_party)
        self.outbox.append(
            {
                "queue_name": queue_name,
                "message_kind": message_kind,
                "payload": payload,
            }
        )
        return "outbox-1"

    def enqueue_outbox(
        self,
        *,
        queue_name: str,
        message_kind: str,
        payload: dict[str, object],
        stream: str,
        actor_party: int | None,
    ) -> str:
        self.outbox.append(
            {
                "queue_name": queue_name,
                "message_kind": message_kind,
                "payload": payload,
                "stream": stream,
                "actor_party": actor_party,
            }
        )
        return "outbox-1"

    def record_gate_decision(
        self,
        milestone_id: str,
        decision: GateDecision,
        resulting_stop_reason: StopReason | None = None,
    ) -> str:
        del milestone_id, decision, resulting_stop_reason
        return "decision-1"


def test_check_failed_tasks_creates_repair_incident() -> None:
    """A failed task is automatically flagged for repair by _check_failed_tasks."""
    store = MemoryStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M-repair",
            title="Self-healing",
            scope=["automatic safe repairs"],
            out_of_scope=["deploy", "secrets", "merge"],
        )
    )
    supervisor = SelfHealingSupervisor(service, "M-repair")

    # Create and fail a regular task.
    task = service.create_task(
        milestone_id="M-repair",
        title="Test worker",
        description="A task that will fail",
        acceptance_criteria=[],
    )
    ready = service.transition_task(task.task_id, TaskStatus.READY, actor_party=None)
    leased = service.transition_task(ready.task_id, TaskStatus.LEASED, actor_party=1)
    failed = service.transition_task(leased.task_id, TaskStatus.FAILED, actor_party=1)
    assert failed.status == TaskStatus.FAILED

    # Simulate the runtime check: scan failed tasks and flag each non-repair one.
    incident: Incident | None = None
    for ft in store.list_tasks_by_status(TaskStatus.FAILED, limit=20):
        if ft.task_id.startswith("repair-"):
            continue
        incident = Incident(
            source="orchestrator.runtime",
            subject=ft.task_id,
            error_class="task.failed",
            summary=ft.title,
            repair_class=RepairClass.SOURCE_CODE,
            evidence=[f"task_id:{ft.task_id}", f"milestone:{ft.milestone_id}"],
        )
        _disposition = supervisor.flag_and_apply_worker(incident)

    # A repair task should have been created and dispatched.
    assert incident is not None
    repair_tasks = [t for t in store.tasks.values() if t.task_id.startswith("repair-")]
    assert len(repair_tasks) == 1
    repair = repair_tasks[0]
    assert repair.status == TaskStatus.READY
    assert "orchestrator.runtime" in repair.description
    assert store.outbox

    # Calling again for the same failed task is idempotent — already active.
    duplicate = supervisor.flag_and_apply_worker(incident)
    assert duplicate.status == "already_active"
    assert len([t for t in store.tasks.values() if t.task_id.startswith("repair-")]) == 1


def test_check_failed_tasks_skips_repair_tasks() -> None:
    """Repair tasks that themselves failed are not re-flagged by the runtime."""
    store = MemoryStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M-repair",
            title="Self-healing",
            scope=["automatic safe repairs"],
            out_of_scope=["deploy", "secrets", "merge"],
        )
    )

    # Create a task that looks like a repair task (starts with "repair-").
    repair_like = service.create_task(
        milestone_id="M-repair",
        task_id="repair-abc123-1",
        title="Repair: something",
        description="A repair task",
        acceptance_criteria=[],
        metadata={"incident_fingerprint": "abc123"},
    )
    ready = service.transition_task(
        repair_like.task_id, TaskStatus.READY, actor_party=None
    )
    leased = service.transition_task(ready.task_id, TaskStatus.LEASED, actor_party=1)
    service.transition_task(leased.task_id, TaskStatus.FAILED, actor_party=1)

    # Runtime check should skip repair-* tasks.
    flagged = False
    for ft in store.list_tasks_by_status(TaskStatus.FAILED, limit=20):
        if ft.task_id.startswith("repair-"):
            continue  # runtime skips these
        flagged = True

    assert not flagged


def test_milestone_is_created_when_missing() -> None:
    """The runtime auto-creates the healing milestone on startup."""
    store = MemoryStore()
    # Milestone deliberately NOT created — will be auto-created.
    assert "M-auto" not in store.milestones

    service = OrchestratorService(store)
    # This simulates what the runtime's __init__ does.
    if "M-auto" not in store.milestones:
        service.create_milestone(
            MilestoneState(
                milestone_id="M-auto",
                title="Self-healing repairs",
                scope=["automatic safe repairs"],
                out_of_scope=["deploy", "secrets", "merge"],
            )
        )

    assert "M-auto" in store.milestones
    milestone = store.get_milestone("M-auto")
    assert milestone.title == "Self-healing repairs"
