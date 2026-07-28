# HADA Master Roadmap
Version: 1.0
Status: Living Document
Owner: HADA (Hermes Autonomous Development Appliance)

---

# Vision

HADA exists to become a governed autonomous software engineering appliance capable of safely designing, implementing, verifying, documenting, maintaining, and continuously improving the Hermes ecosystem while operating within strict governance boundaries.

HADA should progressively reduce the need for human intervention by autonomously selecting, implementing, validating, and documenting roadmap items while preserving human approval for high-impact decisions.

---

# Core Objectives

1. Govern all autonomous development.
2. Maintain engineering quality.
3. Preserve complete auditability.
4. Produce reproducible evidence.
5. Prioritise security over speed.
6. Never bypass governance.
7. Progress continuously until roadmap completion.

---

# Permanent Rules

HADA must NEVER:

- Merge directly into protected branches.
- Deploy to production.
- Modify secrets or credentials.
- Alter infrastructure without approval.
- Disable tests.
- Remove security controls.
- Rewrite unrelated code.
- Hide failures.
- Falsify evidence.

HADA SHOULD:

- Prefer the smallest safe change.
- Leave every task in a better state.
- Produce evidence for every decision.
- Continuously improve documentation.
- Reduce technical debt whenever practical.

---

# Phase 0 -- Governance Foundation

## Objective

Build the governance framework that allows autonomous software engineering to occur safely.

## Deliverables

- Governance architecture
- Engineering handbook
- Security policies
- Development lifecycle
- RFC process
- ADR framework
- Coding standards
- Testing standards
- Evidence standards
- Audit logging
- Release governance
- Project dashboard

## Definition of Done

HADA is capable of supervising engineering work safely.

---

# Phase 1 -- Autonomous Engineering

## Objective

Allow HADA to engineer software with minimal supervision.

## Deliverables

- GitHub integration
- CI monitoring
- Autonomous failure diagnosis
- Autonomous repository inspection
- Autonomous repair
- Local verification
- Regression detection
- Evidence generation
- Documentation updates
- Draft PR generation
- Continuous roadmap tracking

## Definition of Done

HADA can autonomously:

- Detect failures
- Diagnose failures
- Implement repairs
- Verify repairs
- Document changes
- Produce evidence
- Open governed draft pull requests

without human prompting.

---

# Phase 2 -- Hermes CTL

## Objective

Build the personal AI operating environment.

## Core Systems

### Identity

- User profile
- Preferences
- Context

### Memory

- Long-term memory
- Working memory
- Knowledge graph

### Communications

- Email
- SMS
- Telegram
- Contacts

### Productivity

- Calendar
- Tasks
- Notes
- CRM

### Information

- Files
- Search
- Knowledge management

### Intelligence

- Local LLM routing
- Cloud fallback
- Voice interface
- Mobile interface

## Definition of Done

Hermes CTL functions as a complete personal AI operating system.

---

# Phase 3 -- Personal Intelligence

## Objective

Enable proactive assistance.

## Features

- Daily briefing ✅ (Cycle 17: Dream-style briefing engine, merged)
- Planning ✅ (Cycle 20: daily plan generation, merged)
- Smart reminders ✅ (Cycle 22: reminders from daily plan, merged)
- Context awareness ✅ (PR #25 — draft, mergeable, CI green)
- Long-term memory curation ✅ (PR #26 — draft, mergeable, CI green)
- Relationship management ✅ (PR #27 — draft, mergeable, CI green)
- Shopping intelligence ✅ (PR #28 — draft, mergeable, CI green)
- Travel planning ✅ (PR #29 — draft, mergeable, CI green)
- Health tracking ✅ (PR #30 — draft, mergeable, CI green)
- Habit tracking ✅ (PR #31 — draft, mergeable, CI green)
- Financial awareness ✅ (PR #32 — draft, mergeable, CI green)

## Definition of Done

Hermes proactively assists without requiring continual prompting.

---

# Phase 4 -- Home Hub Integration

## Objective

Integrate household services while maintaining project separation.

Implementation remains external to HADA and is governed through review and evidence.

## Integrations

- Shopping
- Inventory
- Pantry
- Calendar
- Family tasks
- Smart home
- Cameras
- Notifications
- Dashboards
- Household automation

## Definition of Done

Home Hub integrates cleanly through governed interfaces.

---

# Phase 5 -- Financial Intelligence

## Objective

Develop governed financial assistance.

## Features

- Budget engine
- Spending analysis
- Savings planning
- Subscription management
- Invoice OCR
- Bill reminders
- Investment tracking
- Tax preparation support
- Wise integration
- Transaction reconciliation

## Definition of Done

Hermes provides accurate financial guidance while maintaining human control over money movement.

---

# Phase 6 -- Infrastructure

## Objective

Operate primarily from local infrastructure with optional burst compute.

## Deliverables

- Local inference
- GPU scheduling
- Kubernetes
- Vast.ai burst compute
- RunPod burst compute
- Backup automation
- Monitoring
- Secret management
- Disaster recovery
- High availability

## Definition of Done

Hermes operates reliably from local infrastructure with governed cloud augmentation.

---

# Phase 7 -- ADHD OS

## Objective

Develop ADHD OS as a separate product.

## Features

- Executive function tools
- Routine management
- Visual task planning
- Motivation systems
- Privacy-first architecture
- Consent framework
- Offline capability
- Cross-platform support

## Definition of Done

ADHD OS is independently deployable while remaining interoperable with Hermes.

---

# Phase 8 -- Continuous Improvement

## Objective

Never stop improving the ecosystem.

## Continuous Responsibilities

- Code review
- Refactoring
- Technical debt reduction
- Documentation improvements
- Test improvements
- Dependency updates
- Security improvements
- Performance optimisation
- Model benchmarking
- Tool evaluation
- Architecture review

---

# Autonomous Development Cycle

For every iteration HADA shall:

1. Review roadmap.
2. Identify highest-priority unfinished task.
3. Verify prerequisites.
4. Implement one bounded change.
5. Run local verification.
6. Generate evidence.
7. Update documentation.
8. Commit changes.
9. Push feature branch.
10. Open or update draft PR.
11. Record progress.
12. Repeat with the next highest-priority task.

---

# Human Approval Boundary

Human approval is permanently required for:

- Production deployments
- Merges into protected branches
- Infrastructure changes
- Secret management
- Financial operations
- Security policy changes
- Architectural decisions with ecosystem-wide impact

---

# Definition of Finalisation

HADA is considered complete when it can autonomously:

- Govern its engineering lifecycle.
- Plan work directly from this roadmap.
- Implement bounded features.
- Verify all work locally.
- Produce complete evidence.
- Maintain documentation automatically.
- Create governed draft pull requests.
- Continuously improve Hermes CTL and associated projects.
- Escalate only decisions requiring human judgement.

Completion does not signify the end of development. Instead, it marks the transition from building HADA to allowing HADA to continuously evolve the Hermes ecosystem under governed human oversight.

---

# Current Status (auto-maintained)

> Maintained by the autonomous build loop. Reflects verified, merged, or
> draft-PR state as of the last cycle. Deployment (Phase B0) remains
> human-authorized and is never executed autonomously.

## Phase 2 — Hermes CTL (personal AI operating environment)

**Foundation complete; deployable surface in progress (Cycles 6–13).** All six
Phase 2 foundation blocks delivered as a stdlib-only, offline-verifiable Python
package under `candidate/phase2-hermes-ctl/hermes_ctl/`. Phase 2 is MERGED to
`main` (PR #13) + unified contact daemon deployed (PR #13 follow-up, commit
aaa0067) + `hermesctl` CLI drafted (PR #15). 57 unit tests passing:

1. Memory ✅ — `MemoryStore` (long-term facts+tags+TTL, working memory,
   typed knowledge graph, JSON persistence).
2. Identity ✅ — `Identity` (profile / preferences / volatile context).
3. Communications ✅ — `Message` / `Channel` (ABC seam) / `LocalChannel`
   (offline) / `Directory` (contacts). Real Email/SMS/Telegram transports
   are deferred (network + secrets — governance boundary).
4. Productivity ✅ — Tasks / Notes / Calendar / CRM on MemoryStore.
5. Information ✅ — FileIndex / SearchIndex / KnowledgeBase.
6. Intelligence ✅ (interface) — `Brain` / `Router` / `LocalRouter`
   (rule-based, offline). Real LLM routing + cloud fallback deferred to
   Phase 6 (Infrastructure) — requires the running inference stack + creds
   (Human Approval Boundary).

**Boundary:** the six foundation blocks are complete and verified (57 unit
tests). Inbound SMS is LIVE via the deployed unified contact daemon (Sms
Forwarder app -> webhook receiver -> MemoryStore inbox). The `hermesctl` CLI
exposes memory/identity/inbox/tasks offline. Live Telegram/Email send + model
inference remain gated human work (creds / running inference stack — Human
Approval Boundary). ADR 0003 (Hermes CTL architecture) Accepted.

Build loop continues with gated integration cycles as authorized.

## Phase 3 — Personal Intelligence (proactive assistance)

**All 11 features delivered as governed draft PRs.** Each feature follows the established 5-layer pattern (dataclass → scan → deliver → CLI → tests). The three core features (briefing, planning, smart reminders) are MERGED to `main` and deployed to `hada-control` as systemd timer-driven services (07:00/07:30/08:00+2h AEST). The remaining 8 features are in draft PRs (#25–#32), each MERGEABLE with all CI checks passing.

| Feature | Status | Details |
|---------|--------|---------|
| Daily briefing | ✅ Merged | Cycle 17, PR #18/#19/#20 |
| Planning | ✅ Merged | Cycle 20–23, PR #20/#21/#22/#23 |
| Smart reminders | ✅ Merged | Cycle 22, PR #22 |
| Context awareness | ✅ Draft #25 | Real-time system state snapshot |
| Long-term memory curation | ✅ Draft #26 | Fact expiry/consolidation |
| Relationship management | ✅ Draft #27 | Contact/relationship tracking |
| Shopping intelligence | ✅ Draft #28 | Shopping list + history |
| Travel planning | ✅ Draft #29 | Trip/itinerary planner |
| Health tracking | ✅ Draft #30 | Metrics logging + summaries |
| Habit tracking | ✅ Draft #31 | Streaks, categories, due-today |
| Financial awareness | ✅ Draft #32 | Budget, expenses, spend analysis |

**Test suite:** 150+ unit tests across all Phase 3 modules, all CI ✅

**Integration gating:** All 8 draft features are wired behind the Hermes CTL communications seam. Live Telegram send + calendar/CRM sync + full LLM inference remain gated on human authorization (merge of draft PRs, then live creds/network per governance boundary).

**Next:** Awaiting human merge of draft PRs #25–#32. After merge, Phase 4+ begins (Home Hub Integration, Financial Intelligence, Infrastructure).

## Phase 1 — Autonomous Engineering (M1: HADA release appliance)

**Locally complete and verified.** The HADA M1 release appliance demonstrates
the full Phase 1 Definition of Done:

- GitHub integration + CI monitoring: `scripts/ci/autonomous_repair.sh --scan`
- Autonomous failure diagnosis + repair: `--continue` stage (hermetically tested)
- Local verification + regression detection: `scripts/ci/run_fast_tests.sh`,
  `workspace/tests/phase-b/run_all.sh` (19/19 in CI)
- Evidence generation: `scripts/ci/repair_evidence.sh`
- Documentation updates: ADR 0001 (Accepted), ADR 0002 (Accepted), this roadmap
- Draft PR generation: governed, never merged by the agent
- Continuous roadmap tracking: this file + `docs/PROGRESS.md`

Key merged/applied work (PRs against `mdyerapis-coder/hada`):
- #5 MERGED — governed autonomous repair pipeline + critical guardrail fix
  (secrets/`gh pr merge` were silently bypassing the scan; caught by a test,
  fixed, externally reviewed APPROVED).
- #6 draft — `ROADMAP.md` + ADR 0001 → Accepted.
- #7 draft — release-manifest gate regression test.
- #8 draft — hermetic `--continue` stage test.
- #9 draft — Phase-B local gate suite wired into `verify.yml` (CI green).
- #10 draft — this Master Roadmap (8-phase living document) + hermetic
  `--scan` stage test (closes full orchestrator coverage: scan → diagnose →
  continue → draft PR, verified end-to-end, no network).

All `verify.yml` checks pass in CI (ShellCheck, release manifests, fast tests,
Phase-B local suite, scan-stage test). `Self-contained E2E` also green.

**Outstanding (human decision):** Phase B0 deployment execution. The runner is
correct and proven by local tests; execution is gated on explicit human
authorization (see Human Approval Boundary).

## Phase 0 — Governance Foundation

Governance is operative: ADR framework, CI verification, guardrails
(`scripts/ci/repair_guardrails.sh`), audit logging (`.ci-evidence/`), and the
human approval boundary are all in place and enforced.

