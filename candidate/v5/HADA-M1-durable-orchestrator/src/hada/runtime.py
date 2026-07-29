from __future__ import annotations

import logging
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from hada.db.postgres import PostgresStore
from hada.models import GovernanceConfig, MilestoneState
from hada.orchestrator.lifecycle import TaskStatus
from hada.orchestrator.publisher import OutboxPublisher
from hada.orchestrator.self_healing import (
    Incident,
    RepairClass,
    SelfHealingSupervisor,
)
from hada.orchestrator.service import OrchestratorService
from hada.queue.broker import DurableQueue

logger = logging.getLogger(__name__)


class RuntimeHealth:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._database = False
        self._queue = False

    def update(self, *, database: bool, queue: bool) -> None:
        with self._lock:
            self._database = database
            self._queue = queue

    def ready(self) -> bool:
        with self._lock:
            return self._database and self._queue

    def snapshot(self) -> tuple[bool, bool]:
        with self._lock:
            return self._database, self._queue


class ProbeServer:
    def __init__(
        self,
        host: str,
        port: int,
        health: RuntimeHealth,
        registry: CollectorRegistry,
        queue: DurableQueue | None = None,
        governance: GovernanceConfig | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.health = health
        self.registry = registry
        self.queue = queue
        self.governance = governance
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        health = self.health
        registry = self.registry
        queue = self.queue
        governance = self.governance

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/metrics":
                    body = generate_latest(registry)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/healthz":
                    self._respond(HTTPStatus.OK, b"ok\n")
                    return
                if self.path == "/readyz":
                    if health.ready():
                        self._respond(HTTPStatus.OK, b"ready\n")
                    else:
                        self._respond(HTTPStatus.SERVICE_UNAVAILABLE, b"not ready\n")
                    return
                if self.path == "/api/v1/state":
                    # Read-only aggregate state. Surfaces only what the v5
                    # orchestrator actually tracks; subsystems it does not yet
                    # model are reported available:false so clients fail closed.
                    db_up, q_up = health.snapshot()
                    state: dict[str, Any] = {
                        "schema_version": "1.0",
                        "is_fixture": False,
                        "health": "ready" if health.ready() else "degraded",
                        "database_up": db_up,
                        "queue_up": q_up,
                        "outbox_published_total": registry.get_sample_value(
                            "hada_outbox_published_total"
                        )
                        or 0,
                        "outbox_publish_failures_total": registry.get_sample_value(
                            "hada_outbox_publish_failures_total"
                        )
                        or 0,
                    }
                    # Real queue depth (no message bodies read).
                    if queue is not None:
                        qstats = queue.stats()
                        state["tasks"] = {
                            "available": True,
                            "queue": qstats["queue"],
                            "enqueued": qstats["enqueued"],
                            "pending": qstats["pending"],
                            "maximum_delivery_attempts": qstats["maximum_delivery_attempts"],
                        }
                    else:
                        state["tasks"] = {
                            "available": False,
                            "reason": "queue not wired to probe",
                        }
                    # Real governance policy (from loaded config).
                    if governance is not None:
                        g = governance
                        state["gates"] = {
                            "available": True,
                            "prohibit_self_approval": g.prohibit_self_approval,
                            "prohibit_scope_expansion": g.prohibit_scope_expansion,
                            "maximum_agent_iterations_per_gate": (
                                g.maximum_agent_iterations_per_gate
                            ),
                            "maximum_recovery_attempts": g.maximum_recovery_attempts,
                            "require_architecture_review": g.require_architecture_review,
                            "require_security_review": g.require_security_review,
                            "require_test_review": g.require_test_review,
                            "require_external_review": g.require_external_review,
                            "stop_on_critical_security_finding": (
                                g.stop_on_critical_security_finding
                            ),
                        }
                    else:
                        state["gates"] = {
                            "available": False,
                            "reason": "governance config not wired to probe",
                        }
                    state["evidence"] = {
                        "available": False,
                        "reason": "signed evidence bundles not yet exposed over HTTP",
                    }
                    self._respond_json(state)
                    return
                self._respond(HTTPStatus.NOT_FOUND, b"not found\n")

            def _respond(self, status: HTTPStatus, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _respond_json(self, payload: object) -> None:
                import json

                body = json.dumps(payload).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_string: str, *args: object) -> None:
                del format_string, args

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


class OrchestratorRuntime:
    def __init__(
        self,
        store: PostgresStore,
        queue: DurableQueue,
        publisher: OutboxPublisher,
        *,
        listen_host: str,
        listen_port: int,
        probe_interval_seconds: int,
        unhealthy_exit_threshold: int,
        governance: GovernanceConfig | None = None,
        healing_milestone_id: str | None = None,
        healing_maximum_attempts: int = 3,
    ) -> None:
        self.store = store
        self.queue = queue
        self.publisher = publisher
        self.probe_interval_seconds = probe_interval_seconds
        self.unhealthy_exit_threshold = unhealthy_exit_threshold
        self.health = RuntimeHealth()
        self.registry = CollectorRegistry()
        self.database_up = Gauge(
            "hada_database_up",
            "Whether PostgreSQL is reachable",
            registry=self.registry,
        )
        self.queue_up = Gauge(
            "hada_queue_up",
            "Whether Valkey is reachable",
            registry=self.registry,
        )
        self.outbox_published = Counter(
            "hada_outbox_published_total",
            "Outbox events published to Valkey",
            registry=self.registry,
        )
        self.outbox_failed = Counter(
            "hada_outbox_publish_failures_total",
            "Outbox publication failures",
            registry=self.registry,
        )
        self.probe_server = ProbeServer(
            listen_host,
            listen_port,
            self.health,
            self.registry,
            queue=self.queue,
            governance=governance,
        )
        self._stop = threading.Event()

        # Wire self-healing supervisor when a milestone is configured.
        self._supervisor: SelfHealingSupervisor | None = None
        if healing_milestone_id is not None:
            orchestrator_service = OrchestratorService(store)
            # Ensure the healing milestone exists.
            try:
                orchestrator_service.store.get_milestone(healing_milestone_id)
            except (KeyError, Exception):
                orchestrator_service.create_milestone(
                    MilestoneState(
                        milestone_id=healing_milestone_id,
                        title="Self-healing repairs",
                        scope=["automatic safe repairs"],
                        out_of_scope=["deploy", "secrets", "merge"],
                    )
                )
            self._supervisor = SelfHealingSupervisor(
                orchestrator_service,
                healing_milestone_id,
                maximum_attempts=healing_maximum_attempts,
            )
        else:
            self._supervisor = None

    def _request_stop(self, signum: int, frame: object) -> None:
        del signum, frame
        self._stop.set()

    def _check_failed_tasks(self) -> None:
        """Scan for recently failed tasks and auto-flag as repair incidents."""
        if self._supervisor is None:
            return
        try:
            failed = self.store.list_tasks_by_status(TaskStatus.FAILED, limit=20)
        except Exception:
            logger.exception("failed to query failed tasks for self-healing")
            return
        for task in failed:
            # Skip tasks that are already repair tasks — the supervisor
            # handles repair-task retries via the attempt-loop internally.
            if task.task_id.startswith("repair-"):
                continue
            incident = Incident(
                source="orchestrator.runtime",
                subject=task.task_id,
                error_class="task.failed",
                summary=task.title,
                repair_class=RepairClass.SOURCE_CODE,
                evidence=[
                    f"task_id:{task.task_id}",
                    f"milestone:{task.milestone_id}",
                ],
            )
            try:
                self._supervisor.flag_and_apply_worker(incident)
            except Exception:
                logger.exception(
                    "self-healing flag failed for task %s", task.task_id
                )

    def run(self) -> int:
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        previous_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        self.probe_server.start()
        consecutive_unhealthy = 0
        try:
            while not self._stop.is_set():
                database_ok = self.store.ping()
                queue_ok = self.queue.ping()
                self.health.update(database=database_ok, queue=queue_ok)
                self.database_up.set(1 if database_ok else 0)
                self.queue_up.set(1 if queue_ok else 0)

                if database_ok and queue_ok:
                    consecutive_unhealthy = 0
                    published, failed = self.publisher.publish_once()
                    self.outbox_published.inc(published)
                    self.outbox_failed.inc(failed)
                    self._check_failed_tasks()
                else:
                    consecutive_unhealthy += 1
                    if consecutive_unhealthy >= self.unhealthy_exit_threshold:
                        return 70
                self._stop.wait(self.probe_interval_seconds)
            return 0
        finally:
            self.probe_server.stop()
            signal.signal(signal.SIGTERM, previous_sigterm)
            signal.signal(signal.SIGINT, previous_sigint)
