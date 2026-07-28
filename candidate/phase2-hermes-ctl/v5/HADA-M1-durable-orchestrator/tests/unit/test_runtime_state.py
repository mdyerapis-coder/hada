"""Unit tests for real queue-depth stats used by the /api/v1/state endpoint."""
from __future__ import annotations

from hada.queue.broker import DurableQueue, InMemoryStreamBackend, QueueMessage


def _new_queue() -> DurableQueue:
    return DurableQueue(
        InMemoryStreamBackend(),
        namespace="hada", consumer_group="orchestrator",
        maximum_delivery_attempts=5, maximum_stream_length=100,
        visibility_timeout_seconds=300,
    )


def test_queue_stats_empty():
    s = _new_queue().stats()
    assert s["enqueued"] == 0 and s["pending"] == 0
    assert s["queue"] == "tasks" and s["namespace"] == "hada"


def test_queue_stats_after_enqueue_and_claim():
    q = _new_queue()
    q.enqueue("tasks", QueueMessage(kind="x", payload={}))
    q.enqueue("tasks", QueueMessage(kind="y", payload={}))
    assert q.stats()["enqueued"] == 2
    c1 = q.claim("tasks", "worker")[0]
    c2 = q.claim("tasks", "worker")[0]
    assert q.stats()["pending"] == 2
    q.complete("tasks", c1)
    assert q.stats()["pending"] == 1
    q.complete("tasks", c2)
    assert q.stats()["pending"] == 0
