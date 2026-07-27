# ADR 0001: Governed release pipeline

- Status: Proposed
- Date: 2026-07-27

## Context

The v4 release archive passed manifest checks but its full E2E suite depended on operator-local Phase B0 evidence outside the archive. This prevented independent reproduction from an unrelated extraction directory.

## Decision

Adopt repository-native verification, clean-room E2E, durable evidence packaging, and a separate manual deployment-authority workflow. Deployment remains non-mutating until staging rehearsal, workload identity, environment protection, and the approved executor are configured.

## Consequences

- Release claims become reproducible in CI.
- Production authority remains separate from test success.
- Existing immutable candidates remain unchanged.
- A test fixture cannot substitute for production evidence.
