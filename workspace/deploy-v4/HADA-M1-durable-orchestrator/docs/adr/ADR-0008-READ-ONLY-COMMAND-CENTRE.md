# ADR-0008: Begin the HADA Command Centre as a read-only bundled dashboard

**Status:** Accepted

## Context

Operators need a clear front door to HADA's task, governance, evidence and documentation state.
HADA does not yet expose a dashboard API, and deployment or approval controls would expand the
security boundary before their authentication, authorisation and audit contracts are defined.

Hermesctl already uses an inspectable dashboard made from packaged HTML, CSS and JavaScript. HADA
can share that visual language while remaining a separate product with separate authority.

## Decision

The first HADA Command Centre milestone is a bundled, read-only HTML, CSS and JavaScript dashboard.
It loads a repository-owned JSON snapshot and falls back to an embedded snapshot when opened
directly from disk. The initial snapshot explicitly reports `LOCAL_ONLY`, `READY_NOT_EXECUTED`, no
active tasks and the outstanding Party 3 external review.

The dashboard does not approve, cancel, retry, execute or deploy work. PostgreSQL remains the
authoritative runtime state; a future authenticated read model may replace the static snapshot after
its contract is approved.

## Consequences

- The dashboard is usable locally without a frontend build chain or remote services.
- Displayed status has a named source and cannot imply live execution when disconnected.
- HADA and Hermesctl remain separate even though their dashboards share a visual language.
- Mutating controls require a later ADR covering authentication, authorisation, audit and replay
  protection.
