# ADR 0003 — Hermes CTL Architecture (Phase 2)

- Status: Accepted
- Date: 2026-07-28
- Promoted: 2026-07-28 (after Cycles 6–11 delivered + verified, 31 tests)
- Phase: 2 (Hermes CTL — personal AI operating environment)
- Supersedes: —

## Context

Phase 1 (Autonomous Engineering) is complete and deployed (B0 executed).
Phase 2's objective is to build the personal AI operating environment —
the "Hermes CTL" surface that the rest of the ecosystem (Communications,
Productivity, Intelligence, etc.) sits on top of.

The roadmap lists broad subsystems (Identity, Memory, Communications,
Productivity, Information, Intelligence). No code exists yet for Phase 2.

## Decision

Build Hermes CTL as a **dependency-light Python package** (`hermes_ctl/`)
under `candidate/phase2-hermes-ctl/`, with the following constraints drawn
from the governance rules:

1. **Stdlib-only core.** No new runtime dependencies for the foundation
   modules (memory, identity). Keeps it runnable inside the governed
   orchestrator and trivially testable.
2. **Three-surface memory first.** `MemoryStore` provides long-term
   (durable facts + tags + TTL), working (session scratch), and a typed
   knowledge graph (nodes + directed edges). This is the substrate every
   other Phase 2 subsystem needs.
3. **No network / secrets / infra in foundation modules.** The memory
   store is pure data modelling. Integrations (Telegram, Email, Calendar)
   come later as separate, explicitly-gated modules.
4. **Pluggable persistence.** In-memory backend default; JSON-file backend
   provided. No database required to verify locally.
5. **Governed build loop.** Each cycle ships one bounded, tested change on
   a feature branch + draft PR. No merge/deploy/secret mutation.

## Alternatives considered

- **Full microservice per subsystem**: rejected — premature for a foundation;
  violates "smallest safe change" and adds infra the governance boundary
  restricts.
- **Adopt an external memory/vector DB now**: rejected — Phase 2 starts with
  structured memory; vector/semantic search can be added later as an
  Intelligence-subsystem concern without blocking Identity/Memory.

## Consequences

- Hermes CTL has a verifiable, dependency-free memory foundation.
- Subsequent subsystems (Identity, Communications, Productivity) can build
  on `MemoryStore` immediately.
- Local verification (pytest, stdlib) is cheap and CI-friendly.
- Draft PRs are opened per cycle; merges require human approval.

## Status

Proposed. Foundation module (`hermes_ctl/memory/store.py`) implemented with
8 passing unit tests. To be promoted to Accepted after human review.
