#!/usr/bin/env bash
# autonomous_repair.sh — governed autonomous PR-repair pipeline for HADA.
#
# Design (human/agent-in-the-loop, fail-closed):
#   Stage A (--scan):   monitor open PRs, detect failing CI, for each create an
#                      isolated git worktree, fetch + classify the CI failure,
#                      and emit a DIAGNOSIS the repair agent acts on.
#   Stage B (--continue <wt> <pr> <base>): after the agent implements the
#                      smallest safe fix in <wt>, run guardrails, local
#                      verification (ShellCheck + relevant test suites),
#                      generate evidence + audit report, commit, push a repair
#                      branch, open a DRAFT PR linked to the original, and STOP
#                      for human approval. Never merges/deploys.
#
# Hard constraints (also enforced by repair_guardrails.sh):
#   - No merge, no deploy, no branch-protection change.
#   - No secret / infrastructure / governance file modification.
#   - Opens a DRAFT PR and stops for human approval.
#
# Usage:
#   autonomous_repair.sh --scan [--repo owner/repo] [--limit N]
#   autonomous_repair.sh --continue <worktree_dir> <pr_number> <base_ref> [--repo owner/repo]
set -euo pipefail

REPO="${HADA_REPAIR_REPO:-mdyerapis-coder/hada}"
MODE=""
WT=""; PR=""; BASE=""; LIMIT=5

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scan) MODE="scan" ;;
    --continue) MODE="continue" ;;
    --repo) REPO="$2"; shift ;;
    --limit) LIMIT="$2"; shift ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) if [[ -z "$WT" ]]; then WT="$1"; elif [[ -z "$PR" ]]; then PR="$1"; elif [[ -z "$BASE" ]]; then BASE="$1"; fi ;;
  esac
  shift
done

[[ -n "$MODE" ]] || { echo "MODE required: --scan | --continue <wt> <pr> <base>" >&2; exit 2; }

run_gh() { gh "$@"; }

# ---------------------------------------------------------------------------
# Stage A: scan for failing PRs and diagnose.
# ---------------------------------------------------------------------------
scan() {
  echo "== autonomous_repair: SCAN ($REPO) =="
  mapfile -t PRS < <(run_gh pr list --repo "$REPO" --state open --json number,title,isDraft,headRefName,baseRefName \
    | python3 -c "import sys,json;[print(p['number'],p['headRefName'],p['baseRefName']) for p in json.load(sys.stdin)]")
  if ((${#PRS[@]} == 0)); then echo "No open PRs."; return 0; fi

  local found=0
  for line in "${PRS[@]:0:$LIMIT}"; do
    local n="${line%% *}"; local head="${line#* }"; local base="${head##* }"; head="${line#* }"; head="${head% *}"
    local title; title=$(run_gh pr view "$n" --repo "$REPO" --json title --jq '.title')
    # CI conclusion for the PR head
    local status; status=$(run_gh pr view "$n" --repo "$REPO" --json statusCheckRollup \
      | python3 -c "import sys,json
d=json.load(sys.stdin).get('statusCheckRollup') or []
if not d: print('pending'); exit()
fails=[c for c in d if (c.get('conclusion') in ('FAILURE','TIMED_OUT','CANCELLED') or c.get('status')=='COMPLETED' and c.get('conclusion')=='FAILURE')]
print('failing' if fails else 'passing')" 2>/dev/null || echo "unknown")
    echo "  PR #$n [$status] $title"
    if [[ "$status" == "failing" ]]; then
      found=$((found+1))
      diagnose_one "$n" "$head" "$base"
    fi
  done
  echo "== scan complete: $found failing PR(s) diagnosed =="
}

diagnose_one() {
  local n="$1" head="$2" base="$3"
  local wt; wt=$(mktemp -d "${TMPDIR:-/tmp}/hada-repair-XXXXXX")
  echo "  -> worktree: $wt"
  git clone --quiet --filter=blob:none "https://github.com/$REPO.git" "$wt" 2>/dev/null \
    || git clone --quiet "https://github.com/$REPO.git" "$wt"
  (cd "$wt" && git fetch --quiet origin "$head" && git checkout --quiet "$head")

  # Fetch the latest workflow run logs for the head branch.
  local run_id; run_id=$(run_gh run list --repo "$REPO" --branch "$head" --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)
  local log=""
  if [[ -n "$run_id" ]]; then
    log=$(run_gh run view "$run_id" --log-failed --repo "$REPO" 2>/dev/null | tail -60 || true)
  fi

  # Classify failure type from log heuristics.
  local ftype="unknown"
  if echo "$log" | grep -qiE 'ShellCheck|SC[0-9]{4}'; then ftype="shellcheck";
  elif echo "$log" | grep -qiE 'AssertionError|Error:|FAILED|test_'; then ftype="test";
  elif echo "$log" | grep -qiE 'build|compile|ModuleNotFound|ImportError'; then ftype="build"; fi

  mkdir -p "$wt/.ci-evidence"
  {
    echo "# Diagnosis for PR #$n ($head -> $base)"
    echo "failure_type: $ftype"
    echo "head: $head"
    echo "base: $base"
    echo "worktree: $wt"
    echo "---- failed CI log (tail) ----"
    echo "$log"
  } > "$wt/.ci-evidence/diagnosis.md"

  # Machine-readable summary for the repair agent.
  python3 - "$n" "$head" "$base" "$ftype" "$wt" <<'PY'
import sys,json,os
n,h,b,ft,wt=sys.argv[1:6]
summary={
 "pr":int(n),"head":h,"base":b,"failure_type":ft,"worktree":wt,
 "instruction":"Implement the smallest safe fix in the worktree, then run: "
               "scripts/ci/autonomous_repair.sh --continue %s %s %s"%(wt,n,b),
}
print(json.dumps(summary,indent=2))
# also drop a file the agent can read
with open(os.path.join(wt,".ci-evidence","diagnosis.json"),"w") as f:
    json.dump(summary,f,indent=2)
PY
  echo "  -> diagnosis written to $wt/.ci-evidence/diagnosis.md"
}

# ---------------------------------------------------------------------------
# Stage B: after the agent implements the fix, verify + commit + draft PR.
# ---------------------------------------------------------------------------
continue_repair() {
  [[ -d "$WT" ]] || { echo "worktree not found: $WT" >&2; exit 1; }
  [[ -n "$PR" && -n "$BASE" ]] || { echo "usage: --continue <wt> <pr> <base>" >&2; exit 2; }
  echo "== autonomous_repair: CONTINUE (PR #$PR) =="

  # 1) Guardrails
  echo "-- guardrails --"
  bash scripts/ci/repair_guardrails.sh "$WT" "$BASE" || {
    echo "GUARDRAIL FAILURE: aborting. No commit, no PR." >&2; exit 1; }

  # 2) Local verification: ShellCheck + relevant test suites.
  echo "-- verification --"
  (cd "$WT" && mkdir -p .ci-evidence)
  verify_in_worktree "$WT" | tee "$WT/.ci-evidence/verify.txt" || {
    echo "VERIFICATION FAILED: not opening PR." >&2; exit 1; }

  # 3) Evidence + audit report
  echo "-- evidence --"
  bash scripts/ci/repair_evidence.sh "$WT" "$PR" "$BASE" || {
    echo "EVIDENCE GENERATION FAILED." >&2; exit 1; }

  # 4) Commit (only if there are changes vs base)
  echo "-- commit --"
  if (cd "$WT" && git diff --quiet "$BASE"); then
    echo "No changes vs $BASE — nothing to commit." >&2; exit 1
  fi
  local repair_branch
  repair_branch="agent/autofix-pr-${PR}-$(date +%s)"
  (cd "$WT" && \
    git checkout -b "$repair_branch" && \
    git add -A && \
    git -c user.email="hermes-agent@local" -c user.name="HADA Autonomous Repair" \
      commit -q -m "fix: autonomous repair for PR #$PR

Diagnosed and fixed a failing CI check. Guardrails passed (no merge/deploy/
secrets/infra changes). Verified locally (ShellCheck + test suites).

Linked to #$PR" )

  # 5) Push + open DRAFT PR
  echo "-- push + draft PR --"
  (cd "$WT" && git push --quiet -u origin "$repair_branch")
  local body; body=$(cat "$WT/.ci-evidence/audit-report.md" 2>/dev/null || echo "Autonomous repair for #$PR.")
  run_gh pr create --repo "$REPO" --draft \
    --head "$repair_branch" --base "$BASE" \
    --title "fix: autonomous repair for PR #$PR" \
    --body "$(printf '%s\n\n---\n\nLinked to #%s. Draft for human review — not merged automatically.\n\nGuardrails: no merge/deploy/secrets/infra changes. Verification evidence attached in CI.' "$body" "$PR")" \
    | tee "$WT/.ci-evidence/pr-url.txt"

  # 6) STOP for human approval (never merge).
  echo "== DRAFT PR opened. STOPPING for human approval. No merge performed. =="
  echo "Repair branch: $repair_branch"
  echo "Worktree: $WT"
}

# Verification inside a worktree uses the same complete fail-closed gate as CI.
verify_in_worktree() {
  local wt="$1"
  (
    cd "$wt"
    HADA_REPAIR_VERIFY=1 bash scripts/ci/full_green_gate.sh
    echo "VERIFY OK"
  )
}

# dispatch
case "$MODE" in
  scan) scan ;;
  continue) continue_repair ;;
esac
