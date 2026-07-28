import pytest

from hada.governance.engine import GovernanceEngine, GovernanceViolation
from hada.models import GateDecision, GateName, GateStatus, MilestoneState, StopReason


def state() -> MilestoneState:
    return MilestoneState(
        milestone_id="M0",
        title="Foundation",
        scope=["governance"],
        out_of_scope=["Hermesctl changes"],
    )


def test_self_approval_rejected() -> None:
    with pytest.raises(ValueError):
        GateDecision(
            gate=GateName.ARCHITECTURE,
            status=GateStatus.APPROVED,
            reviewer_party=1,
            subject_party=1,
            evidence=["sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
        )


def test_approval_without_evidence_rejected() -> None:
    with pytest.raises(ValueError):
        GateDecision(
            gate=GateName.ARCHITECTURE,
            status=GateStatus.APPROVED,
            reviewer_party=2,
            subject_party=1,
        )


def test_external_review_must_be_party_three() -> None:
    engine = GovernanceEngine()
    with pytest.raises(GovernanceViolation):
        engine.record_decision(
            state(),
            GateDecision(
                gate=GateName.EXTERNAL_REVIEW,
                status=GateStatus.APPROVED,
                reviewer_party=2,
                subject_party=1,
                evidence=["sha256:" + "a" * 64],
            ),
        )


def test_internal_gates_stop_at_external_review() -> None:
    engine = GovernanceEngine()
    current = state()
    for gate in [
        GateName.ARCHITECTURE,
        GateName.SECURITY,
        GateName.TEST,
        GateName.DOCUMENTATION,
        GateName.MILESTONE_REPORT,
    ]:
        result = engine.record_decision(
            current,
            GateDecision(
                gate=gate,
                status=GateStatus.APPROVED,
                reviewer_party=2,
                subject_party=1,
                evidence=["sha256:" + "b" * 64],
            ),
        )
        current = result.state
    assert current.stop_reason == StopReason.EXTERNAL_REVIEW_REQUIRED
    assert result.may_continue is False


def _approved(gate: GateName, *, reviewer: int = 2, subject: int = 1) -> GateDecision:
    return GateDecision(
        gate=gate,
        status=GateStatus.APPROVED,
        reviewer_party=reviewer,
        subject_party=subject,
        evidence=["sha256:" + "c" * 64],
    )


def test_internal_review_must_be_party_two() -> None:
    with pytest.raises(GovernanceViolation, match="Party 2"):
        GovernanceEngine().record_decision(
            state(),
            GateDecision(
                gate=GateName.SECURITY,
                status=GateStatus.REJECTED,
                reviewer_party=1,
                subject_party=1,
            ),
        )


def test_reviews_must_assess_party_one_work() -> None:
    with pytest.raises(GovernanceViolation, match="Party 1"):
        GovernanceEngine().record_decision(
            state(),
            GateDecision(
                gate=GateName.TEST,
                status=GateStatus.REJECTED,
                reviewer_party=2,
                subject_party=2,
            ),
        )


def test_external_review_cannot_run_early() -> None:
    with pytest.raises(GovernanceViolation, match="before every internal gate"):
        GovernanceEngine().record_decision(
            state(),
            _approved(GateName.EXTERNAL_REVIEW, reviewer=3),
        )


def test_gate_decisions_are_immutable() -> None:
    engine = GovernanceEngine()
    current = state()
    engine.record_decision(current, _approved(GateName.ARCHITECTURE))
    with pytest.raises(GovernanceViolation, match="immutable"):
        engine.record_decision(current, _approved(GateName.ARCHITECTURE))


def test_only_external_review_may_follow_external_stop() -> None:
    current = state().model_copy(
        update={"stop_reason": StopReason.EXTERNAL_REVIEW_REQUIRED},
        deep=True,
    )
    with pytest.raises(GovernanceViolation, match="only the external-review gate"):
        GovernanceEngine().record_decision(
            current,
            _approved(GateName.ARCHITECTURE),
        )


def test_external_approval_completes_milestone() -> None:
    engine = GovernanceEngine()
    current = state()
    for gate in (
        GateName.ARCHITECTURE,
        GateName.SECURITY,
        GateName.TEST,
        GateName.DOCUMENTATION,
        GateName.MILESTONE_REPORT,
    ):
        engine.record_decision(current, _approved(gate))
    result = engine.record_decision(
        current,
        _approved(GateName.EXTERNAL_REVIEW, reviewer=3),
    )
    assert result.state.stop_reason == StopReason.MILESTONE_COMPLETE
    assert result.may_continue is False


def test_pending_decision_is_not_recordable() -> None:
    with pytest.raises(GovernanceViolation, match="not a final"):
        GovernanceEngine().record_decision(
            state(),
            GateDecision(
                gate=GateName.ARCHITECTURE,
                status=GateStatus.PENDING,
                reviewer_party=2,
                subject_party=1,
            ),
        )
