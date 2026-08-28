---
type: object
universe: live
status: verified
date: 2026-08-26
commit: 14a1036
---

# Outbox publisher + runtime — outbox-pattern delivery loop

## Why this shape

Classic transactional-outbox pattern: task-state changes write an `OutboxRecord` in the same DB transaction as the state change (see `objects/orchestrator/orchestrator-service.md`), and a separate loop (`OutboxPublisher.publish_once`) claims and pushes those rows onto the durable queue. This decouples "the state change committed" from "the message is on the queue" so a crash between the two can't lose or duplicate a transition — the outbox row is retried, not the original mutation. `OrchestratorRuntime.run()` is the actual long-running process: it polls DB/queue health, republishes outbox rows, and exits code `70` after `unhealthy_exit_threshold` consecutive failed pings (so an orchestrator (systemd/supervisor) restarts it rather than spinning forever half-healthy).

## Shape

- `src/hada/orchestrator/outbox.py` — `OutboxRecord` (queue_name, message_kind, payload, attempts)
- `src/hada/orchestrator/publisher.py` — `OutboxPublisher.publish_once(limit=50)`: claims via `OutboxStore.claim_outbox`, enqueues each onto `DurableQueue`, marks published/failed
- `src/hada/runtime.py` — `OrchestratorRuntime.run()` (`runtime.py:88-127`): SIGTERM/SIGINT-aware loop, pings store+queue every `probe_interval_seconds`, calls `publisher.publish_once()` when healthy, exposes Prometheus counters (`hada_outbox_published_total`, `hada_outbox_publish_failures_total`) and an HTTP `/healthz` `/readyz` `/metrics` server (`ProbeServer`)

## Connected to

- owns: nothing persistent; reads/writes outbox rows through the injected `OutboxStore` (implemented by `PostgresStore`)
- owned-by: `hada.cli`'s `orchestrator run` command (`cli.py:201-229`), which is the only place `OrchestratorRuntime` is constructed
- joins: `objects/persistence/durable-queue.md` (`DurableQueue`/`RedisStreamBackend`), `objects/persistence/postgres-store.md` (the `OutboxStore` implementation)
- looks-like-but-is-not: `objects/orchestrator/orchestrator-service.md` — that layer creates outbox rows inside a transition; this layer only ever drains them

## If you change this

- Hits: `cli.py` `orchestrator run` (constructs `OutboxPublisher`/`OrchestratorRuntime`), `db/postgres.py` (`claim_outbox`/`mark_outbox_published`/`mark_outbox_failed`), `queue/broker.py` (`DurableQueue.enqueue`)
- Does not hit: `evidence/store.py`, `audit/chain.py`, `governance/engine.py` — this is pure transport, it never inspects gate/task semantics

## Surfaces

- long-running process started by `hada orchestrator run` (see `processes/orchestrator-run-loop.md`); `/healthz`, `/readyz`, `/metrics` HTTP endpoints for ops

## See

- `src/hada/runtime.py:88-127`
