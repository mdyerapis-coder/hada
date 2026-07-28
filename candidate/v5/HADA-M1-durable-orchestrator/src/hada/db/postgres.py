from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from hada.audit.chain import GENESIS_HASH, AuditChain, AuditRecord
from hada.canonical import canonical_json
from hada.crypto.signing import Ed25519Signer, SignatureEnvelope
from hada.evidence.store import EvidenceManifest
from hada.models import GateDecision, MilestoneState, StopReason
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus
from hada.orchestrator.outbox import OutboxRecord
from hada.workspaces.manager import WorkspaceRecord


class StateConflict(RuntimeError):
    pass


class PostgresStore:
    def __init__(
        self,
        dsn: str,
        signer: Ed25519Signer,
        *,
        connect_timeout_seconds: int = 10,
        statement_timeout_seconds: int = 30,
    ) -> None:
        self.dsn = dsn
        self.signer = signer
        self.connect_timeout_seconds = connect_timeout_seconds
        self.statement_timeout_seconds = statement_timeout_seconds

    def _connection(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL state") from exc
        return psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout_seconds,
            options=f"-c statement_timeout={self.statement_timeout_seconds * 1000}",
            row_factory=dict_row,
        )

    @staticmethod
    def _json(value: Any) -> Any:
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL JSON values") from exc
        return Jsonb(value)

    def _append_audit_on_connection(
        self,
        connection: Any,
        *,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        actor_party: int | None,
    ) -> AuditRecord:
        chain = AuditChain(self.signer)
        connection.execute("SELECT pg_advisory_xact_lock(hashtext('hada_audit_chain'))")
        row = connection.execute(
            "SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = str(row["event_hash"]) if row else GENESIS_HASH
        record = chain.build(
            previous_hash=previous_hash,
            stream=stream,
            event_type=event_type,
            payload=payload,
            actor_party=actor_party,
        )
        inserted = connection.execute(
            """
            INSERT INTO audit_events (
                event_id, stream, event_type, actor_party, occurred_at, payload,
                previous_hash, event_hash, signer_key_id, signature
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING sequence
            """,
            (
                record.event_id,
                record.stream,
                record.event_type,
                record.actor_party,
                record.occurred_at,
                self._json(record.payload),
                record.previous_hash,
                record.event_hash,
                record.signature.key_id,
                record.signature.signature_b64,
            ),
        ).fetchone()
        if inserted is None:
            raise StateConflict("audit event insert did not return a sequence")
        return record.model_copy(update={"sequence": int(inserted["sequence"])})

    def ping(self) -> bool:
        try:
            with self._connection() as connection:
                row = connection.execute("SELECT 1 AS ok").fetchone()
                return bool(row and row["ok"] == 1)
        except Exception:
            return False

    def create_milestone(self, state: MilestoneState) -> None:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO milestones (
                    milestone_id, title, scope, out_of_scope, implementation_party,
                    stop_reason, version
                ) VALUES (%s, %s, %s, %s, %s, %s, 0)
                """,
                (
                    state.milestone_id,
                    state.title,
                    self._json(state.scope),
                    self._json(state.out_of_scope),
                    state.implementation_party,
                    state.stop_reason.value,
                ),
            )
            self._append_audit_on_connection(
                connection,
                stream=f"milestone:{state.milestone_id}",
                event_type="milestone.created",
                payload=state.model_dump(mode="json"),
                actor_party=None,
            )

    def get_milestone(self, milestone_id: str) -> MilestoneState:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT milestone_id, title, scope, out_of_scope, implementation_party, stop_reason
                FROM milestones WHERE milestone_id = %s
                """,
                (milestone_id,),
            ).fetchone()
            if row is None:
                raise KeyError(milestone_id)
            decision_rows = connection.execute(
                """
                SELECT gate, status, reviewer_party, subject_party, evidence, findings
                FROM gate_decisions WHERE milestone_id = %s ORDER BY created_at
                """,
                (milestone_id,),
            ).fetchall()
        state = MilestoneState(
            milestone_id=str(row["milestone_id"]),
            title=str(row["title"]),
            scope=list(row["scope"]),
            out_of_scope=list(row["out_of_scope"]),
            implementation_party=1,
            stop_reason=StopReason(str(row["stop_reason"])),
        )
        for decision_row in decision_rows:
            decision = GateDecision.model_validate(dict(decision_row))
            state.gates[decision.gate] = decision
        return state

    def update_milestone_stop_reason(
        self,
        milestone_id: str,
        stop_reason: StopReason,
        *,
        expected_version: int,
    ) -> int:
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE milestones
                SET stop_reason = %s, version = version + 1
                WHERE milestone_id = %s AND version = %s
                RETURNING version
                """,
                (stop_reason.value, milestone_id, expected_version),
            ).fetchone()
            if row is None:
                raise StateConflict("milestone version conflict")
            return int(row["version"])

    def create_task(self, task: TaskRecord) -> None:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, milestone_id, title, description, status, assigned_party,
                    acceptance_criteria, metadata, workspace_id, version, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task.task_id,
                    task.milestone_id,
                    task.title,
                    task.description,
                    task.status.value,
                    task.assigned_party,
                    self._json(task.acceptance_criteria),
                    self._json(task.metadata),
                    task.workspace_id,
                    task.version,
                    task.created_at,
                    task.updated_at,
                ),
            )
            self._append_audit_on_connection(
                connection,
                stream=f"task:{task.task_id}",
                event_type="task.created",
                payload=task.model_dump(mode="json"),
                actor_party=None,
            )

    @staticmethod
    def _task_from_row(row: dict[str, Any]) -> TaskRecord:
        return TaskRecord(
            task_id=str(row["task_id"]),
            milestone_id=str(row["milestone_id"]),
            title=str(row["title"]),
            description=str(row["description"]),
            status=TaskStatus(str(row["status"])),
            assigned_party=int(row["assigned_party"]),
            acceptance_criteria=list(row["acceptance_criteria"]),
            metadata=dict(row["metadata"]),
            workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_task(self, task_id: str) -> TaskRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = %s",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            return self._task_from_row(dict(row))

    def save_task_transition(
        self,
        before: TaskRecord,
        after: TaskRecord,
        *,
        actor_party: int | None = None,
    ) -> None:
        if after.version != before.version + 1:
            raise StateConflict("task transition must increment version exactly once")
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE tasks
                SET status = %s, workspace_id = %s, version = %s, updated_at = %s
                WHERE task_id = %s AND version = %s AND status = %s
                RETURNING task_id
                """,
                (
                    after.status.value,
                    after.workspace_id,
                    after.version,
                    after.updated_at,
                    before.task_id,
                    before.version,
                    before.status.value,
                ),
            ).fetchone()
            if row is None:
                raise StateConflict("task state changed concurrently")
            self._append_audit_on_connection(
                connection,
                stream=f"task:{before.task_id}",
                event_type="task.transitioned",
                payload={
                    "from": before.status.value,
                    "to": after.status.value,
                    "before_version": before.version,
                    "after_version": after.version,
                    "workspace_id": after.workspace_id,
                },
                actor_party=actor_party,
            )

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
        if after.version != before.version + 1:
            raise StateConflict("task transition must increment version exactly once")
        outbox_id = str(uuid4())
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE tasks
                SET status = %s, workspace_id = %s, version = %s, updated_at = %s
                WHERE task_id = %s AND version = %s AND status = %s
                RETURNING task_id
                """,
                (
                    after.status.value,
                    after.workspace_id,
                    after.version,
                    after.updated_at,
                    before.task_id,
                    before.version,
                    before.status.value,
                ),
            ).fetchone()
            if row is None:
                raise StateConflict("task state changed concurrently")
            connection.execute(
                """
                INSERT INTO outbox_events (
                    outbox_id, queue_name, message_kind, payload
                ) VALUES (%s, %s, %s, %s)
                """,
                (outbox_id, queue_name, message_kind, self._json(payload)),
            )
            self._append_audit_on_connection(
                connection,
                stream=f"task:{before.task_id}",
                event_type="task.transitioned_and_enqueued",
                payload={
                    "from": before.status.value,
                    "to": after.status.value,
                    "before_version": before.version,
                    "after_version": after.version,
                    "outbox_id": outbox_id,
                    "queue_name": queue_name,
                    "message_kind": message_kind,
                },
                actor_party=actor_party,
            )
        return outbox_id

    def enqueue_outbox(
        self,
        *,
        queue_name: str,
        message_kind: str,
        payload: dict[str, Any],
        stream: str,
        actor_party: int | None,
    ) -> str:
        outbox_id = str(uuid4())
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO outbox_events (outbox_id, queue_name, message_kind, payload)
                VALUES (%s, %s, %s, %s)
                """,
                (outbox_id, queue_name, message_kind, self._json(payload)),
            )
            self._append_audit_on_connection(
                connection,
                stream=stream,
                event_type="outbox.enqueued",
                payload={
                    "outbox_id": outbox_id,
                    "queue_name": queue_name,
                    "message_kind": message_kind,
                    "payload_digest": hashlib.sha256(canonical_json(payload)).hexdigest(),
                },
                actor_party=actor_party,
            )
        return outbox_id

    def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        stale_after_seconds: int = 300,
    ) -> list[OutboxRecord]:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                UPDATE outbox_events
                SET state = 'pending', locked_by = NULL, locked_at = NULL
                WHERE state = 'publishing'
                  AND locked_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
                """,
                (stale_after_seconds,),
            )
            rows = connection.execute(
                """
                WITH selected AS (
                    SELECT outbox_id
                    FROM outbox_events
                    WHERE state = 'pending' AND available_at <= CURRENT_TIMESTAMP
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE outbox_events AS event
                SET state = 'publishing', locked_by = %s, locked_at = CURRENT_TIMESTAMP,
                    attempts = attempts + 1
                FROM selected
                WHERE event.outbox_id = selected.outbox_id
                RETURNING event.outbox_id, event.queue_name, event.message_kind,
                          event.payload, event.attempts, event.created_at
                """,
                (limit, worker_id),
            ).fetchall()
        return [
            OutboxRecord(
                outbox_id=str(row["outbox_id"]),
                queue_name=str(row["queue_name"]),
                message_kind=str(row["message_kind"]),
                payload=dict(row["payload"]),
                attempts=int(row["attempts"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark_outbox_published(self, outbox_id: str, worker_id: str) -> None:
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE outbox_events
                SET state = 'published', published_at = CURRENT_TIMESTAMP,
                    locked_by = NULL, locked_at = NULL, last_error = NULL
                WHERE outbox_id = %s AND state = 'publishing' AND locked_by = %s
                RETURNING outbox_id
                """,
                (outbox_id, worker_id),
            ).fetchone()
            if row is None:
                raise StateConflict("outbox ownership was lost before publication acknowledgement")

    def mark_outbox_failed(
        self,
        outbox_id: str,
        worker_id: str,
        error: str,
        *,
        maximum_attempts: int,
        retry_delay_seconds: int,
    ) -> None:
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                UPDATE outbox_events
                SET state = CASE WHEN attempts >= %s THEN 'failed' ELSE 'pending' END,
                    available_at = CASE
                        WHEN attempts >= %s THEN available_at
                        ELSE CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                    END,
                    locked_by = NULL, locked_at = NULL, last_error = %s
                WHERE outbox_id = %s AND state = 'publishing' AND locked_by = %s
                RETURNING outbox_id
                """,
                (
                    maximum_attempts,
                    maximum_attempts,
                    retry_delay_seconds,
                    error[:4000],
                    outbox_id,
                    worker_id,
                ),
            ).fetchone()
            if row is None:
                raise StateConflict("outbox ownership was lost before failure recording")

    def register_workspace(self, workspace: WorkspaceRecord) -> None:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO workspaces (
                    workspace_id, milestone_id, task_id, owner_party, path,
                    repository_url, requested_ref, resolved_commit, status, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    workspace.workspace_id,
                    workspace.milestone_id,
                    workspace.task_id,
                    workspace.owner_party,
                    str(workspace.path),
                    workspace.repository_url,
                    workspace.requested_ref,
                    workspace.resolved_commit,
                    workspace.status,
                    workspace.created_at,
                ),
            )
            self._append_audit_on_connection(
                connection,
                stream=f"task:{workspace.task_id}",
                event_type="workspace.registered",
                payload=workspace.model_dump(mode="json"),
                actor_party=workspace.owner_party,
            )

    def register_evidence(self, manifest: EvidenceManifest, object_path: Path) -> None:
        with self._connection() as connection, connection.transaction():
            inserted = connection.execute(
                """
                INSERT INTO evidence_artifacts (
                    digest, algorithm, logical_name, media_type, byte_size, object_path,
                    manifest, signer_key_id, signature, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (digest) DO NOTHING
                RETURNING digest
                """,
                (
                    manifest.digest,
                    manifest.algorithm,
                    manifest.logical_name,
                    manifest.media_type,
                    manifest.byte_size,
                    str(object_path),
                    self._json(manifest.model_dump(mode="json")),
                    manifest.signature.key_id,
                    manifest.signature.signature_b64,
                    manifest.created_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT algorithm, logical_name, media_type, byte_size, object_path,
                           manifest, signer_key_id, signature
                    FROM evidence_artifacts
                    WHERE digest = %s
                    """,
                    (manifest.digest,),
                ).fetchone()
                expected_manifest = manifest.model_dump(mode="json")
                if (
                    existing is None
                    or str(existing["algorithm"]) != manifest.algorithm
                    or str(existing["logical_name"]) != manifest.logical_name
                    or str(existing["media_type"]) != manifest.media_type
                    or int(existing["byte_size"]) != manifest.byte_size
                    or str(existing["object_path"]) != str(object_path)
                    or dict(existing["manifest"]) != expected_manifest
                    or str(existing["signer_key_id"]) != manifest.signature.key_id
                    or str(existing["signature"]) != manifest.signature.signature_b64
                ):
                    raise StateConflict(
                        "existing evidence registration does not match the supplied manifest"
                    )
            self._append_audit_on_connection(
                connection,
                stream=f"evidence:{manifest.digest}",
                event_type=(
                    "evidence.registered" if inserted is not None else "evidence.reused"
                ),
                payload={
                    "digest": manifest.digest,
                    "logical_name": manifest.logical_name,
                    "media_type": manifest.media_type,
                    "byte_size": manifest.byte_size,
                    "signer_key_id": manifest.signature.key_id,
                },
                actor_party=None,
            )

    def record_gate_decision(
        self,
        milestone_id: str,
        decision: GateDecision,
        resulting_stop_reason: StopReason | None = None,
    ) -> str:
        payload = decision.model_dump(mode="json")
        digest_payload = {"milestone_id": milestone_id, "decision": payload}
        digest = hashlib.sha256(canonical_json(digest_payload)).hexdigest()
        decision_id = str(uuid4())
        with self._connection() as connection, connection.transaction():
            milestone_row = connection.execute(
                "SELECT milestone_id FROM milestones WHERE milestone_id = %s FOR UPDATE",
                (milestone_id,),
            ).fetchone()
            if milestone_row is None:
                raise KeyError(milestone_id)
            connection.execute(
                """
                INSERT INTO gate_decisions (
                    decision_id, milestone_id, gate, status, reviewer_party, subject_party,
                    evidence, findings, decision_digest
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    decision_id,
                    milestone_id,
                    decision.gate.value,
                    decision.status.value,
                    decision.reviewer_party,
                    decision.subject_party,
                    self._json(decision.evidence),
                    self._json(decision.findings),
                    digest,
                ),
            )
            if resulting_stop_reason is not None:
                stop_row = connection.execute(
                    "SELECT stop_reason FROM milestones WHERE milestone_id = %s",
                    (milestone_id,),
                ).fetchone()
                if (
                    stop_row is None
                    or str(stop_row["stop_reason"]) != resulting_stop_reason.value
                ):
                    raise StateConflict(
                        "database governance state disagrees with the governance engine"
                    )
            self._append_audit_on_connection(
                connection,
                stream=f"milestone:{milestone_id}",
                event_type="governance.gate_decision",
                payload={"decision_id": decision_id, "decision_digest": digest, **payload},
                actor_party=decision.reviewer_party,
            )
        return decision_id

    def record_policy_decision(
        self,
        *,
        milestone_id: str,
        task_id: str | None,
        workspace_id: str | None,
        actor_party: int,
        rule_id: str,
        allowed: bool,
        reason: str,
        request_digest: str,
    ) -> str:
        decision_id = str(uuid4())
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO policy_decisions (
                    policy_decision_id, milestone_id, task_id, workspace_id, actor_party,
                    rule_id, allowed, reason, request_digest
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    decision_id,
                    milestone_id,
                    task_id,
                    workspace_id,
                    actor_party,
                    rule_id,
                    allowed,
                    reason,
                    request_digest,
                ),
            )
            self._append_audit_on_connection(
                connection,
                stream=f"task:{task_id}" if task_id else f"milestone:{milestone_id}",
                event_type="tool.policy_decision",
                payload={
                    "policy_decision_id": decision_id,
                    "workspace_id": workspace_id,
                    "rule_id": rule_id,
                    "allowed": allowed,
                    "reason": reason,
                    "request_digest": request_digest,
                },
                actor_party=actor_party,
            )
        return decision_id

    def append_audit(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        actor_party: int | None,
    ) -> AuditRecord:
        with self._connection() as connection, connection.transaction():
            return self._append_audit_on_connection(
                connection,
                stream=stream,
                event_type=event_type,
                payload=payload,
                actor_party=actor_party,
            )

    def iter_audit(self) -> Iterator[AuditRecord]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
            for row in rows:
                yield AuditRecord(
                    sequence=int(row["sequence"]),
                    event_id=str(row["event_id"]),
                    stream=str(row["stream"]),
                    event_type=str(row["event_type"]),
                    actor_party=int(row["actor_party"]) if row["actor_party"] is not None else None,
                    occurred_at=row["occurred_at"],
                    payload=dict(row["payload"]),
                    previous_hash=str(row["previous_hash"]),
                    event_hash=str(row["event_hash"]),
                    signature=SignatureEnvelope(
                        key_id=str(row["signer_key_id"]),
                        signature_b64=str(row["signature"]),
                    ),
                )
