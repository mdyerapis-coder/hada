# HADA Build Progress

Autonomous build loop log. Each cycle implements one bounded, verified change
on a feature branch, opens a draft PR, and records progress here. No merge,
deploy, secret/infra change, or governance bypass occurs.

## Cycle 1 — Repair-pipeline test suite + guardrail fix
- Branch: `agent/autofix-add-autonomous-repair-pipeline` (PR #5)
- Added `tests/ci/test_repair_pipeline.sh` (guardrail allow/deny + orchestrator
  contract); wired into `run_fast_tests.sh`.
- **Caught a critical guardrail bug**: the secret/merge content scan used
  `grep -v '^\+\+\+'` to strip diff headers, but GNU grep ERE treats `\+` as
  "1+", so `^\+\+\+` matched ANY `+` line — silently dropping secret/merge
  lines from the scan. Removed the filter. Secrets + `gh pr merge` now caught.
- Also fixed earlier: `verify_release_manifests.sh` pattern + corrupt v2 manifest.
- Verified: 7/7 repair tests pass; CI `Verify` + `E2E` green.
- Review: routed to agent-forge subagent (background).

## Cycle 2 — Roadmap + ADR 0001 status
- Branch: `agent/docs-roadmap-and-adr1-accepted` (PR this change)
- Created `ROADMAP.md` (explicit M1 phases, status, guardrails, backlog).
- Promoted `docs/adr/0001-governed-release-pipeline.md` Proposed → Accepted.
- Recorded progress (this file).

## Open / blocked
- Phase B0 deployment: human authorization required (not automated).
- PR #4 "merged" anomaly on `main`: PR #5 carries the full pipeline.
- v3 B0 checksum-gate path-independence: deferred (edits deploy preflight script).

## Cycle 6 — Phase 2 start: Hermes CTL memory foundation
- Branch: `agent/phase2-hermes-ctl-memory-foundation` (draft PR)
- Scaffolded `candidate/phase2-hermes-ctl/hermes_ctl/` (Phase 2 package).
- `MemoryStore`: long-term (facts + tags + TTL), working (session scratch),
  knowledge graph (typed nodes + directed edges). Stdlib-only; JSON-file
  persistence backend. No network/secrets/infra.
- Added `tests/test_memory_store.py` (8 tests: remember/recall/forget, TTL
  expiry, tag search, working-memory lifecycle, graph edges, JSON roundtrip,
  serialization). All pass.
- Added `docs/adr/0003-hermes-ctl-architecture.md` (Proposed).
- Verified: `pytest tests/` → 8 passed.
- Next bounded tasks (in order): Identity layer (user profile/prefs/context
  on MemoryStore), then Communications adapters, Productivity, Intelligence.

## Cycle 7 — Phase 2: Identity layer
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/identity/profile.py`: `Identity` built on `MemoryStore` —
  profile (merge fields), preferences (key/value + defaults), volatile context
  (working memory). Stdlib-only.
- Added `tests/test_identity.py` (5 tests: profile merge, prefs + default, key
  validation, volatile context, persistence). All pass.
- Verified: `pytest tests/` → 13 passed (8 memory + 5 identity).
- Next: Communications adapters (Email / SMS / Telegram / Contacts).

## Cycle 8 — Phase 2: Communications layer (foundation)
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/communications/channels.py`: `Message` (content-hashable),
  `Channel` (ABC transport seam), `LocalChannel` (offline in-memory transport,
  no network/credentials), `Directory` (contacts on MemoryStore).
- Real Email/SMS/Telegram transports intentionally NOT here — they need
  network + secrets (governance boundary). The `Channel` ABC is the seam
  they implement later, gated.
- Added `tests/test_communications.py` (5 tests). All pass.
- Verified: `pytest tests/` → 18 passed.
- Next: Productivity (Calendar / Tasks / Notes / CRM).

## Cycle 9 — Phase 2: Productivity layer
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/productivity/store.py`: TaskStore + NoteStore + Calendar
  (events, upcoming-window query) + CRM (entities), all on MemoryStore.
  Stdlib-only dataclasses + query logic.
- Added `tests/test_productivity.py` (5 tests). All pass.
- Verified: `pytest tests/` → 23 passed.
- Next: Information (Files / Search / Knowledge management).

## Cycle 10 — Phase 2: Information layer
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/information/index.py`: FileIndex (metadata + sha256,
  read-only scan), SearchIndex (inverted term index, AND-query), KnowledgeBase
  (thin wrapper over MemoryStore graph). Stdlib-only.
- Added `tests/test_information.py` (4 tests). All pass.
- Verified: `pytest tests/` → 27 passed.
- Next: Intelligence (local LLM routing / cloud fallback / voice / mobile).

## Cycle 11 — Phase 2: Intelligence layer (foundation + boundary)
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/intelligence/router.py`: `Brain` dataclass + `Router`
  (ABC) + `LocalRouter` (rule-based, offline, per-brain auth header seam).
  No live model calls; the real routing is the existing llmfit-gui service
  (external to this repo) which the Router can target via HTTP later.
- Added `tests/test_intelligence.py` (4 tests). All pass.
- Verified: `pytest tests/` → 31 passed.
- **Boundary reached**: real local LLM routing (loading GGUF, GPU/CPU
  scheduling) and cloud fallback require the running inference stack +
  credentials, which is Phase 6 (Infrastructure) and governed by the Human
  Approval Boundary. The Intelligence *interface* is complete and testable;
  wiring it to live models is a human-gated integration. Phase 2 foundation
  blocks (Memory, Identity, Communications, Productivity, Information,
  Intelligence interface) are all delivered and verified.

## Cycle 3 — Release-manifest gate regression test
- Branch: `agent/test-release-manifest-gate` (PR #7)
- Added `tests/ci/test_release_manifests.sh`: positive (real releases/ verifies)
  + two negative cases (corrupt checksum, missing-file reference both rejected).
- Wired into `run_fast_tests.sh`. 3/3 pass; ShellCheck clean.
- Guards the `*.sha256` pattern fix so the gate cannot silently regress.

## Cycle 4 — Hermetic test for --continue stage
- Branch: `agent/test-continue-stage` (PR #8)
- `tests/ci/test_continue_stage.sh` exercises `autonomous_repair.sh --continue`
  with a stubbed `gh` + local bare mirror (no network). Proves: happy path
  opens a DRAFT PR and never calls `gh pr merge`; guardrail abort opens no PR.
- Wired into `run_fast_tests.sh`. 5/5 pass; ShellCheck clean.
- Closes the verification gap on the only previously-untested stage (Stage B).

## Cycle 5 — Wire Phase B local suite into CI
- Branch: `agent/ci-phase-b-suite` (PR #9)
- `verify.yml` now runs `workspace/tests/phase-b/run_all.sh` (B0 evidence gate,
  Gate 0f, DEPLOY_EXECUTE=0 no-remote, all 10 phase gates) on every PR/push.
  Previously only `run_fast_tests.sh` ran, so the most important deployment
  gate tests were NOT exercised in CI.
- run_all.sh is local-only (mocked SSH, no docker daemon); 19/19 pass locally.
