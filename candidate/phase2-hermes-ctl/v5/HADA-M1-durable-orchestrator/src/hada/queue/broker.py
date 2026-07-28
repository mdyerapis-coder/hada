from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from hada.canonical import canonical_json


class QueueError(RuntimeError):
    pass


class QueueMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class BackendMessage:
    stream_id: str
    envelope: bytes
    deliveries: int


class StreamBackend(Protocol):
    def ping(self) -> bool: ...

    def ensure_group(self, stream: str, group: str) -> None: ...

    def add(self, stream: str, envelope: bytes, maximum_length: int) -> str: ...

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int,
        block_milliseconds: int,
    ) -> list[BackendMessage]: ...

    def auto_claim(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        minimum_idle_milliseconds: int,
        count: int,
    ) -> list[BackendMessage]: ...

    def ack(self, stream: str, group: str, stream_id: str) -> None: ...

    def delete(self, stream: str, stream_id: str) -> None: ...

    def length(self, stream: str) -> int: ...

    def pending_count(self, stream: str, group: str) -> int: ...


class RedisStreamBackend:
    def __init__(self, url: str) -> None:
        try:
            import redis
        except ImportError as exc:
            raise QueueError("redis package is required for Valkey queues") from exc
        self._client: Any = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=10,
            health_check_interval=30,
        )

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def ensure_group(self, stream: str, group: str) -> None:
        try:
            self._client.xgroup_create(stream, group, id="0-0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise QueueError(f"unable to create consumer group {group}") from exc

    def add(self, stream: str, envelope: bytes, maximum_length: int) -> str:
        del maximum_length
        stream_id = self._client.xadd(stream, {b"envelope": envelope})
        return stream_id.decode("ascii") if isinstance(stream_id, bytes) else str(stream_id)

    @staticmethod
    def _delivery_count(client: Any, stream: str, group: str, stream_id: str) -> int:
        rows = client.xpending_range(stream, group, min=stream_id, max=stream_id, count=1)
        if not rows:
            return 1
        row = rows[0]
        value = row.get("times_delivered", row.get(b"times_delivered", 1))
        return int(value)

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int,
        block_milliseconds: int,
    ) -> list[BackendMessage]:
        result = self._client.xreadgroup(
            group,
            consumer,
            {stream: ">"},
            count=count,
            block=block_milliseconds,
        )
        messages: list[BackendMessage] = []
        for _, rows in result:
            for raw_id, fields in rows:
                stream_id = raw_id.decode("ascii") if isinstance(raw_id, bytes) else str(raw_id)
                envelope = fields.get(b"envelope", fields.get("envelope"))
                if not isinstance(envelope, bytes):
                    envelope = str(envelope).encode("utf-8")
                messages.append(
                    BackendMessage(
                        stream_id=stream_id,
                        envelope=envelope,
                        deliveries=self._delivery_count(
                            self._client, stream, group, stream_id
                        ),
                    )
                )
        return messages

    def auto_claim(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        minimum_idle_milliseconds: int,
        count: int,
    ) -> list[BackendMessage]:
        result = self._client.xautoclaim(
            stream,
            group,
            consumer,
            min_idle_time=minimum_idle_milliseconds,
            start_id="0-0",
            count=count,
        )
        rows = result[1] if len(result) >= 2 else []
        messages: list[BackendMessage] = []
        for raw_id, fields in rows:
            stream_id = raw_id.decode("ascii") if isinstance(raw_id, bytes) else str(raw_id)
            envelope = fields.get(b"envelope", fields.get("envelope"))
            if not isinstance(envelope, bytes):
                envelope = str(envelope).encode("utf-8")
            messages.append(
                BackendMessage(
                    stream_id=stream_id,
                    envelope=envelope,
                    deliveries=self._delivery_count(self._client, stream, group, stream_id),
                )
            )
        return messages

    def ack(self, stream: str, group: str, stream_id: str) -> None:
        self._client.xack(stream, group, stream_id)

    def delete(self, stream: str, stream_id: str) -> None:
        self._client.xdel(stream, stream_id)

    def length(self, stream: str) -> int:
        try:
            return int(self._client.xlen(stream))
        except Exception:
            return 0

    def pending_count(self, stream: str, group: str) -> int:
        try:
            summary = self._client.xpending(stream, group)
            if isinstance(summary, dict):
                value = summary.get("pending", summary.get(b"pending", 0))
                return int(value)
        except Exception:
            return 0
        return 0


@dataclass
class _MemoryPending:
    consumer: str
    deliveries: int
    claimed_at: float


class InMemoryStreamBackend:
    """Deterministic backend used by unit tests and offline governance validation."""

    def __init__(self) -> None:
        self.messages: dict[str, list[tuple[str, bytes]]] = {}
        self.groups: dict[tuple[str, str], int] = {}
        self.pending: dict[tuple[str, str, str], _MemoryPending] = {}
        self.counter = 0

    def ping(self) -> bool:
        return True

    def ensure_group(self, stream: str, group: str) -> None:
        self.messages.setdefault(stream, [])
        self.groups.setdefault((stream, group), 0)

    def add(self, stream: str, envelope: bytes, maximum_length: int) -> str:
        self.counter += 1
        stream_id = f"{self.counter}-0"
        del maximum_length
        entries = self.messages.setdefault(stream, [])
        entries.append((stream_id, envelope))
        return stream_id

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int,
        block_milliseconds: int,
    ) -> list[BackendMessage]:
        del block_milliseconds
        self.ensure_group(stream, group)
        offset = self.groups[(stream, group)]
        rows = self.messages.get(stream, [])[offset : offset + count]
        self.groups[(stream, group)] = offset + len(rows)
        result: list[BackendMessage] = []
        for stream_id, envelope in rows:
            pending = _MemoryPending(consumer=consumer, deliveries=1, claimed_at=time.monotonic())
            self.pending[(stream, group, stream_id)] = pending
            result.append(BackendMessage(stream_id, envelope, pending.deliveries))
        return result

    def auto_claim(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        minimum_idle_milliseconds: int,
        count: int,
    ) -> list[BackendMessage]:
        now = time.monotonic()
        by_id = dict(self.messages.get(stream, []))
        result: list[BackendMessage] = []
        for key, pending in list(self.pending.items()):
            pending_stream, pending_group, stream_id = key
            if pending_stream != stream or pending_group != group:
                continue
            idle = (now - pending.claimed_at) * 1000
            if idle < minimum_idle_milliseconds:
                continue
            pending.consumer = consumer
            pending.deliveries += 1
            pending.claimed_at = now
            result.append(BackendMessage(stream_id, by_id[stream_id], pending.deliveries))
            if len(result) >= count:
                break
        return result

    def ack(self, stream: str, group: str, stream_id: str) -> None:
        self.pending.pop((stream, group, stream_id), None)

    def delete(self, stream: str, stream_id: str) -> None:
        self.messages[stream] = [
            row for row in self.messages.get(stream, []) if row[0] != stream_id
        ]

    def length(self, stream: str) -> int:
        return len(self.messages.get(stream, []))

    def pending_count(self, stream: str, group: str) -> int:
        return sum(
            1 for key in self.pending if key[0] == stream and key[1] == group
        )


class ClaimedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stream_id: str
    deliveries: int = Field(ge=1)
    message: QueueMessage


class DurableQueue:
    def __init__(
        self,
        backend: StreamBackend,
        *,
        namespace: str,
        consumer_group: str,
        maximum_delivery_attempts: int,
        maximum_stream_length: int,
        visibility_timeout_seconds: int,
        primary_queue: str = "tasks",
    ) -> None:
        self.backend = backend
        self.namespace = namespace
        self.consumer_group = consumer_group
        self.maximum_delivery_attempts = maximum_delivery_attempts
        self.maximum_stream_length = maximum_stream_length
        self.visibility_timeout_seconds = visibility_timeout_seconds
        self.primary_queue = primary_queue

    def _stream(self, queue: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
        if not queue or any(character not in allowed for character in queue):
            raise QueueError(f"invalid queue name: {queue!r}")
        return f"{self.namespace}:queue:{queue}"

    def _dead_letter_stream(self, queue: str) -> str:
        return f"{self._stream(queue)}:dead-letter"

    def enqueue(self, queue: str, message: QueueMessage) -> str:
        stream = self._stream(queue)
        self.backend.ensure_group(stream, self.consumer_group)
        return self.backend.add(stream, canonical_json(message), self.maximum_stream_length)

    @staticmethod
    def _decode(row: BackendMessage) -> ClaimedMessage:
        try:
            decoded = json.loads(row.envelope.decode("utf-8"))
            message = QueueMessage.model_validate(decoded)
        except Exception as exc:
            raise QueueError(f"invalid queued message at {row.stream_id}") from exc
        return ClaimedMessage(
            stream_id=row.stream_id,
            deliveries=row.deliveries,
            message=message,
        )

    def claim(
        self,
        queue: str,
        consumer: str,
        *,
        count: int = 1,
        block_milliseconds: int = 5000,
    ) -> list[ClaimedMessage]:
        stream = self._stream(queue)
        self.backend.ensure_group(stream, self.consumer_group)
        rows = self.backend.read_group(
            stream,
            self.consumer_group,
            consumer,
            count=count,
            block_milliseconds=block_milliseconds,
        )
        return [self._decode(row) for row in rows]

    def reclaim_stale(self, queue: str, consumer: str, *, count: int = 10) -> list[ClaimedMessage]:
        stream = self._stream(queue)
        rows = self.backend.auto_claim(
            stream,
            self.consumer_group,
            consumer,
            minimum_idle_milliseconds=self.visibility_timeout_seconds * 1000,
            count=count,
        )
        return [self._decode(row) for row in rows]

    def complete(self, queue: str, claimed: ClaimedMessage) -> None:
        stream = self._stream(queue)
        self.backend.ack(stream, self.consumer_group, claimed.stream_id)
        self.backend.delete(stream, claimed.stream_id)

    def fail(self, queue: str, claimed: ClaimedMessage, reason: str) -> bool:
        """Leave retryable messages pending; move exhausted messages to the dead-letter stream."""
        if claimed.deliveries < self.maximum_delivery_attempts:
            return False
        dead_letter = {
            "failed_message": claimed.message.model_dump(mode="json"),
            "source_stream_id": claimed.stream_id,
            "deliveries": claimed.deliveries,
            "reason": reason[:4000],
            "failed_at": datetime.now(UTC),
        }
        self.backend.add(
            self._dead_letter_stream(queue),
            canonical_json(dead_letter),
            self.maximum_stream_length,
        )
        self.complete(queue, claimed)
        return True

    def ping(self) -> bool:
        return self.backend.ping()

    def stats(self) -> dict[str, object]:
        """Real queue depth for the primary queue (no message bodies read)."""
        stream = self._stream(self.primary_queue)
        return {
            "queue": self.primary_queue,
            "namespace": self.namespace,
            "consumer_group": self.consumer_group,
            "enqueued": self.backend.length(stream),
            "pending": self.backend.pending_count(stream, self.consumer_group),
            "maximum_delivery_attempts": self.maximum_delivery_attempts,
        }
