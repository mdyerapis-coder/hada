# HADA Master Roadmap

> **Plain-English purpose:** Build HADA safely, then use it to build and operate
> Hermes without allowing autonomous agents to merge, deploy, change secrets, or
> hide failures.

| Document | Value |
|---|---|
| **Status** | Living roadmap |
| **Owner** | HADA — Hermes Autonomous Development Appliance |
| **Last reviewed** | 29 July 2026 |
| **Detailed live evidence** | [Current status](#current-status--29-july-2026) |

## Start here

### The three active priorities

1. **Repair and certify Phase 3** — PR #35 must restore relationship behaviour
   and turn the broken `main` baseline green.
2. **Install the safe build loop** — PR #36 must serialize work in isolated
   worktrees and fail closed before automation resumes.
3. **Build the Android app next** — PR #37 makes the APK the primary household
   interface; dashboards remain admin/fallback tools.

### Roadmap at a glance

| Phase | Outcome | State | What it means now |
|---:|---|:---:|---|
| 0 | Governance foundation | ✅ Operational | Rules, evidence and approval boundaries exist. |
| 1 | Autonomous engineering | 🛠 Repairing | Build-loop controller is being replaced before resuming autonomy. |
| 2 | Hermes CTL | ✅ Foundation built | Core personal-AI services and APIs exist. |
| 3 | Personal intelligence | ⚠️ Stabilising | Features merged, but regression certification is blocked by PR #35. |
| 4 | Home Hub + Android APK | 🔵 Next | Native Android becomes the primary user interface. |
| 5 | Financial intelligence | ⚪ Planned | Governed finance assistance; no autonomous money movement. |
| 6 | Infrastructure | 🟡 Partial | Local/cloud inference exists; remaining resilience work is planned. |
| 7 | ADHD OS | ⚪ Planned | Separate ADHD-focused product interoperable with Hermes. |
| 8 | Continuous improvement | ♾ Ongoing | Review, security, tests, performance and maintenance never stop. |

**Legend:** ✅ operational · 🛠 active repair · ⚠️ blocked/stabilising · 🔵 next ·
🟡 partial · ⚪ planned · ♾ continuous

### Product surfaces

| Surface | Audience | Purpose | Long-term role |
|---|---|---|---|
| **Android APK** | Household users | Chat, household tools, notifications and approvals | **Primary interface** |
| **HADA Command Centre** | Operator/admin | Builds, repairs, evidence and governance | Admin only |
| **Home Hub web UI** | Household/admin | Browser compatibility and recovery | Fallback only |
| **Grafana** | Infrastructure operator | Metrics and operational observability | Admin only |

### Delivery path

`Stabilise Phase 3` → `Merge safe build loop` → `Resume one bounded cycle` →
`Build authenticated APIs` → `Build Android APK` → `Migrate household features`

> **Need detail?** Each phase below contains its objective, deliverables and a
> short definition of done. The bottom section records current engineering
> evidence and blockers.

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

# ✅ Phase 0 — Governance Foundation

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
- Engineering admin dashboard (operator-only; not the primary user interface)

## Definition of Done

HADA is capable of supervising engineering work safely.

---

# 🛠 Phase 1 — Autonomous Engineering

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

# ✅ Phase 2 — Hermes CTL

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
- Mobile application API seam

## Definition of Done

Hermes CTL functions as a complete personal AI operating system.

---

# ⚠️ Phase 3 — Personal Intelligence

## Objective

Enable proactive assistance.

> **Current gate:** Phase 3 features have been merged, but the phase is **not
> regression-certified**. Relationship/CLI repair PR #35 and a clean `main` test
> run must pass before this phase becomes ✅.

## Capability status

| Capability | State |
|---|:---:|
| Daily briefing, planning and smart reminders | ✅ Built |
| Context awareness and long-term memory | 🟠 Re-certify |
| Relationship management | 🛠 Repair PR #35 |
| Shopping, travel and health intelligence | 🟠 Re-certify |
| Habit tracking and financial awareness | 🟠 Re-certify |

## Definition of Done

Hermes proactively assists without requiring continual prompting.

---

# 🔵 Phase 4 — Home Hub + Android APK

## Objective

Integrate household services while maintaining project separation.

Implementation remains external to HADA and is governed through review and evidence.

## Product decision

> **The Android APK is the primary household and personal interface.** Web
> dashboards remain available only for administration, observability, recovery,
> or browser fallback.

### What goes where

| Capability | Primary surface | Notes |
|---|---|---|
| Chat, commands, reminders and approvals | Android APK | Main everyday experience |
| Shopping, inventory, pantry and calendar | Android APK | Migrated from Home Hub APIs |
| Family tasks, smart home, cameras and notifications | Android APK | Role-aware adult/child views |
| Build, repair and evidence status | HADA Command Centre | Operator/admin; selected status may appear read-only in APK |
| Infrastructure metrics | Grafana | Operator/admin only |
| Browser household controls | Home Hub web UI | Optional fallback |

All clients use versioned Hermes CTL / Home Hub APIs so authorization and
behaviour cannot silently diverge between app and web.

### Android MVP

- Kotlin + Jetpack Compose application
- Authenticated Hermes CTL / Home Hub API
- Chat, commands, reminders and explicit approval prompts
- Household views and governed engineering status
- Push notifications
- Offline read cache and idempotent queued actions
- Android Keystore-backed token storage; no embedded secrets
- Accessible, role-aware adult and child experiences
- CI-built debug APK
- Human-authorized signing for release APK/AAB

### Later integrations — not part of the initial APK

| Integration | Earliest safe form | Gate before expansion |
|---|---|---|
| SMS notifications | Inbound-only forwarder | Stable ingestion, deduplication and visible health |
| SMS replies | Suggested drafts requiring approval | Production evidence + accepted ADR |
| Automatic SMS replies | Restricted allowlisted automation | Separate explicit authorization + kill switch |
| Facebook / Messenger | Official Meta API adapter | Meta app review, privacy review and credentials |

<details>
<summary><strong>Safety rules for SMS and Meta integrations</strong></summary>

- The SMS notification listener forwards minimal encrypted events through the
  authenticated Hermes CTL ingestion seam. HADA remains a worker, not the
  personal contact receiver.
- Initial SMS forwarding does not read the SMS database, request `SEND_SMS`,
  reply, or originate messages. Notification capture is best-effort and must
  visibly report disabled, redacted, duplicated or suppressed events.
- Any future automatic reply mode needs recipient allowlists, confidence
  thresholds, rate limits, loop prevention, quiet-hours policy, immutable audit
  records and an immediate kill switch.
- OTPs, financial/legal/medical content, emergencies, unknown senders and
  ambiguous intent must never receive an automatic reply.
- Facebook and Messenger use official Meta APIs, OAuth, verified webhooks,
  scoped/revocable tokens, rate-limit handling and explicit retention controls.
  No scraping, credential sharing or direct Meta access from the APK.

</details>

### Delivery stages

| Stage | Deliverable | Release band |
|---:|---|:---:|
| 1 | API contract and authentication seam | MVP |
| 2 | Compose shell, navigation, accessibility and design system | MVP |
| 3 | Chat, controls, notifications and approval workflow | MVP |
| 4 | Household feature migration from Home Hub | MVP |
| 5 | Governed HADA engineering status | MVP |
| 6 | Offline behaviour, device security, E2E tests and packaging | MVP |
| 7 | Inbound-only SMS notification forwarder | Later |
| 8 | Facebook and Messenger adapter | Later |
| 9 | SMS reply drafts, then separately authorized automation | Deferred |

## Definition of Done

The Android APK is the primary household interface, both former dashboard
surfaces are integrated through shared governed APIs, and web dashboards are
limited to explicit admin/fallback use.

---

# ⚪ Phase 5 — Financial Intelligence

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

# 🟡 Phase 6 — Infrastructure

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

# ⚪ Phase 7 — ADHD OS

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

# ♾ Phase 8 — Continuous Improvement

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

> **One cycle = one bounded roadmap item and at most one draft PR. Then stop.**

| Step | Action | Fail-closed result |
|---:|---|---|
| 1 | Acquire the single build lease | If held/unavailable: do nothing |
| 2 | Pin the current `origin/main` SHA | If fetch/auth fails: quarantine |
| 3 | Create an isolated worktree | Never edit the shared checkout |
| 4 | Select one ready roadmap item | If prerequisites are missing: defer |
| 5 | Implement and document one bounded change | No unrelated work |
| 6 | Run marker, compile, targeted and full tests | Any failure blocks publication |
| 7 | Reject stale base or changed candidate SHA | Restart from a clean base later |
| 8 | Publish the exact verified SHA as a draft PR | Never merge or deploy |
| 9 | Record evidence and release the lease | Quarantine incomplete state |

A later scheduler tick may begin the next cycle only after the prior lease has
been safely released or quarantined.

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

# Current Status — 29 July 2026

> **Automation is paused.** HADA must not resume autonomous roadmap work until
> `main` is repaired and the replacement build loop is independently approved.

## Active engineering gates

| Item | Verified evidence | Gate to proceed |
|---|---|---|
| `main` baseline | **41 failed, 259 passed** in the last clean audit | Repair and re-run from a clean checkout |
| PR #35 — Phase 3 repair | **306 passed** on the repaired branch; historical relationship suites also pass | Fresh independent approval + green CI |
| PR #36 — safe build loop | Hermetic tests and GitHub CI green | Independent safety review, then merge after healthy `main` |
| PR #37 — Android roadmap | APK-first direction and dashboard roles documented | Review the latest roadmap/readability head |
| Autonomous build cron | Paused | Resume in audit-only mode after #35 and #36 are certified |

## Next safe sequence

1. Independently approve and merge the Phase 3 repair.
2. Prove `main` is green in a clean checkout.
3. Rebase and independently approve the build-loop guard.
4. Merge the readable APK-first roadmap.
5. Run one audit-only build cycle before enabling draft-PR creation.

## Stable foundations

- **Phase 0:** governance rules, evidence, guardrails and human approval boundary.
- **Phase 1:** CI monitoring, diagnosis, repair primitives and draft-PR workflow.
- **Phase 2:** memory, identity, communications, productivity, information and
  intelligence seams in Hermes CTL.

All deployment, protected-branch merge, infrastructure, secret, financial and
security-policy actions remain human-authorized boundaries.

