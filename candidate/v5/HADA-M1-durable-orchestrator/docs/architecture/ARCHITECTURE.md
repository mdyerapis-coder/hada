# HADA Architecture

## System boundary

HADA owns provisioning, inference, orchestration, governance, evidence, observability and bounded recovery. Hermesctl remains an external target repository. HADA may clone a configured revision into an isolated milestone workspace; it must not treat its own repository as the product repository.

## M1 component model

### Governance plane

The governance engine validates reviewer identity, prevents self-approval, requires evidence for approvals and computes stop conditions. PostgreSQL duplicates critical rules with check constraints so bypassing the Python API does not bypass governance.

### Durable state plane

PostgreSQL stores milestones, tasks, workspaces, gate decisions, policy decisions, evidence registrations, outbox rows, processed-message IDs and signed audit events. Migrations are ordered by numeric prefix, checksummed and serialised with an advisory lock.

### Delivery plane

Valkey Streams carries party queues. Consumer groups provide pending-entry tracking. Stale entries are reclaimed after a configured visibility timeout. Messages that reach the delivery limit are copied to a dead-letter stream before acknowledgement and deletion from the source stream. Active and dead-letter streams are not length-trimmed because trimming can discard pending or forensic records; successful source entries are explicitly acknowledged and deleted.

Renewable Valkey leases use `SET NX PX` and compare-and-renew/release Lua scripts. Possession of a lease name alone is insufficient; the random token must match.

### Evidence plane

Evidence bytes are addressed by SHA-256 under `/var/lib/hada/evidence/sha256/<prefix>/<digest>`. A canonical manifest records the digest, media type, size, logical name, metadata, timestamp and Ed25519 signature. PostgreSQL stores the manifest and immutable registration.

### Audit plane

The audit ledger is global and ordered. Each unsigned event includes the prior event hash. The event hash is SHA-256 over canonical JSON and is signed using the appliance Ed25519 key. The related state change and audit insertion occur in one PostgreSQL transaction.

### Workspace plane

A repository URL must pass host and scheme policy. HADA maintains a bare mirror under `/var/lib/hada/repositories`. Each task receives a detached Git worktree under `/var/lib/hada/workspaces/<milestone>/<task>` pinned to a resolved commit. Workspace metadata is stored separately as a read-only file and in PostgreSQL.

### Execution plane

The policy engine receives a typed request containing party, milestone, task, workspace, executable, arguments, working directory and timeout. It validates one exact workspace boundary and one configured tool rule. The executor uses `shell=False`, a closed environment, resource limits, bounded output and a Bubblewrap namespace. Networkless rules use `--unshare-all`; only configured read-only paths and the exact workspace are bound.

### Runtime and observability plane

The orchestrator runtime probes PostgreSQL and Valkey, publishes transactional-outbox rows and exposes:

- `/healthz` — process liveness;
- `/readyz` — PostgreSQL and Valkey readiness;
- `/metrics` — Prometheus metrics.

Prometheus alerts on database loss, queue loss and outbox publication failure. Grafana provisions a read-only HADA control-plane dashboard. Grafana Alloy reads Docker JSON logs from a read-only host mount and forwards them to Loki without access to the Docker socket. The systemd watchdog performs bounded Compose recovery, and systemd is configured not to restart it after recovery exhaustion.

## Trust boundaries

- Agent output is untrusted input.
- Repository content and tests are untrusted input.
- Tool requests require policy evaluation before execution.
- Secrets never enter prompts, command arguments, audit payloads or milestone reports.
- Party 1 cannot write an approving review decision.
- Party 2 cannot use Party 1 execution authority.
- Party 3 approval must originate outside HADA.
- The supervisor may restart services but may not mark gates approved, change scope or delete findings.
- Valkey is not trusted as durable state.

## Task lifecycle

```text
PROPOSED -> READY -> LEASED -> RUNNING -> AWAITING_REVIEW -> COMPLETED
     |         |         |         |              |
     +------> CANCELLED <-+------> FAILED <--------+
                                      |
                                      +----------> READY

AWAITING_REVIEW -> REJECTED -> READY
```

Party 1 performs execution transitions for Party 1 tasks. Party 2 decides `COMPLETED` or `REJECTED` from `AWAITING_REVIEW`. Party 3 cannot mutate task state.

## Milestone lifecycle

```text
PROPOSED
  -> ARCHITECTURE_APPROVED
  -> IMPLEMENTING
  -> INTERNAL_REVIEW
  -> EXTERNAL_REVIEW_REQUIRED
  -> COMPLETE
```

A rejected or blocked gate enters `HUMAN_INPUT_REQUIRED`. Critical security findings enter `CRITICAL_SECURITY_FINDING`. Repeated infrastructure failure enters `RECOVERY_EXHAUSTED`.

## Transaction boundaries

### State mutation and audit

The PostgreSQL transaction obtains the global audit advisory lock, reads the final hash, constructs and signs the next event, writes the durable state record and audit event, then commits both. A database trigger independently verifies `previous_hash` continuity and assigns a gapless sequence. A signing or continuity failure aborts the transaction.

### State mutation and queue publication

The state transaction inserts an outbox row. The outbox publisher later claims rows with `FOR UPDATE SKIP LOCKED`, emits a stable message ID to Valkey and marks the row published. A crash after queue publication but before acknowledgement may duplicate a message; it cannot silently lose the event.

## Network topology

```text
Internet
   |
 Caddy :80/:443
   |
 ingress network
   |
 Grafana
   |
 control network (internal)
   +-- Prometheus
   +-- Loki <- Grafana Alloy <- read-only Docker JSON logs
   +-- Orchestrator
   +-- PostgreSQL
   +-- Valkey
   +-- Node Exporter
```

Only Caddy publishes host ports. The control network is internal to Docker Compose.

## Recovery

Recovery is bounded and idempotent. The orchestrator exits after repeated dependency failure, allowing the systemd supervisor to restart the control plane. Pending outbox events remain in PostgreSQL. Pending stream messages remain reclaimable in Valkey. Expired leases become available to another worker.

The supervisor cannot change governance state, delete evidence, discard dead-letter messages, raise retry limits or rotate signing keys.

## M1 exclusions

- GPU discovery and inference service deployment;
- agent prompt protocols and context construction;
- autonomous Hermesctl implementation or review;
- external Party 3 decision import;
- backups, restore automation and disaster-recovery drills;
- image digest pinning, SBOM generation and image signing.
