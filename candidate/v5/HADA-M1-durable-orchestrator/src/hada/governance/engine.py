from __future__ import annotations

from dataclasses import dataclass

from hada.models import GateDecision, GateName, GateStatus, MilestoneState, StopReason


class GovernanceViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class GovernanceResult:
    state: MilestoneState
    may_continue: bool
    message: str


_INTERNAL_GATES = (
    GateName.ARCHITECTURE,
    GateName.SECURITY,
    GateName.TEST,
    GateName.DOCUMENTATION,
    GateName.MILESTONE_REPORT,
)


class GovernanceEngine:
    @staticmethod
    def _validate_parties(decision: GateDecision) -> None:
        if decision.subject_party != 1:
            raise GovernanceViolation("all HADA milestone reviews must assess Party 1 work")
        if decision.gate == GateName.EXTERNAL_REVIEW:
            if decision.reviewer_party != 3:
                raise GovernanceViolation("external review must be performed by Party 3")
            return
        if decision.reviewer_party != 2:
            raise GovernanceViolation("internal governance gates must be reviewed by Party 2")

    @staticmethod
    def _internal_gates_approved(state: MilestoneState) -> bool:
        return all(
            state.gates[gate] is not None
            and state.gates[gate].status == GateStatus.APPROVED
            for gate in _INTERNAL_GATES
        )

    def record_decision(self, state: MilestoneState, decision: GateDecision) -> GovernanceResult:
        if state.stop_reason not in {StopReason.NONE, StopReason.EXTERNAL_REVIEW_REQUIRED}:
            raise GovernanceViolation(f"milestone is stopped: {state.stop_reason}")
        if decision.gate not in state.gates:
            raise GovernanceViolation(f"unknown gate: {decision.gate}")
        if decision.status == GateStatus.PENDING:
            raise GovernanceViolation("pending is not a final gate decision")
        if state.gates[decision.gate] is not None:
            raise GovernanceViolation(f"gate decision is immutable: {decision.gate}")

        self._validate_parties(decision)

        if state.stop_reason == StopReason.EXTERNAL_REVIEW_REQUIRED:
            if decision.gate != GateName.EXTERNAL_REVIEW:
                raise GovernanceViolation("only the external-review gate may proceed")
        elif decision.gate == GateName.EXTERNAL_REVIEW:
            if not self._internal_gates_approved(state):
                raise GovernanceViolation(
                    "external review may not occur before every internal gate is approved"
                )

        state.gates[decision.gate] = decision

        if decision.status in {GateStatus.REJECTED, GateStatus.BLOCKED}:
            state.stop_reason = StopReason.HUMAN_INPUT_REQUIRED
            return GovernanceResult(state, False, f"gate {decision.gate} did not pass")

        if state.is_complete():
            state.stop_reason = StopReason.MILESTONE_COMPLETE
            return GovernanceResult(state, False, "milestone complete")

        if self._internal_gates_approved(state):
            state.stop_reason = StopReason.EXTERNAL_REVIEW_REQUIRED
            return GovernanceResult(state, False, "external independent review required")

        state.stop_reason = StopReason.NONE
        return GovernanceResult(state, True, "next gate may proceed")
