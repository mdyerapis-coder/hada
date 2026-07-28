import pytest

from hada.orchestrator.lifecycle import InvalidTaskTransition, TaskRecord, TaskStatus


def test_task_lifecycle_and_optimistic_version() -> None:
    task = TaskRecord(
        milestone_id="M1",
        title="State",
        description="Create durable state",
    )
    ready = task.transition(TaskStatus.READY, expected_version=0)
    leased = ready.transition(TaskStatus.LEASED, expected_version=1)
    running = leased.transition(TaskStatus.RUNNING, expected_version=2)
    review = running.transition(TaskStatus.AWAITING_REVIEW, expected_version=3)
    complete = review.transition(TaskStatus.COMPLETED, expected_version=4)
    assert complete.version == 5
    assert complete.status == TaskStatus.COMPLETED


def test_invalid_transition_rejected() -> None:
    task = TaskRecord(milestone_id="M1", title="State", description="State")
    with pytest.raises(InvalidTaskTransition):
        task.transition(TaskStatus.RUNNING, expected_version=0)


def test_stale_version_rejected() -> None:
    task = TaskRecord(milestone_id="M1", title="State", description="State")
    with pytest.raises(InvalidTaskTransition):
        task.transition(TaskStatus.READY, expected_version=9)
