from typing import Any

from hada.models import GateDecision, MilestoneState, StopReason
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus
from hada.orchestrator.self_healing import (
    Incident,
    RepairClass,
    SelfHealingSupervisor,
)
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
        if task.task_id in self.tasks:
            raise ValueError("duplicate task")
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
        del actor_party
        assert self.tasks[before.task_id].version == before.version
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
        return f"outbox-{len(self.outbox)}"

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
        return f"outbox-{len(self.outbox)}"

    def record_gate_decision(
        self,
        milestone_id: str,
        decision: GateDecision,
        resulting_stop_reason: StopReason | None = None,
    ) -> str:
        del milestone_id, decision, resulting_stop_reason
        return "decision-1"


def make_supervisor() -> tuple[MemoryStore, OrchestratorService, SelfHealingSupervisor]:
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
    return store, service, SelfHealingSupervisor(service, "M-repair")


def test_safe_incident_is_flagged_and_atomically_dispatched_once() -> None:
    store, _, supervisor = make_supervisor()
    incident = Incident(
        source="post_action_verifier",
        subject="relationship persistence",
        error_class="test_failure",
        summary="rollback regression reproduced",
        repair_class=RepairClass.TEST,
        evidence=["pytest:tests/test_relationships.py::test_rollback"],
    )

    first = supervisor.flag_and_apply_worker(incident)
    second = supervisor.flag_and_apply_worker(incident)

    assert first.status == "dispatched"
    assert second.status == "already_active"
    assert first.task_id == second.task_id
    assert len(store.tasks) == 1
    assert len(store.outbox) == 1
    task = store.tasks[first.task_id]
    assert task.status == TaskStatus.READY
    assert task.assigned_party == 1
    assert task.metadata["incident_fingerprint"] == incident.fingerprint
    assert store.outbox[0]["message_kind"] == "repair.dispatch"


def test_failed_worker_is_reassigned_with_evidence_up_to_bound() -> None:
    store, service, supervisor = make_supervisor()
    incident = Incident(
        source="ci",
        subject="main",
        error_class="compile_failure",
        summary="compile gate failed",
        repair_class=RepairClass.BUILD,
        evidence=["compile.log:12"],
    )

    task_ids = []
    for attempt in range(1, 4):
        disposition = supervisor.flag_and_apply_worker(incident)
        assert disposition.status == "dispatched"
        assert disposition.attempt == attempt
        task_ids.append(disposition.task_id)
        task = store.tasks[disposition.task_id]
        leased = service.transition_task(task.task_id, TaskStatus.LEASED, actor_party=1)
        service.transition_task(leased.task_id, TaskStatus.FAILED, actor_party=1)

    exhausted = supervisor.flag_and_apply_worker(incident)
    assert exhausted.status == "human_required"
    assert exhausted.reason == "repair_attempts_exhausted"
    assert len(set(task_ids)) == 3
    assert len(store.outbox) == 3


def test_governance_sensitive_incident_is_flagged_without_worker() -> None:
    store, _, supervisor = make_supervisor()
    incident = Incident(
        source="policy",
        subject="production deploy",
        error_class="configuration_error",
        summary="deployment configuration is inconsistent",
        repair_class=RepairClass.DEPLOYMENT,
        evidence=["gate:deployment"],
    )

    result = supervisor.flag_and_apply_worker(incident)

    assert result.status == "human_required"
    assert result.reason == "governance_boundary"
    assert len(store.tasks) == 1
    assert next(iter(store.tasks.values())).status == TaskStatus.PROPOSED
    assert store.outbox == []


def test_completed_repair_marks_repeat_detection_resolved() -> None:
    store, service, supervisor = make_supervisor()
    incident = Incident(
        source="runtime",
        subject="queue consumer",
        error_class="test_failure",
        summary="consumer dropped a message",
        repair_class=RepairClass.SOURCE_CODE,
        evidence=["trace:message-42"],
    )
    dispatched = supervisor.flag_and_apply_worker(incident)
    task = store.tasks[dispatched.task_id]
    leased = service.transition_task(task.task_id, TaskStatus.LEASED, actor_party=1)
    running = service.transition_task(leased.task_id, TaskStatus.RUNNING, actor_party=1)
    review = service.transition_task(running.task_id, TaskStatus.AWAITING_REVIEW, actor_party=1)
    service.transition_task(review.task_id, TaskStatus.COMPLETED, actor_party=2)

    resolved = supervisor.flag_and_apply_worker(incident)
    assert resolved.status == "resolved"
    assert len(store.outbox) == 1


def test_detector_recovers_flag_created_before_dispatch() -> None:
    store, service, supervisor = make_supervisor()
    incident = Incident(
        source="post_action_verifier",
        subject="published SHA",
        error_class="identity_mismatch",
        summary="remote ref differs from verified head",
        repair_class=RepairClass.SOURCE_CODE,
        evidence=["expected:abc actual:def"],
    )
    task_id = f"repair-{incident.fingerprint[:24]}-1"
    service.create_task(
        milestone_id="M-repair",
        task_id=task_id,
        title="Repair: published SHA",
        description="interrupted detector flag",
        acceptance_criteria=["remote equals verified head"],
        metadata={
            "incident_fingerprint": incident.fingerprint,
            "auto_repair": True,
        },
    )

    recovered = supervisor.flag_and_apply_worker(incident)

    assert recovered.status == "dispatched"
    assert recovered.reason == "recovered_unscheduled_flag"
    assert store.tasks[task_id].status == TaskStatus.READY
    assert len(store.outbox) == 1


def test_concurrent_detector_insert_is_deduplicated_and_dispatched() -> None:
    class RacingStore(MemoryStore):
        def create_task(self, task: TaskRecord) -> None:
            if task.task_id.startswith("repair-") and task.task_id not in self.tasks:
                self.tasks[task.task_id] = task
                raise ValueError("simulated concurrent unique-key winner")
            super().create_task(task)

    store = RacingStore()
    service = OrchestratorService(store)
    service.create_milestone(
        MilestoneState(
            milestone_id="M-repair",
            title="Self-healing",
            scope=["automatic safe repairs"],
            out_of_scope=[],
        )
    )
    supervisor = SelfHealingSupervisor(service, "M-repair")
    incident = Incident(
        source="ci",
        subject="unit tests",
        error_class="test_failure",
        summary="a regression was detected",
        repair_class=RepairClass.TEST,
        evidence=["test.log:9"],
    )

    result = supervisor.flag_and_apply_worker(incident)

    assert result.status == "dispatched"
    assert result.reason == "recovered_unscheduled_flag"
    assert len(store.tasks) == 1
    assert len(store.outbox) == 1


def test_fingerprint_collision_avoided_on_different_evidence() -> None:
    """Two incidents with the same source/subject/error_class/repair_class but
    different summary or evidence MUST produce distinct fingerprints."""
    base = dict(
        source="ci",
        subject="unit-tests",
        error_class="test_failure",
    )
    a = Incident(
        **base,
        repair_class=RepairClass.TEST,
        summary="regression in module A",
        evidence=["log:test_a"],
    )
    b = Incident(
        **base,
        repair_class=RepairClass.TEST,
        summary="regression in module B",
        evidence=["log:test_b"],
    )
    c = Incident(
        **base,
        repair_class=RepairClass.TEST,
        summary="regression in module A",
        evidence=["log:test_a", "extra"],
    )

    assert a.fingerprint != b.fingerprint, "different summary + evidence"
    assert a.fingerprint != c.fingerprint, "different evidence length"
    assert b.fingerprint != c.fingerprint, "different summary + evidence"
    # Sanity: same inputs = same fingerprint
    a2 = Incident(
        **base,
        repair_class=RepairClass.TEST,
        summary="regression in module A",
        evidence=["log:test_a"],
    )
    assert a.fingerprint == a2.fingerprint, "deterministic / idempotent"
