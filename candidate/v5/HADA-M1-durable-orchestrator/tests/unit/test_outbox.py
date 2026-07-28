from datetime import UTC, datetime

from hada.orchestrator.outbox import OutboxRecord
from hada.orchestrator.publisher import OutboxPublisher
from hada.queue.broker import DurableQueue, InMemoryStreamBackend


class Store:
    def __init__(self) -> None:
        self.records = [
            OutboxRecord(
                outbox_id="event-1",
                queue_name="party-1",
                message_kind="task.dispatch",
                payload={"task_id": "1"},
                attempts=1,
                created_at=datetime.now(UTC),
            )
        ]
        self.published: list[str] = []
        self.failed: list[str] = []

    def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        stale_after_seconds: int = 300,
    ) -> list[OutboxRecord]:
        del worker_id, limit, stale_after_seconds
        records = self.records
        self.records = []
        return records

    def mark_outbox_published(self, outbox_id: str, worker_id: str) -> None:
        del worker_id
        self.published.append(outbox_id)

    def mark_outbox_failed(
        self,
        outbox_id: str,
        worker_id: str,
        error: str,
        *,
        maximum_attempts: int,
        retry_delay_seconds: int,
    ) -> None:
        del worker_id, error, maximum_attempts, retry_delay_seconds
        self.failed.append(outbox_id)


def test_outbox_publisher_uses_stable_message_id() -> None:
    backend = InMemoryStreamBackend()
    queue = DurableQueue(
        backend,
        namespace="hada",
        consumer_group="orchestrator",
        maximum_delivery_attempts=3,
        maximum_stream_length=100,
        visibility_timeout_seconds=60,
    )
    store = Store()
    publisher = OutboxPublisher(
        store,
        queue,
        worker_id="publisher-1",
        maximum_attempts=3,
        retry_delay_seconds=10,
    )
    assert publisher.publish_once() == (1, 0)
    claimed = queue.claim("party-1", "worker-1")[0]
    assert claimed.message.message_id == "event-1"
    assert store.published == ["event-1"]
