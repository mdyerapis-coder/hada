# HADA Command Centre — Usage Guide

How to read and operate the HADA Command Centre: the read-only single pane of
glass for governed autonomous development.

> **Read-only by design.** This interface reports state. It does **not** merge,
> deploy, alter secrets, change infrastructure, or approve governance gates.
> If you need a write action, it happens through a separately governed,
> authenticated pipeline with explicit human confirmation — never from this UI.

## Opening the board

See `COMMAND_CENTRE_ACCESS.md` for connection methods (Tailscale
`http://100.77.108.35/hada-control/`, or IAP tunnel `http://localhost:8080/hada-control/`).

## The eight views

Use the sidebar to switch views. Each view is a semantic section; Tab/click
navigates.

### 1. Overview
The default landing view. Shows:
- **Metric tiles** — latest commit SHA (repository HEAD), open PRs, whether
  human approval is required (always "required"), and recent failing CI runs.
- **Current milestone** — strategic M1 status combined with the M1 tactical
  roadmap's Phase B0 (deploy) state. If B0 is blocked (human authorization
  required), the milestone is shown as **blocked**, honestly.
- **Role separation** — the three-party authority split (Implementation /
  Adversarial / External reviewer).
- **Governance path** — Plan → Implement → Review → Approve, none of which the
  board itself performs.

### 2. Roadmap
Renders **both** canonical roadmaps:
- **Strategic roadmap (M0–M8)** — parsed from `docs/MASTER_ROADMAP.md`. Each
  phase shows a status pill (active / complete / planned / blocked). No
  invented progress percentages.
- **M1 tactical roadmap** — parsed from `ROADMAP.md`: the phase table, current
  release archive, and immutable guardrails.

### 3. Development
- **Pull requests** — open/draft PRs with state, branch, and last-updated,
  linked to GitHub.
- **CI checks** — recent workflow runs with conclusion (success/failure) and
  branch, linked to GitHub.
- **Latest commit** — SHA, date, message.

### 4. Governance
- **Authority boundary** — explicit statement that the board is read-only.
- **ADRs** — architecture decision records with status (e.g. Accepted), linked
  to their repo paths.
- Human approval required / self-approval prohibited are always shown.

### 5. Evidence
- Commit and PR identifiers with timestamps and provenance.
- Integrity/signature status is shown as **"not yet exposed"** where the v5
  orchestrator does not yet publish signed evidence over HTTP. Unavailable data
  is never shown as verified.

### 6. Agents
The six roles (Supervisor, Planner, Implementer, Reviewer, Security reviewer,
Release authority) with current assignment, last activity, and explicitly
listed permitted/prohibited actions. Assignment/activity reflect the designed
authority model, not live per-agent telemetry (that surface is not yet
exposed by the orchestrator).

### 7. Infrastructure
Live service health from the orchestrator probe (`/hada-api/metrics`):
orchestrator, Postgres (DB up), Valkey (queue up). Only services HADA governs
or observes are listed. **No secrets, tokens, or sensitive host data** are
shown. If the probe is unreachable, the panel shows "unreachable" — never
"healthy".

### 8. Documentation
Navigable summaries of canonical repository Markdown (Architecture, Security,
Roadmap, Governed autonomy, Durable orchestrator, External review). Each summary
is clearly labelled as a **summary, not canonical text**, with a source path
link. Click a card to open the reader; the canonical file remains the source of
truth.

## Refresh

Click **Refresh** (top bar) to:
- Re-fetch `/hada-control/snapshot.json` (GitHub + roadmap state)
- Re-fetch the live orchestrator probe (`/hada-api/metrics`, `/healthz`)

The freshness banner updates from `snapshot.json`'s `generated_at`.

## Reading the status signals

- **Pills**: `ok`/`complete`/`active` (green), `warn`/`review`/`draft` (amber),
  `bad`/`blocked`/`failed` (red), `neutral`/`planned`/`unavailable` (grey).
- **Source banner** (top): `live` (healthy), `stale` (snapshot >30m old), or
  `error` (unreachable).
- **Execution state** pill: `READY — HEALTHY`, `DEGRADED`, or `INFRA UNREACHABLE`.

## Fail-closed behaviour (what you will see when data is missing)

The board never fabricates health. If a data source is unavailable:

- Missing/stale/unreachable snapshot → the affected panels show an explicit
  "Data unavailable" notice. The board does **not** show that state as healthy.
- Live infra probe unreachable → Infrastructure panel shows "unreachable", not
  green.
- Evidence not yet exposed by the orchestrator → shown as "not yet exposed",
  never as verified.

## What you CANNOT do here

- Merge or approve a PR.
- Deploy or rebuild the appliance.
- Edit secrets, infrastructure, or governance config.
- Silently approve a governance gate.
- Trigger an autonomous repair (that is a separate, governed pipeline — see
  `docs/runbooks/AUTONOMOUS_REPAIR.md`).

If you intend any of the above, it must go through the governed pipeline with
explicit human authorization.

## How the data is produced (for operators)

`scripts/control-board-snapshot.py` (run by an operator or CI) collects:
- GitHub state via `gh` (read-only) — PRs, CI runs, latest commit
- Both roadmaps parsed from canonical Markdown
- Emits `deploy/control-board/snapshot.json` (`is_fixture: false`)

The browser renders that snapshot plus the live orchestrator probe. Tests live
in `tests/control_board/test_snapshot.py` (roadmap parsing, status mapping,
stale handling, snapshot-shape validation).

## Links

- Access: `docs/COMMAND_CENTRE_ACCESS.md`
- Autonomous repair pipeline: `docs/runbooks/AUTONOMOUS_REPAIR.md`
- Roadmaps: `docs/MASTER_ROADMAP.md`, `ROADMAP.md`
- ADRs: `docs/adr/`
