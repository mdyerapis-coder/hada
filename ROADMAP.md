# HADA Roadmap — M1 (Hermes Autonomous Development Appliance)

Status: `HADA_M1_B0_EXECUTED`

HADA M1 is a governed, self-verifying release appliance. The v4 candidate
passed all local gates. Phase B0 execution (deploy candidate to target) was
authorized and completed on `hada-control`; the live appliance now runs the
merged `main` candidate with the operational Command Centre.

## Phases

| Phase | Goal | State |
|-------|------|-------|
| v1 → v4 candidates | Build + checksum-lock release archives | ✅ Done (v4 current) |
| Local verification gate | Reproducible CI checks on the candidate | ✅ Passed (V4) |
| Governed release pipeline (ADR 0001) | CI/CD, evidence packaging, manual deploy authority | ✅ Built + Accepted |
| Autonomous repair pipeline (ADR 0002) | Monitor PRs/CI, smallest-safe-fix, draft PR, stop | ✅ Built (PR #5 merged) |
| Phase B0 execution | Deploy candidate to target | ✅ Executed (authorized 2026-07-28) |
| Roadmap + status docs | This file; ADR 0001 promoted to Accepted | ✅ Done |

## Current release

- Live appliance tracks `main` (merged candidate): control board, read-only
  `/api/v1/state` (real tasks + governance gates), caddy on Tailscale + IAP.
- v4 candidate preserved: `releases/v4/HADA-M1-gcp-candidate-v4.zip`
  SHA-256 `d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac`
- v5 candidate: `releases/v5/HADA-M1-gcp-candidate-v5.zip` (sha256 verified)

## Guardrails (immutable)

- Deployment remains non-mutating until staging rehearsal, workload identity,
  environment protection, and the approved executor are configured (ADR 0001).
- The autonomous repair pipeline may open draft PRs but **never merges,
  deploys, or edits secrets/infra/governance** (`scripts/ci/repair_guardrails.sh`).

## Buildable backlog (non-deployment)

- [x] Repair-pipeline test suite (guardrail + orchestrator) — PR #5.
- [x] Fix release-manifest CI gate (match real `*.sha256` names; repair corrupt v2 manifest) — PR #5.
- [x] Roadmap + ADR 0001 status promotion — this change.
- [ ] (Out of scope) v3 B0 checksum-gate path-independence — requires editing
      `workspace/scripts/run-phase-b0-v3-preflight.sh` (deployment preflight);
      deferred per governance boundary.

## Blocked / awaiting human decision

- **GitHub `main` reconciliation** — PR #4 shows "merged" but its commit did
  not land on `main` (still the WIP commit). PR #5 carries the full pipeline
  and is the intended vehicle; `main` cleanup is a human decision.
