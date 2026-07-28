# ADR-0005: Transactional Outbox for Queue Publication

**Status:** Proposed

## Context

Writing task state to PostgreSQL and independently publishing to Valkey creates a dual-write failure: either operation can succeed alone.

## Decision

Scheduling inserts an outbox row in PostgreSQL. A publisher claims rows with `FOR UPDATE SKIP LOCKED`, publishes a stable message ID to Valkey Streams and marks the row published. Stale publication claims are recoverable. Failed publication is retried with bounded attempts.

## Consequences

Delivery is at-least-once, not exactly-once. Workers must record processed message IDs before applying non-idempotent effects. Queue duplication is acceptable; silent loss is not.
