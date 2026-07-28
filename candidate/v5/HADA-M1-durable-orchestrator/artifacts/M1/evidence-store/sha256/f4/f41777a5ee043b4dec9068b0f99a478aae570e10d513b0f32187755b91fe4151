# RFC-0002: Durable Orchestrator

**Status:** Proposed for M1 external review  
**Authors:** Party 1 implementation candidate  
**Review authority:** Party 2 internal review and Party 3 external review

## Problem

A governed autonomous development system cannot rely on prompt history, process memory or an in-memory queue. It requires durable state, non-repudiable evidence, bounded work ownership, idempotent delivery, explicit task transitions and an execution boundary that treats every agent request as untrusted.

## Decision

HADA uses PostgreSQL as the source of truth and Valkey only for disposable delivery and renewable leases. Every durable mutation that affects governance, tasks, evidence, workspaces or policy is represented in PostgreSQL. Queue publication originates from a transactional outbox so a committed task cannot be silently lost if Valkey is unavailable.

Audit records form one global SHA-256 hash chain. Each event hash is signed with an appliance Ed25519 key. PostgreSQL serialises insertions, verifies the supplied previous hash and assigns the next sequence inside a trigger. Evidence objects are stored by SHA-256 digest and accompanied by a signed canonical manifest. Gate decisions and policy decisions are immutable at the database layer.

Task updates use optimistic versions. The lifecycle rejects impossible state transitions. Party 3 cannot mutate task state. Internal completion or rejection from `awaiting_review` requires Party 2.

Git workspaces are created as detached worktrees from a mirrored repository after origin policy validation. The resolved commit is recorded before execution begins.

Tool execution is fail-closed. Agent requests cannot select a shell, executable path or arbitrary environment. The broker validates the exact workspace, executable, subcommand, timeout and party. Execution uses `shell=False` and, where configured, a Bubblewrap namespace with no network and only the task workspace writable.

## Consistency model

- PostgreSQL transactions are authoritative.
- Audit insertion and the related durable record are committed in the same transaction.
- Outbox publication is at-least-once.
- Stable outbox IDs become queue message IDs so downstream workers can deduplicate.
- Valkey pending entries are reclaimed after a visibility timeout.
- Exhausted messages are moved to a durable dead-letter stream. Queue streams are not length-trimmed; acknowledged source entries are deleted explicitly.
- Leases are protected by random ownership tokens; only the owning token can renew or release.

## Failure behaviour

PostgreSQL unavailable: readiness fails, outbox publication stops and the runtime exits after the configured unhealthy threshold.

Valkey unavailable: durable state remains safe in PostgreSQL; the outbox remains pending and publication resumes after recovery.

Worker crash: the queue message remains pending and may be reclaimed after its visibility timeout. Its lease expires unless renewed.

Audit signing key unavailable: state-changing operations that require the signed audit path fail rather than committing an unsigned record.

Sandbox unavailable: tool execution is denied.

## Alternatives rejected

**Valkey as the state store:** rejected because eviction, operational resets and asynchronous persistence do not meet governance durability requirements.

**Direct database-to-queue dual writes:** rejected because either side may commit alone.

**Shell-based command broker:** rejected because quoting rules, expansion and inherited configuration broaden the execution surface.

**A shared mutable checkout:** rejected because tasks could overwrite or contaminate one another and review provenance would be ambiguous.

## Deferred work

M1 does not implement local inference, autonomous coding agents, Party 2 adversarial prompts, Party 3 decision import, backup automation, software-bill-of-material generation or image signing. These remain in later milestones.
