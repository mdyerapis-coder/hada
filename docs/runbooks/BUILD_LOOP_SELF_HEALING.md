# Self-Healing Autonomous Build Loop

The build loop advances HADA in bounded cycles without sharing a mutable Git
checkout between cron runs. `scripts/ci/build_cycle_guard.py` is the deterministic
governance boundary around the reasoning agent.

## Failure modes closed

- **Concurrent cycles:** an atomic, token-bound lease permits one cycle at a
  time. A live lease returns exit 75. Expired leases are archived and recovered.
- **Shared-checkout races:** every cycle receives a unique worktree and branch
  pinned to the resolved `origin/main` SHA.
- **Stale merges:** verification and publishing both fetch and compare
  `origin/main` with the recorded base SHA. Movement quarantines the cycle.
- **Conflict artifacts:** anchored Git markers (`<<<<<<< `, exact `=======`,
  `>>>>>>> `) are scanned without matching decorative `# =====` comments.
- **Hidden regressions:** the default gate runs shell fast tests, Python
  compilation, and the complete Hermes CTL pytest suite.
- **Hangs:** Git, tests, and GitHub publication have bounded timeouts.
- **Partial/unreviewed publication:** publishing requires a clean committed
  change whose HEAD exactly matches the verified SHA. It can only open a draft
  PR; no merge operation exists.
- **Unsafe cleanup:** lease worktrees are removed only when their resolved path
  is exactly `<state>/worktrees/<token>`.

## Cycle protocol

```bash
# 1. Allocate the only active cycle and isolated worktree.
cycle=$(python3 scripts/ci/build_cycle_guard.py prepare \
  --repo /home/m_dyer_apis_gmail_com/hada --ttl 2700)
# Parse token/worktree/branch/base_sha from the JSON output.

# 2. In the returned worktree: select ONE roadmap item, implement, test, update
# docs, and commit. Never edit the shared checkout.

# 3. Run immutable-base and full regression gates.
python3 scripts/ci/build_cycle_guard.py verify --token "$token"

# 4. Publish the exact verified commit as a draft PR only.
python3 scripts/ci/build_cycle_guard.py publish --token "$token" \
  --title 'feat(scope): bounded change' --body-file /tmp/pr-body.md

# 5. Release and clean the isolated worktree.
python3 scripts/ci/build_cycle_guard.py release --token "$token" --status complete
```

On any failure, release with `--status quarantined` after preserving the error
in the cycle report. Do not rebase or resolve conflicts in place. A later cycle
starts cleanly from the new authoritative `origin/main`.

## Cron rules

- One bounded feature per tick; never “continue through multiple features.”
- Read current roadmap state from the pinned worktree, not stale skill examples.
- Do not merge, deploy, alter secrets/infra/governance, or modify the shared
  checkout.
- Maximum one draft PR per tick and three repair attempts per incident.
- Silent on active-lease contention; report quarantine, stale-lease recovery,
  auth/permission needs, and human product decisions to Instance Control.

## Verification

```bash
bash tests/ci/test_build_cycle_guard.sh
bash scripts/ci/run_fast_tests.sh
python3 -m py_compile scripts/ci/build_cycle_guard.py
shellcheck tests/ci/test_build_cycle_guard.sh
```

The hermetic test uses a local bare Git remote and stubbed `gh`. It proves lease
serialization, immutable SHA pinning, isolated worktrees, stale-base rejection,
conflict-marker rejection, bounded timeout, quarantine/recovery, path-safe
cleanup, and draft-only publication without network access.
