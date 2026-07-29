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

- Daily briefing ✅ (Cycle 17: Dream-style briefing — fail-closed 4-category schema, MemoryStore delivery, CLI)
- Planning ✅ (Cycle 20: daily plan generation with LLM inference, CLI)
- Smart reminders ✅ (Cycle 22: scheduled reminders from daily plan, CLI)
- Context awareness ✅ (Cycle 23: recent interactions + open tasks + pending deliveries snapshot, CLI)
- Long-term memory ✅ (Cycle 24: curation — fact importance ranking, archival suggestions, consolidation, CLI)
- Relationship management ✅ (Cycle 25: Relationships class + interaction logging + important dates + CLI)
- Shopping intelligence ✅ (Cycle 26: shopping lists — items, purchase tracking, categories, CLI)
- Travel planning ✅ (Cycle 27: travel trip planning — destinations, dates, itineraries, CLI)
- Health tracking ✅ (Cycle 28: health metrics logging — sleep, water, exercise, weight, mood, CLI)
- Habit tracking ✅ (Cycle 29: habit tracking — streaks, categories, logs, due-today, CLI)
- Financial awareness ✅ (Cycle 30: budget tracking, expense logging, spend analysis, CLI)

## Definition of Done

Hermes proactively assists without requiring continual prompting.

---

# Phase 4 -- Home Hub Integration

## Objective

Integrate household services while maintaining project separation.

Implementation remains external to HADA and is governed through review and evidence.

## Architecture

See ADR 0004 (Proposed) for the three-layer integration pattern:
adapter (`hermes_ctl/integrations/`) → existing Hermes CTL seam
(MemoryStore/Channel/CLI) → external service.

## Integrations

|- Shopping ✅ (Phase 3)
|- Inventory ✅ (Cycle 33 — PR #43, household inventory module)
|- Pantry ✅ (Cycle 34 — PR #44, household pantry stock management)
|- Calendar 🔄 (Cycle 36 — active, household calendar module)
|- Family tasks ✅ (Cycle 35 — PR #46, family task management)
- Smart home
- Cameras
- Notifications
- Dashboards
- Household automation

## Definition of Done

Home Hub integrates cleanly through governed interfaces. At least one
Phase 4 adapter is delivered, verified, and reaches draft-PR state.

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

## Phase 3 — Personal Intelligence

**COMPLETE ✅ — All 11 features delivered, merged to `main` (PRs #20–#32).
Regression-certified (326 unit tests passing, clean conflict-artifact scan,
build loop verification gate green). Build loop now advances to Phase 4.**

## Phase 4 — Home Hub Integration

**In progress — Phase 4 integrations under development (Cycles 33–36).**
Foundation ADR 0004 accepted. Three draft PRs open for review:

- ✅ Inventory (Cycle 33, PR #43) — household inventory tracking module
- ✅ Pantry (Cycle 34, PR #44) — household pantry stock management
- ✅ Family tasks (Cycle 35, PR #46) — family task assignment and tracking
- 🔄 Calendar (Cycle 36, this PR) — household calendar event management

Remaining integrations (smart home, cameras, notifications, dashboards,
household automation) deferred — require hardware or infrastructure not yet
available in the build environment.

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

