from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from hada.audit.chain import AuditChain
from hada.crypto.signing import Ed25519Signer
from hada.db.migrate import MigrationRunner
from hada.db.postgres import PostgresStore
from hada.models import GateDecision, GateName, GateStatus, MilestoneState, StopReason
from hada.orchestrator.lifecycle import TaskRecord, TaskStatus
from hada.orchestrator.service import OrchestratorService
from hada.queue.broker import DurableQueue, QueueMessage, RedisStreamBackend

pytestmark = pytest.mark.integration


def _integration_environment() -> tuple[str, str]:
    dsn = os.environ.get("HADA_INTEGRATION_DSN")
    valkey_url = os.environ.get("HADA_INTEGRATION_VALKEY_URL")
    if not dsn or not valkey_url:
        pytest.skip("integration services are not configured")
    return dsn, valkey_url


def test_postgres_audit_and_valkey_round_trip(tmp_path: Path) -> None:
    dsn, valkey_url = _integration_environment()
    migration_directory = Path(__file__).parents[2] / "src" / "hada" / "db" / "migrations"
    MigrationRunner(dsn, migration_directory).apply()

    signer = Ed25519Signer.generate()
    store = PostgresStore(dsn, signer)
    suffix = uuid4().hex
    milestone = MilestoneState(
        milestone_id=f"M1-{suffix}",
        title="Durable orchestrator integration",
        scope=["database", "audit", "queue"],
        out_of_scope=["inference"],
    )
    store.create_milestone(milestone)
    task = TaskRecord(
        milestone_id=milestone.milestone_id,
        title="Integration task",
        description="Exercise state transitions",
        acceptance_criteria=["round trip succeeds"],
    )
    store.create_task(task)
    ready = task.transition(TaskStatus.READY, expected_version=0)
    store.save_task_transition(task, ready, actor_party=1)

    records = list(store.iter_audit())
    AuditChain.verify(records, signer.verifier())
    assert any(record.event_type == "task.transitioned" for record in records)

    backend = RedisStreamBackend(valkey_url)
    queue = DurableQueue(
        backend,
        namespace=f"hada-integration-{suffix}",
        consumer_group="workers",
        maximum_delivery_attempts=3,
        maximum_stream_length=100,
        visibility_timeout_seconds=60,
    )
    queue.enqueue(
        "party-1",
        QueueMessage(kind="task.dispatch", payload={"task_id": task.task_id}),
    )
    claimed = queue.claim("party-1", "worker-1", block_milliseconds=1000)
    assert claimed and claimed[0].message.payload["task_id"] == task.task_id
    queue.complete("party-1", claimed[0])


def _approved_gate(gate: GateName, *, reviewer_party: int = 2) -> GateDecision:
    return GateDecision(
        gate=gate,
        status=GateStatus.APPROVED,
        reviewer_party=reviewer_party,
        subject_party=1,
        evidence=["sha256:" + "d" * 64],
    )


def test_database_enforces_governance_and_immutability() -> None:
    dsn, _ = _integration_environment()
    migration_directory = Path(__file__).parents[2] / "src" / "hada" / "db" / "migrations"
    MigrationRunner(dsn, migration_directory).apply()

    import psycopg

    signer = Ed25519Signer.generate()
    store = PostgresStore(dsn, signer)
    service = OrchestratorService(store)
    suffix = uuid4().hex
    milestone_id = f"M1-governance-{suffix}"
    service.create_milestone(
        MilestoneState(
            milestone_id=milestone_id,
            title="Database governance enforcement",
            scope=["governance"],
            out_of_scope=["inference"],
        )
    )

    with pytest.raises(psycopg.errors.RaiseException):
        store.record_gate_decision(
            milestone_id,
            _approved_gate(GateName.EXTERNAL_REVIEW, reviewer_party=3),
        )

    for gate in (
        GateName.ARCHITECTURE,
        GateName.SECURITY,
        GateName.TEST,
        GateName.DOCUMENTATION,
        GateName.MILESTONE_REPORT,
    ):
        service.record_gate_decision(milestone_id, _approved_gate(gate))

    waiting = store.get_milestone(milestone_id)
    assert waiting.stop_reason == StopReason.EXTERNAL_REVIEW_REQUIRED
    service.record_gate_decision(
        milestone_id,
        _approved_gate(GateName.EXTERNAL_REVIEW, reviewer_party=3),
    )
    completed = store.get_milestone(milestone_id)
    assert completed.stop_reason == StopReason.MILESTONE_COMPLETE

    with psycopg.connect(dsn) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            with connection.transaction():
                connection.execute(
                    "UPDATE audit_events SET event_type = 'tampered' WHERE sequence = 1"
                )

        with pytest.raises(psycopg.errors.RaiseException):
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, stream, event_type, actor_party, occurred_at, payload,
                        previous_hash, event_hash, signer_key_id, signature
                    ) VALUES (%s, 'attack', 'chain.break', 1, CURRENT_TIMESTAMP, '{}'::jsonb,
                              %s, %s, 'attacker-key-id', 'invalid-signature')
                    """,
                    (str(uuid4()), "0" * 64, "f" * 64),
                )
