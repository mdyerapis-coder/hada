# HADA — system map
A walkable graph of the live HADA orchestrator so a cold agent can answer "what is X" and "what else moves if I change X" without slurping the tree. The subject tree is the source of truth; this map cites it (`path:line`).

## Universes

| Universe | Meaning |
|---|---|
| **live** | In force. Implement and cite against these. |
| **leftover** | Still present, no longer the main path. Touch only if that path is in scope. |
| **ghost** | Named or filed, not wired (stubs, dead types, docs of functions that do not exist). Do not implement against these. |

## Name collisions

Product language, repo layout, and package names disagree here more than usual — read this before opening a card.

| Product term | Code/file name |
|---|---|
| HADA (the product) | package `hada`, `workspace/deploy-v4/HADA-M1-durable-orchestrator/` |
| the orchestrator | `OrchestratorService` + `OrchestratorRuntime`, `src/hada/orchestrator/` |
| Party 1 / Party 2 / Party 3 | roles in `GateDecision`/`MilestoneState` (`models.py`) — 1 = implementer, 2 = internal reviewer, 3 = external reviewer. Not services or repos. |
| "the current release" per root README | `releases/v4/HADA-M1-gcp-candidate-v4.zip` — a **leftover** snapshot, not the live tree |
| `candidate/`, `workspace/inspection/`, `archives/`, `releases/`, `workspace/deploy-v2/`, `workspace/deploy-v3/`, `workspace/deploy-run-local/`, `workspace/deploy-staging/`, root `Claude Code OS (2.13).zip` | **leftover/ghost.** The repo's own root README declares the canonical active source is `workspace/deploy-v4/HADA-M1-durable-orchestrator/` only — these look like source trees but are retained candidates/inspection/archive copies |

## How to walk

1. Open `map/CLAUDE.md` (this file) — the L0 catalog.
2. Open `map/objects/_index.md` — one line per noun.
3. Open the object card for the noun you are changing.
4. Open `map/effects/CONTEXT.md` — what else moves.
5. For a running movement (not just a noun), check `map/processes/` first.

## Routing

| If you are changing | Open |
|---|---|
| task/milestone lifecycle, gates | `map/objects/orchestrator/`, `map/objects/governance/` |
| the outbox publish loop / runtime health | `map/objects/orchestrator/outbox-publisher.md`, `map/processes/orchestrator-run-loop.md` |
| sandboxed tool execution | `map/objects/governance/policy-broker.md` |
| Postgres schema / queue transport | `map/objects/persistence/` |
| evidence, audit log, signing | `map/objects/evidence-audit/` |
| CLI, workspace checkout | `map/objects/interfaces/` |
| anything | `map/effects/CONTEXT.md` first |

## Twins

`map/AGENTS.md` and `map/routing.md` are byte-identical twins of this catalog, generated for tools that ignore `CLAUDE.md`. Never hand-edit the twins; regenerate from `CLAUDE.md`.
