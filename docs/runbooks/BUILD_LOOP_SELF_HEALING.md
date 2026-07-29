# Self-Healing Autonomous Build Loop

> **One lease → one immutable base → one isolated worktree → one bounded change
> → one complete gate → at most one draft PR → stop.**

`scripts/ci/build_cycle_guard.py` is the deterministic boundary around the
reasoning agent. Autonomous work never runs in a shared checkout.

## Safety contract

| Risk | Fail-closed control |
|---|---|
| Concurrent cycles | Token-bound singleton lease plus non-blocking controller lock |
| Abandoned cycle | PID/start-time ownership, heartbeat grace and explicit recovery |
| Shared checkout damage | Controller-owned bare mirror and isolated run worktree |
| Moving `main` | Immutable recorded SHA checked before/after tests and after push |
| Conflict damage | Unmerged-index, merge-commit and anchored marker rejection |
| Hidden regression | One central `full_green_gate.sh`, shared by local verification and CI |
| Partial publication | Hashed gate evidence and exact verified HEAD binding |
| Duplicate PR | Existing branch PR lookup makes publication idempotent |
| Unsafe cleanup | Run, mirror, worktree and archive paths are validated before deletion |
| Autonomous impact | Draft PR only; no merge, deploy, rebase, force-push or secret mutation |

## State layout

```text
${XDG_STATE_HOME:-$HOME/.local/state}/hada-build/
├── guard.lock
├── lease.json
├── repository.git/                 # controller-owned bare mirror
├── runs/<run-id>/
│   ├── manifest.json
│   ├── full-gate.log
│   └── worktree/
├── history/<run-id>/
└── quarantine/<run-id>/
```

The manifest binds `run_id`, a 256-bit token, host, owner PID and PID start time,
heartbeat, immutable base SHA, explicit path allowlist, branch, worktree, verified
head and gate-log hash.
State writes use temporary files, file `fsync`, atomic replacement and directory
`fsync`. Corrupt or incomplete state is a hard stop.

## Cycle protocol

```bash
# The wrapper process remains alive for the cycle; pass its PID explicitly.
cycle=$(python3 scripts/ci/build_cycle_guard.py prepare \
  --repo /home/m_dyer_apis_gmail_com/hada \
  --allow-path 'candidate/phase2-hermes-ctl/hermes_ctl/**' \
  --allow-path 'candidate/phase2-hermes-ctl/tests/**' \
  --owner-pid "$$")
# Parse run_id, token, worktree, branch and base_sha from JSON.

# Work only inside the returned worktree and allowlisted paths. Select ONE ready
# roadmap item, commit it.

python3 scripts/ci/build_cycle_guard.py heartbeat --token "$token"
python3 scripts/ci/build_cycle_guard.py verify --token "$token"
python3 scripts/ci/build_cycle_guard.py heartbeat --token "$token"
python3 scripts/ci/build_cycle_guard.py publish --token "$token" \
  --title 'feat(scope): bounded change' --body-file /tmp/pr-body.md
python3 scripts/ci/build_cycle_guard.py release \
  --token "$token" --status complete
```

Read-only health:

```bash
python3 scripts/ci/build_cycle_guard.py status
```

Dead-owner recovery:

```bash
python3 scripts/ci/build_cycle_guard.py recover
```

A live local PID is never stolen solely because TTL elapsed. Recovery requires a
dead owner and expired heartbeat, or a terminal/quarantined state. Recovery
archives metadata and changed-file evidence before cleanup.

Every cycle requires one or more `--allow-path` Git globs. Verification compares
the immutable base with the candidate using rename detection disabled, so both
the source and destination of a rename must be allowlisted. Any out-of-scope
addition, edit, deletion or rename quarantines the cycle before the quality gate.

## Complete green gate

`scripts/ci/full_green_gate.sh` is the single source of truth used by both the
build controller and `.github/workflows/verify.yml`. Missing tools are fatal.
It runs:

1. clean committed-candidate and `git diff --check` checks;
2. anchored conflict-marker and unmerged-index scans;
3. `bash -n` and required ShellCheck over tracked shell scripts;
4. operator-path, autonomous guardrail and release-manifest checks;
5. fast shell tests and all Phase B local-only gates;
6. Hermes CTL compile plus its complete pytest suite;
7. durable orchestrator Ruff, strict mypy and non-integration pytest under
   Python 3.12 through `uv`;
8. final clean-worktree verification.

Generated `.ci-evidence` files are restored before the clean-worktree check.
The build guard hashes the resulting gate log and verifies that hash immediately
before publication.

## Publication boundary

`publish` is the only stage that may push or call `gh pr create`. It:

1. revalidates base, branch, merge-base, markers, clean state and exact HEAD;
2. verifies the stored gate-evidence hash;
3. pushes without force;
4. fetches and checks `origin/main` again;
5. reuses an existing PR for the cycle branch or creates one draft PR;
6. reads the PR back and proves draft state plus correct head/base;
7. embeds run/base/head provenance in a hidden PR-body marker.

No autonomous merge, auto-merge, rebase, force-push, deployment, secret,
infrastructure, governance or authentication-broadening operation is allowed.

## Cron rules

- One bounded task and zero or one draft PR per tick; then stop.
- Read the current roadmap from the pinned worktree.
- Active contention is silent and healthy.
- Report quarantine, stale/dead-owner recovery, auth/permission failures and real
  human decisions to Instance Control.
- Keep the cron paused until this controller is merged, independently approved,
  rebased onto healthy `main`, and proven by one audit-only dry run.

## Verification

```bash
bash tests/ci/test_full_green_gate.sh
bash tests/ci/test_build_cycle_guard.sh
python3 -m py_compile scripts/ci/build_cycle_guard.py \
  scripts/ci/reject_conflict_artifacts.py
shellcheck scripts/ci/full_green_gate.sh \
  tests/ci/test_build_cycle_guard.sh tests/ci/test_full_green_gate.sh
bash scripts/ci/full_green_gate.sh
```
