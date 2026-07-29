from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from hada.governance.engine import GovernanceEngine, GovernanceResult, GovernanceViolation
from hada.models import GateDecision, MilestoneState, StopReason
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus


class OrchestratorStore(Protocol):
    def create_milestone(self, state: MilestoneState) -> None: ...

    def get_milestone(self, milestone_id: str) -> MilestoneState: ...

    def create_task(self, task: TaskRecord) -> None: ...

    def get_task(self, task_id: str) -> TaskRecord: ...

    def save_task_transition(
        self,
        before: TaskRecord,
        after: TaskRecord,
        *,
        actor_party: int | None = None,
    ) -> None: ...

    def save_task_transition_with_outbox(
        self,
        before: TaskRecord,
        after: TaskRecord,
        *,
        queue_name: str,
        message_kind: str,
        payload: dict[str, Any],
        actor_party: int | None = None,
    ) -> str: ...

    def enqueue_outbox(
        self,
        *,
        queue_name: str,
        message_kind: str,
        payload: dict[str, object],
        stream: str,
        actor_party: int | None,
    ) -> str: ...

    def record_gate_decision(
        self,
        milestone_id: str,
        decision: GateDecision,
        resulting_stop_reason: StopReason | None = None,
    ) -> str: ...


class OrchestratorService:
    def __init__(
        self,
        store: OrchestratorStore,
        governance: GovernanceEngine | None = None,
    ) -> None:
        self.store = store
        self.governance = governance or GovernanceEngine()

    def create_milestone(self, state: MilestoneState) -> None:
        if state.stop_reason != StopReason.NONE:
            raise GovernanceViolation("a new milestone must begin without a stop reason")
        self.store.create_milestone(state)

    def create_task(
        self,
        *,
        milestone_id: str,
        title: str,
        description: str,
        acceptance_criteria: list[str],
        assigned_party: int = 1,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        milestone = self.store.get_milestone(milestone_id)
        if milestone.stop_reason != StopReason.NONE:
            raise GovernanceViolation(f"milestone is stopped: {milestone.stop_reason}")
        if assigned_party == 3:
            raise GovernanceViolation("Party 3 may not receive internal execution tasks")
        task = TaskRecord(
            task_id=task_id or str(uuid4()),
            milestone_id=milestone_id,
            title=title,
            description=description,
            assigned_party=assigned_party,
            acceptance_criteria=acceptance_criteria,
            metadata=dict(metadata or {}),
        )
        self.store.create_task(task)
        return task

    def ready_and_schedule_task(
        self,
        task_id: str,
        *,
        message_kind: str = "task.dispatch",
        actor_party: int | None = None,
    ) -> tuple[TaskRecord, str]:
        """Atomically mark a proposed task ready and enqueue its dispatch."""
        before = self.store.get_task(task_id)
        milestone = self.store.get_milestone(before.milestone_id)
        if milestone.stop_reason != StopReason.NONE:
            raise GovernanceViolation(f"milestone is stopped: {milestone.stop_reason}")
        if before.status != TaskStatus.PROPOSED:
            raise GovernanceViolation("only proposed tasks may be atomically dispatched")
        after = before.transition(TaskStatus.READY, expected_version=before.version)
        payload: dict[str, Any] = {
            "task_id": after.task_id,
            "milestone_id": after.milestone_id,
            "assigned_party": after.assigned_party,
            "expected_version": after.version,
        }
        outbox_id = self.store.save_task_transition_with_outbox(
            before,
            after,
            queue_name=f"party-{after.assigned_party}",
            message_kind=message_kind,
            payload=payload,
            actor_party=actor_party,
        )
        return after, outbox_id

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        actor_party: int | None,
        workspace_id: str | None = None,
    ) -> TaskRecord:
        before = self.store.get_task(task_id)
        milestone = self.store.get_milestone(before.milestone_id)
        if milestone.stop_reason != StopReason.NONE:
            raise GovernanceViolation(f"milestone is stopped: {milestone.stop_reason}")
        if actor_party == 3:
            raise GovernanceViolation("Party 3 may not mutate internal task state")
        if target in {TaskStatus.LEASED, TaskStatus.RUNNING, TaskStatus.AWAITING_REVIEW}:
            if actor_party != before.assigned_party:
                raise GovernanceViolation(
                    "only the assigned party may perform execution transitions"
                )
        if target in {TaskStatus.COMPLETED, TaskStatus.REJECTED} and actor_party != 2:
            raise GovernanceViolation("Party 2 must decide the internal review outcome")
        after = before.transition(
            target,
            expected_version=before.version,
            workspace_id=workspace_id,
        )
        self.store.save_task_transition(before, after, actor_party=actor_party)
        return after

    def schedule_task(self, task_id: str, *, actor_party: int | None = None) -> str:
        task = self.store.get_task(task_id)
        milestone = self.store.get_milestone(task.milestone_id)
        if milestone.stop_reason != StopReason.NONE:
            raise GovernanceViolation(f"milestone is stopped: {milestone.stop_reason}")
        if task.status != TaskStatus.READY:
            raise GovernanceViolation("only ready tasks may be scheduled")
        payload: dict[str, object] = {
            "task_id": task.task_id,
            "milestone_id": task.milestone_id,
            "assigned_party": task.assigned_party,
            "expected_version": task.version,
        }
        return self.store.enqueue_outbox(
            queue_name=f"party-{task.assigned_party}",
            message_kind="task.dispatch",
            payload=payload,
            stream=f"task:{task.task_id}",
            actor_party=actor_party,
        )

    def record_gate_decision(
        self,
        milestone_id: str,
        decision: GateDecision,
    ) -> GovernanceResult:
        state = self.store.get_milestone(milestone_id)
        result = self.governance.record_decision(state, decision)
        self.store.record_gate_decision(
            milestone_id,
            decision,
            resulting_stop_reason=result.state.stop_reason,
        )
        return result
