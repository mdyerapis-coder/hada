# map — how to walk

This shelf is a **system map** (ICM form 6): a record library of nouns, a short shelf of verbs, and a change-impact index. It exists so an editing agent can answer "what is X" and "what else moves" without reading the whole tree.

## The subject

`~/github/hada/workspace/deploy-v4/HADA-M1-durable-orchestrator/` — the live HADA source tree, per the repo's own root `README.md` ("Source of truth" section). `src/hada/` is the Python package; `pyproject.toml` there declares `hada = "hada.cli:app"`. Everything the repo root README calls "retained candidates, inspection copies, or immutable archives" is out of scope for object cards.

## Universes

- **live** — in force; implement and cite against these. Everything under `workspace/deploy-v4/HADA-M1-durable-orchestrator/src/hada/`.
- **leftover** — present but not the main path (`candidate/`, `releases/`, `archives/`, `workspace/deploy-v2/`, `workspace/deploy-v3/`, `workspace/inspection/`, `workspace/deploy-run-local/`, `workspace/deploy-staging/`).
- **ghost** — named/filed but not wired. None found as of this pass; if you find a stub, mark it here.

## Node types (closed set)

See `_meta/schema.md`. Cards are copied from `_templates/object.md` / `process.md`.

## Status of nouns

`map/objects/_index.md` — one line per noun, marked `stub | verified | stale`. A card is `verified` only with a date, commit, and citations.

## Change impact

`map/effects/CONTEXT.md` — if you are changing X, open these cards. First-order hits only.

## Rules

- Never hand-edit `map/AGENTS.md` or `map/routing.md` — they are byte-identical twins of `map/CLAUDE.md`.
- Do not create `processes/` or `effects/` cards for movements that do not actually run.
- If a card and source disagree, the code wins and the card says so.
- `scripts/check_hada_consistency.py` (repo root) is the repo's own tool for catching drift between the live tree and the leftover copies — read-only, hashes `pyproject.toml`/`Dockerfile` only.
