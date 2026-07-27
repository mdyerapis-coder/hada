# Runbook: Autonomous PR-Repair Pipeline

## What it does

`scripts/ci/autonomous_repair.sh` watches HADA PRs, repairs failing CI with the
smallest safe fix, and opens a **draft** PR for human approval. It never
merges, deploys, or edits secrets/infra/governance.

## Modes

### Scan (discovery)

```bash
scripts/ci/autonomous_repair.sh --scan --repo mdyerapis-coder/hada --limit 5
```

For each open PR with a failing check it:
- clones into an isolated worktree under `$TMPDIR/hada-repair-*`,
- fetches the failed-run log and classifies the failure
  (`shellcheck` / `test` / `build`),
- writes `.ci-evidence/diagnosis.md` + `diagnosis.json` with the repair
  instruction.

The agent (Hermes) reads the diagnosis, implements the fix in the worktree,
then runs `--continue`.

### Continue (verify + draft PR)

```bash
scripts/ci/autonomous_repair.sh --continue <worktree> <pr> <base>
```

Runs, in order:
1. `repair_guardrails.sh` — abort if out-of-scope files/secrets/merge calls.
2. `verify_in_worktree` — ShellCheck, `reject_operator_paths.sh`,
   `verify_release_manifests.sh`, `run_fast_tests.sh`, repo pytest.
3. `repair_evidence.sh` — audit report + evidence tarball (sha256).
4. Commit on `agent/autofix-pr-<n>-<ts>` branch.
5. Push + open **DRAFT** PR linked to `#<pr>`.
6. **Stop** — no merge.

## Triggering

A Hermes cron job `hada-autonomous-repair` runs the scan on a schedule
(default every 30 min) and, for each diagnosis, performs the fix and
`--continue`. It sends a Telegram summary after each repair (or "no failures").

## Guardrail scope (rejected edits)

- `.github/workflows/deploy.yml`, `release.yml`
- `workspace/deploy*`, `*/compose*`, `*/supervisor*`, `VALKEY_SVC.json`
- `policies/`, `docs/adr/`, `releases/`, `archives/`
- any file matching `*.secret`, `*.key`, `*.pem`, `secrets`, `credentials`
- any addition of a secret pattern (`ghp_…`, `Bearer …`, `api_key=…`, …)
- any `gh pr merge` / auto-merge / branch-protection operation

## Recovery

If a repair is wrong, close the draft PR and delete the branch. The original
PR is untouched (repairs go to a separate branch). The worktree under
`$TMPDIR/hada-repair-*` can be removed.

## Manual override

To disable autonomously-opened PRs, set `HADA_REPAIR_DRYRUN=1` — the scan still
diagnoses but `--continue` will print the planned PR and stop before pushing.
