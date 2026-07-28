# HADA Roadmap — M1 (Hermes Autonomous Development Appliance)

Status: `HADA_V4_LOCAL_GATE_PASS_AWAITING_PHASE_B0`

HADA M1 is a governed, self-verifying release appliance. The v4 candidate
passed all local gates. The remaining gate (Phase B0 execution) requires
explicit human authorization and is **never** performed automatically.

## Phases

| Phase | Goal | State |
|-------|------|-------|
| v1 → v4 candidates | Build + checksum-lock release archives | ✅ Done (v4 current) |
| Local verification gate | Reproducible CI checks on the candidate | ✅ Passed (V4) |
| Governed release pipeline (ADR 0001) | CI/CD, evidence packaging, manual deploy authority | ✅ Built + Accepted |
| Autonomous repair pipeline (ADR 0002) | Monitor PRs/CI, smallest-safe-fix, draft PR, stop | 🟡 In review (PR #5) |
| Phase B0 execution | Deploy candidate to target | ⛔ Blocked — human authorization required |
| Roadmap + status docs | This file; ADR 0001 promoted to Accepted | 🟡 In progress (this change) |

## Current release

- v4 candidate: `releases/v4/HADA-M1-gcp-candidate-v4.zip`
  SHA-256 `d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac`
- v3 preserved: SHA-256 `7d969ee44874837a584dcd3363dd4c72c0816fc46d3054300a896d0a37686204`

## Guardrails (immutable)

- Deployment remains non-mutating until staging rehearsal, workload identity,
  environment protection, and the approved executor are configured (ADR 0001).
- The autonomous repair pipeline may open draft PRs but **never merges,
  deploys, or edits secrets/infra/governance** (`scripts/ci/repair_guardrails.sh`).

## Buildable backlog (non-deployment)

- [x] Repair-pipeline test suite (guardrail + orchestrator) — PR #5.
- [x] Fix release-manifest CI gate (match real `*.sha256` names; repair corrupt v2 manifest) — PR #5.
- [ ] Roadmap + ADR 0001 status promotion — this change.
- [ ] (Out of scope) v3 B0 checksum-gate path-independence — requires editing
      `workspace/scripts/run-phase-b0-v3-preflight.sh` (deployment preflight);
      deferred per governance boundary.

## Blocked / awaiting human decision

- **Phase B0 execution** — requires explicit authorization; not automated.
- **GitHub `main` reconciliation** — PR #4 shows "merged" but its commit did
  not land on `main` (still the WIP commit). PR #5 carries the full pipeline
  and is the intended vehicle; `main` cleanup is a human decision.
