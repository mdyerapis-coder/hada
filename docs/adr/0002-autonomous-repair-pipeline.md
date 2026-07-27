# ADR 0002: Autonomous PR-repair pipeline

- Status: Accepted
- Date: 2026-07-28

## Context

HADA's governed release pipeline (ADR 0001) enforces manual authority for
deployment but leaves routine CI failures on PRs to be fixed by hand. Repeated
ShellCheck / test failures are low-risk, high-frequency, and safe to repair
automatically if the repair is bounded and never crosses governance boundaries.

## Decision

Adopt a governed autonomous repair pipeline (`scripts/ci/autonomous_repair.sh`)
that:

1. Monitors open PRs and detects failing CI checks.
2. Creates an isolated git worktree and diagnoses the failure (classification:
   shellcheck / test / build) from the failed-run logs.
3. Implements the **smallest safe fix** in the worktree.
4. Runs local verification: ShellCheck, `reject_operator_paths.sh`,
   manifest verification, fast tests, and any repo pytest suite.
5. Generates an audit report + evidence tarball (sha256).
6. Commits, pushes a `agent/autofix-pr-*` branch, and opens a **DRAFT** PR
   linked to the original.
7. **Stops for human approval** — it never merges, deploys, or alters branch
   protection.

Hard guardrails (`scripts/ci/repair_guardrails.sh`) reject any repair that
touches infrastructure, deployment, governance, or secret files, or that adds
merge/deploy/branch-protection operations. The guardrail scan runs before
commit and aborts the repair on violation.

## Consequences

- Low-risk CI failures are repaired without human toil, while deployment
  authority stays strictly manual (per ADR 0001).
- Every repair is auditable: diagnosis, diff, verification, and evidence are
  captured and linked from the draft PR.
- A draft PR (not an auto-merge) preserves the human approval gate.
- The pipeline refuses to act on failures it cannot verify locally.
