from __future__ import annotations

import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from hada.db.postgres import PostgresStore
from hada.orchestrator.publisher import OutboxPublisher
from hada.queue.broker import DurableQueue


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
    ) -> None:
        self.host = host
        self.port = port
        self.health = health
        self.registry = registry
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        health = self.health
        registry = self.registry

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
                self._respond(HTTPStatus.NOT_FOUND, b"not found\n")

            def _respond(self, status: HTTPStatus, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
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
        self.probe_server = ProbeServer(listen_host, listen_port, self.health, self.registry)
        self._stop = threading.Event()

    def _request_stop(self, signum: int, frame: object) -> None:
        del signum, frame
        self._stop.set()

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
