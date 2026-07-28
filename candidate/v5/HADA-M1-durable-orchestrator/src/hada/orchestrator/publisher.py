from __future__ import annotations

from typing import Protocol

from hada.orchestrator.outbox import OutboxRecord
from hada.queue.broker import DurableQueue, QueueMessage


class OutboxStore(Protocol):
    def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        stale_after_seconds: int = 300,
    ) -> list[OutboxRecord]: ...

    def mark_outbox_published(self, outbox_id: str, worker_id: str) -> None: ...

    def mark_outbox_failed(
        self,
        outbox_id: str,
        worker_id: str,
        error: str,
        *,
        maximum_attempts: int,
        retry_delay_seconds: int,
    ) -> None: ...


class OutboxPublisher:
    def __init__(
        self,
        store: OutboxStore,
        queue: DurableQueue,
        *,
        worker_id: str,
        maximum_attempts: int,
        retry_delay_seconds: int,
    ) -> None:
        self.store = store
        self.queue = queue
        self.worker_id = worker_id
        self.maximum_attempts = maximum_attempts
        self.retry_delay_seconds = retry_delay_seconds

    def publish_once(self, *, limit: int = 50) -> tuple[int, int]:
        published = 0
        failed = 0
        records = self.store.claim_outbox(worker_id=self.worker_id, limit=limit)
        for record in records:
            try:
                self.queue.enqueue(
                    record.queue_name,
                    QueueMessage(
                        message_id=record.outbox_id,
                        kind=record.message_kind,
                        payload=record.payload,
                        created_at=record.created_at,
                    ),
                )
                self.store.mark_outbox_published(record.outbox_id, self.worker_id)
                published += 1
            except Exception as exc:
                self.store.mark_outbox_failed(
                    record.outbox_id,
                    self.worker_id,
                    str(exc),
                    maximum_attempts=self.maximum_attempts,
                    retry_delay_seconds=self.retry_delay_seconds,
                )
                failed += 1
        return published, failed
