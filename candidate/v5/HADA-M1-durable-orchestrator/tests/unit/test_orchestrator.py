from typing import Any

import pytest

from hada.governance.engine import GovernanceViolation
from hada.models import GateDecision, GateName, GateStatus, MilestoneState, StopReason
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus
from hada.orchestrator.service import OrchestratorService


class MemoryStore:
    def __init__(self) -> None:
        self.milestones: dict[str, MilestoneState] = {}
        self.tasks: dict[str, TaskRecord] = {}
        self.outbox: list[dict[str, Any]] = []

    def create_milestone(self, state: MilestoneState) -> None:
        self.milestones[state.milestone_id] = state.model_copy(deep=True)

    def get_milestone(self, milestone_id: str) -> MilestoneState:
        return self.milestones[milestone_id].model_copy(deep=True)

    def create_task(self, task: TaskRecord) -> None:
        self.tasks[task.task_id] = task

    def get_task(self, task_id: str) -> TaskRecord:
        return self.tasks[task_id]

    def save_task_transition(
        self,
        before: TaskRecord,
        after: TaskRecord,
        *,
        actor_party: int | None = None,
    ) -> None:
        del before, actor_party
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
        return "outbox-atomic-1"

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
        state = self.milestones[milestone_id]
        state.gates[decision.gate] = decision
        if resulting_stop_reason is not None:
            state.stop_reason = resulting_stop_reason
        return "decision-1"


def test_task_scheduling_and_review_separation() -> None:
    store = MemoryStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M1",
            title="Durable orchestrator",
            scope=["state"],
            out_of_scope=["inference"],
        )
    )
    task = service.create_task(
        milestone_id="M1",
        title="Schema",
        description="Implement schema",
        acceptance_criteria=["migration applies"],
    )
    ready = service.transition_task(task.task_id, TaskStatus.READY, actor_party=None)
    assert ready.status == TaskStatus.READY
    assert service.schedule_task(task.task_id) == "outbox-1"
    leased = service.transition_task(task.task_id, TaskStatus.LEASED, actor_party=1)
    running = service.transition_task(leased.task_id, TaskStatus.RUNNING, actor_party=1)
    review = service.transition_task(running.task_id, TaskStatus.AWAITING_REVIEW, actor_party=1)
    with pytest.raises(GovernanceViolation):
        service.transition_task(review.task_id, TaskStatus.COMPLETED, actor_party=1)
    complete = service.transition_task(review.task_id, TaskStatus.COMPLETED, actor_party=2)
    assert complete.status == TaskStatus.COMPLETED


def test_external_party_cannot_mutate_tasks() -> None:
    store = MemoryStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M1",
            title="Durable orchestrator",
            scope=["state"],
            out_of_scope=["inference"],
        )
    )
    task = service.create_task(
        milestone_id="M1",
        title="Schema",
        description="Implement schema",
        acceptance_criteria=[],
    )
    with pytest.raises(GovernanceViolation):
        service.transition_task(task.task_id, TaskStatus.READY, actor_party=3)


def test_gate_result_is_persisted() -> None:
    store = MemoryStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M1",
            title="Durable orchestrator",
            scope=["state"],
            out_of_scope=["inference"],
        )
    )
    result = service.record_gate_decision(
        "M1",
        GateDecision(
            gate=GateName.ARCHITECTURE,
            status=GateStatus.APPROVED,
            reviewer_party=2,
            subject_party=1,
            evidence=["sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
        ),
    )
    assert result.may_continue is True
    assert store.milestones["M1"].gates[GateName.ARCHITECTURE] is not None


def test_stopped_milestone_blocks_task_execution() -> None:
    store = MemoryStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M1-stop",
            title="Stopped milestone",
            scope=["state"],
            out_of_scope=[],
        )
    )
    task = service.create_task(
        milestone_id="M1-stop",
        title="Blocked task",
        description="Must not execute after stop",
        acceptance_criteria=[],
    )
    store.milestones["M1-stop"].stop_reason = StopReason.EXTERNAL_REVIEW_REQUIRED
    with pytest.raises(GovernanceViolation, match="stopped"):
        service.transition_task(task.task_id, TaskStatus.READY, actor_party=None)
