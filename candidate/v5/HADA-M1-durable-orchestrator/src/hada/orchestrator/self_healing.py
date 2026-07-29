from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hada.canonical import canonical_json
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus
from hada.orchestrator.service import OrchestratorService


class RepairClass(StrEnum):
    SOURCE_CODE = "source_code"
    TEST = "test"
    BUILD = "build"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    SECRET = "secret"
    INFRASTRUCTURE = "infrastructure"
    DEPLOYMENT = "deployment"
    GOVERNANCE = "governance"
    UNKNOWN = "unknown"


_AUTO_REPAIRABLE = frozenset(
    {
        RepairClass.SOURCE_CODE,
        RepairClass.TEST,
        RepairClass.BUILD,
        RepairClass.DOCUMENTATION,
    }
)


class Incident(BaseModel):
    """Deterministic error signal emitted by a detector or post-action verifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=256)
    error_class: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2000)
    repair_class: RepairClass = RepairClass.UNKNOWN
    evidence: list[str] = Field(min_length=1, max_length=50)

    @property
    def fingerprint(self) -> str:
        identity = {
            "source": self.source,
            "subject": self.subject,
            "error_class": self.error_class,
            "repair_class": self.repair_class,
            "summary": self.summary,
            "evidence": self.evidence,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    @property
    def auto_repairable(self) -> bool:
        return self.repair_class in _AUTO_REPAIRABLE


class RepairDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["dispatched", "already_active", "resolved", "human_required"]
    incident_fingerprint: str
    task_id: str
    attempt: int = Field(ge=1)
    reason: str


class SelfHealingSupervisor:
    """Deduplicate incidents and apply a bounded repair worker when policy permits."""

    def __init__(
        self,
        orchestrator: OrchestratorService,
        milestone_id: str,
        *,
        maximum_attempts: int = 3,
    ) -> None:
        if maximum_attempts < 1 or maximum_attempts > 10:
            raise ValueError("maximum_attempts must be between 1 and 10")
        self.orchestrator = orchestrator
        self.milestone_id = milestone_id
        self.maximum_attempts = maximum_attempts

    @staticmethod
    def _task_id(incident: Incident, attempt: int) -> str:
        return f"repair-{incident.fingerprint[:24]}-{attempt}"

    def _find_task(self, task_id: str) -> TaskRecord | None:
        try:
            return self.orchestrator.store.get_task(task_id)
        except KeyError:
            return None

    def _create_flag(self, incident: Incident, attempt: int) -> TaskRecord:
        task_id = self._task_id(incident, attempt)
        evidence = "\n".join(f"- {item}" for item in incident.evidence)
        metadata = {
            "incident_fingerprint": incident.fingerprint,
            "incident_source": incident.source,
            "error_class": incident.error_class,
            "repair_class": incident.repair_class.value,
            "repair_attempt": attempt,
            "auto_repair": incident.auto_repairable,
            "evidence": list(incident.evidence),
        }
        return self.orchestrator.create_task(
            milestone_id=self.milestone_id,
            task_id=task_id,
            title=f"Repair: {incident.subject}",
            description=(
                f"Detector: {incident.source}\nError: {incident.summary}\nEvidence:\n{evidence}"
            ),
            acceptance_criteria=[
                "reproduce the incident before modification",
                "add or retain a regression check",
                "run the complete fail-closed verification gate",
                "route the exact repaired head to independent review",
            ],
            assigned_party=1,
            metadata=metadata,
        )

    def _disposition(
        self,
        status: Literal["dispatched", "already_active", "resolved", "human_required"],
        incident: Incident,
        task: TaskRecord,
        attempt: int,
        reason: str,
    ) -> RepairDisposition:
        return RepairDisposition(
            status=status,
            incident_fingerprint=incident.fingerprint,
            task_id=task.task_id,
            attempt=attempt,
            reason=reason,
        )

    def flag_and_apply_worker(self, incident: Incident) -> RepairDisposition:
        """Persist one incident flag and dispatch a repair worker when safe."""
        last_task: TaskRecord | None = None
        for attempt in range(1, self.maximum_attempts + 1):
            task_id = self._task_id(incident, attempt)
            task = self._find_task(task_id)
            created = False
            if task is None:
                try:
                    task = self._create_flag(incident, attempt)
                    created = True
                except Exception:
                    # A concurrent detector may have won the deterministic-ID
                    # insert. Read the authoritative task before deciding.
                    task = self._find_task(task_id)
                    if task is None:
                        raise
            if created:
                if not incident.auto_repairable:
                    return self._disposition(
                        "human_required",
                        incident,
                        task,
                        attempt,
                        "governance_boundary",
                    )
                ready, _ = self.orchestrator.ready_and_schedule_task(
                    task.task_id,
                    message_kind="repair.dispatch",
                )
                return self._disposition(
                    "dispatched", incident, ready, attempt, "repair_worker_applied"
                )

            last_task = task
            if task.status == TaskStatus.COMPLETED:
                return self._disposition(
                    "resolved", incident, task, attempt, "verified_repair_completed"
                )
            if not bool(task.metadata.get("auto_repair", False)):
                return self._disposition(
                    "human_required", incident, task, attempt, "governance_boundary"
                )
            if task.status == TaskStatus.PROPOSED:
                ready, _ = self.orchestrator.ready_and_schedule_task(
                    task.task_id,
                    message_kind="repair.dispatch",
                )
                return self._disposition(
                    "dispatched", incident, ready, attempt, "recovered_unscheduled_flag"
                )
            if task.status in {
                TaskStatus.READY,
                TaskStatus.LEASED,
                TaskStatus.RUNNING,
                TaskStatus.AWAITING_REVIEW,
            }:
                return self._disposition(
                    "already_active", incident, task, attempt, "repair_in_progress"
                )
            if task.status not in {
                TaskStatus.REJECTED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return self._disposition(
                    "human_required", incident, task, attempt, "unexpected_task_state"
                )

        assert last_task is not None
        return self._disposition(
            "human_required",
            incident,
            last_task,
            self.maximum_attempts,
            "repair_attempts_exhausted",
        )
