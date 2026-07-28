# ADR-0003: PostgreSQL Is the Durable Source of Truth

**Status:** Proposed

## Context

Milestones, task transitions, gate decisions and evidence references must survive process, VM and queue failures.

## Decision

PostgreSQL stores all durable control-plane records. Valkey stores delivery state and renewable leases only. Database migrations are ordered, checksummed and protected by a PostgreSQL advisory lock.

## Consequences

Loss of Valkey does not erase governance state. PostgreSQL backup and recovery become critical operations. Schema changes require immutable migration files; changing an already applied migration checksum is a hard failure.
