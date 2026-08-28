---
type: object
universe: live
status: verified
date: 2026-08-26
commit: 14a1036
---

# Orchestrator service — governed task/milestone lifecycle

## Why this shape

Enforces HADA's core governance rule in code, not just docs: Party 1 (implementer) may not approve its own work, execution transitions require the assigned party, and completion/rejection require Party 2. `GovernanceViolation` is raised, not silently ignored, on every rule breach. `TaskRecord.transition` uses optimistic concurrency (`expected_version`) so two workers can't race a task through the state machine.

## Shape

- `src/hada/orchestrator/service.py` — `OrchestratorService` (create_milestone, create_task, transition_task, schedule_task), `OrchestratorStore` protocol it depends on
- `src/hada/orchestrator/lifecycle.py` — `TaskStatus` enum (proposed → ready → leased → running → awaiting_review → completed/rejected/failed/cancelled), `_ALLOWED_TRANSITIONS` table, `TaskRecord.transition()`
- `src/hada/models.py` — `MilestoneState`, `GateDecision` (self-approval and evidence-required checks in `prevent_self_approval`, `models.py:36-41`), `StopReason`
- Party numbers are plain ints (1/2/3), constrained `ge=1, le=2` on `TaskRecord.assigned_party` and `ge=1, le=3` on reviewer/subject fields — not an enum, not a separate identity system

## Connected to

- owns: nothing persistent — `OrchestratorService` is stateless business logic over an injected `OrchestratorStore`
- owned-by: `src/hada/cli.py` (via `_store()`), and indirectly `db/postgres.py`'s `PostgresStore` (implements `OrchestratorStore`)
- joins: `objects/governance/governance-engine.md` (`GovernanceEngine` is the gate-decision half; this card is the task/milestone half — both live in `hada.governance`/`hada.orchestrator` and share `MilestoneState`/`StopReason`)
- looks-like-but-is-not: the outbox publish loop (`objects/orchestrator/outbox-publisher.md`) — this card only ever writes an outbox row via `enqueue_outbox`; it never touches the queue or Redis directly

## If you change this

- Hits: `db/postgres.py` (must implement any new `OrchestratorStore` method), `cli.py` (workspace/orchestrator Typer commands), `objects/governance/governance-engine.md` (shares `MilestoneState`/`StopReason`)
- Does not hit: `queue/broker.py`, `evidence/store.py`, `audit/chain.py` (this layer only enqueues outbox rows and records transitions; it never signs or publishes)

## Surfaces

- `hada.cli` Typer commands (`workspace create`, `orchestrator run` calls into a `PostgresStore` that implements this protocol)
- unit tests under `tests/unit`

## See

- `src/hada/orchestrator/service.py:45-145`
