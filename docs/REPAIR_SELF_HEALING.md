# HADA Repair Self-Healing Structure

## Purpose

Keep the governed repair pipeline observable and recoverable without making an
LLM, a transient provider, or an unbounded retry loop a single point of failure.
The structure remains fail-closed: it never merges, deploys, changes secrets, or
bypasses review.

## Layers

1. **Script-only watchdog** (`scripts/ci/repair_watchdog.sh`)
   - Runs outside the LLM/provider failure domain.
   - Uses `flock` to prevent overlapping scans.
   - Validates scanner shell syntax before execution.
   - Retries transient GitHub/network failures up to three times with bounded
     backoff.
   - Persists atomic health state under
     `${XDG_STATE_HOME:-~/.local/state}/hada-repair/health.json`.
   - Stays silent while healthy; reports failures and recovery transitions.

2. **PR scan** (`autonomous_repair.sh --scan`)
   - Detects failed checks on open PRs and writes diagnoses in isolated clones.
   - Creates no commits and opens no PR during the scan stage.

3. **Main health gate**
   - Runs the shell fast-test suite.
   - Compiles the Hermes CTL Python package.
   - Runs all Hermes CTL Python tests even when no PR is open.
   - This closes the gap where a regression can land on `main` and remain
     invisible because the PR list is empty.

4. **Reasoning repair agent**
   - Reads watchdog incidents and diagnoses.
   - Reproduces the failure in an isolated worktree.
   - Applies one smallest-safe fix, runs full verification, and opens a draft PR.
   - Never merges, deploys, edits secrets, or changes governance automatically.

5. **Human escalation**
   - Authentication/permission failures explicitly request human input.
   - Other failures remain in bounded automatic retry and are reported to the
     Hermes CTL Instance Control chat.

## Output contract

- Healthy and unchanged: empty stdout (silent cron delivery).
- Recovery: one `RECOVERED` transition message.
- Failed scan or main gate: one actionable `ALERT`, failure count, and log tail.
- Authentication boundary: `Human input required` is included explicitly.

## Verification

```bash
bash tests/ci/test_repair_watchdog.sh
bash scripts/ci/run_fast_tests.sh
shellcheck scripts/ci/repair_watchdog.sh tests/ci/test_repair_watchdog.sh
```

The watchdog tests are hermetic: scanner and health-check behavior are stubbed,
so they exercise healthy silence, transient retry, persistent failure state,
recovery, main-regression detection, authentication escalation, and interesting
scan output without GitHub or network access.
