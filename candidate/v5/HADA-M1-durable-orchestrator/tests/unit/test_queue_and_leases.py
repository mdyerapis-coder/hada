import pytest

from hada.queue.broker import DurableQueue, InMemoryStreamBackend, QueueMessage
from hada.queue.leases import InMemoryLeaseBackend, LeaseError, LeaseManager


def test_queue_claim_complete() -> None:
    backend = InMemoryStreamBackend()
    queue = DurableQueue(
        backend,
        namespace="hada-test",
        consumer_group="workers",
        maximum_delivery_attempts=3,
        maximum_stream_length=100,
        visibility_timeout_seconds=0,
    )
    queue.enqueue("party-1", QueueMessage(kind="task.dispatch", payload={"task_id": "1"}))
    claimed = queue.claim("party-1", "worker-1")
    assert claimed[0].message.payload["task_id"] == "1"
    queue.complete("party-1", claimed[0])
    assert queue.claim("party-1", "worker-1", block_milliseconds=0) == []


def test_queue_dead_letters_after_delivery_limit() -> None:
    backend = InMemoryStreamBackend()
    queue = DurableQueue(
        backend,
        namespace="hada-test",
        consumer_group="workers",
        maximum_delivery_attempts=2,
        maximum_stream_length=100,
        visibility_timeout_seconds=0,
    )
    queue.enqueue("party-1", QueueMessage(kind="task.dispatch", payload={"task_id": "1"}))
    first = queue.claim("party-1", "worker-1")[0]
    assert queue.fail("party-1", first, "transient") is False
    second = queue.reclaim_stale("party-1", "worker-2")[0]
    assert second.deliveries == 2
    assert queue.fail("party-1", second, "permanent") is True
    assert "hada-test:queue:party-1:dead-letter" in backend.messages


def test_lease_token_prevents_foreign_release() -> None:
    manager = LeaseManager(InMemoryLeaseBackend(), namespace="test")
    lease = manager.acquire("task/1", "worker-a", ttl_seconds=60)
    assert lease is not None
    assert manager.acquire("task/1", "worker-b", ttl_seconds=60) is None
    forged = lease.model_copy(update={"token": "x" * 40})
    with pytest.raises(LeaseError):
        manager.release(forged)
    renewed = manager.renew(lease, ttl_seconds=120)
    assert renewed.expires_at > lease.expires_at
    manager.release(renewed)
    assert manager.acquire("task/1", "worker-b", ttl_seconds=60) is not None


def test_queue_does_not_trim_unacknowledged_messages() -> None:
    backend = InMemoryStreamBackend()
    queue = DurableQueue(
        backend,
        namespace="hada-test",
        consumer_group="workers",
        maximum_delivery_attempts=3,
        maximum_stream_length=1,
        visibility_timeout_seconds=0,
    )
    for task_id in ("1", "2", "3"):
        queue.enqueue(
            "party-1",
            QueueMessage(kind="task.dispatch", payload={"task_id": task_id}),
        )
    claimed = queue.claim("party-1", "worker-1", count=3, block_milliseconds=0)
    assert [item.message.payload["task_id"] for item in claimed] == ["1", "2", "3"]
