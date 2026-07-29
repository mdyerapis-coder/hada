#!/usr/bin/env bash
# repair_guardrails.sh — hard safety boundary for the autonomous repair pipeline.
#
# Enforces the immutable constraints:
#   - NEVER merge, deploy, or modify branch protection.
#   - NEVER modify secrets, infrastructure, or deployment/governance files.
#   - The repair may only touch source/test/CI-script files to implement the
#     smallest safe fix for a failing check.
#
# Usage: repair_guardrails.sh <worktree_dir> <base_ref>
# Exits 0 if the worktree diff is permitted, 1 if it violates a guardrail.
set -euo pipefail

WT="${1:?usage: repair_guardrails.sh <worktree_dir> <base_ref>}"
BASE="${2:?usage: repair_guardrails.sh <worktree_dir> <base_ref>}"

mkdir -p .ci-evidence
OUT=.ci-evidence/guardrail-scan.txt
: > "$OUT"

# Make untracked files visible to `git diff` (intent-to-add) so new files are
# also scanned. This does not stage content; the orchestrator stages later.
git -C "$WT" add -A -N 2>/dev/null || true

echo "Guardrail scan of $WT vs $BASE" | tee -a "$OUT"

# 1) No merge / deploy / branch-protection intent in any script we run.
#    (Defence-in-depth: the orchestrator never calls gh pr merge, but we
#     additionally refuse if a repair diff adds such calls.)
# shellcheck disable=SC2015
DANGEROUS_CALLS=$(cd "$WT" && git diff --unified=0 "$BASE" 2>/dev/null \
  | grep -E '^\+' | grep -iE 'gh pr merge|gh api .*merge|enablePullRequestAutoMerge|branch protection|protected' \
  | grep -v '^\+\+\+' || true)
if [[ -n "$DANGEROUS_CALLS" ]]; then
  echo "FAIL: prohibited merge/deploy/branch-protection operation detected:" | tee -a "$OUT"
  echo "$DANGEROUS_CALLS" | tee -a "$OUT"
  exit 1
fi

# 2) Forbidden file paths — infrastructure, deployment, governance, secrets.
FORBIDDEN_PATHS=(
  '^\.github/workflows/deploy\.yml$'
  '^\.github/workflows/release\.yml$'
  '^workspace/deploy'
  '^workspace/.*/compose'
  '^workspace/.*/supervisor'
  '^VALKEY_SVC\.json$'
  '^policies/'
  '^scripts/ci/validate_deployment_authority\.sh$'
  'releases/'
  'archives/'
)
violations=""
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  for pat in "${FORBIDDEN_PATHS[@]}"; do
    if [[ "$f" =~ $pat ]]; then
      violations+="  $f (matches $pat)"$'\n'
      break
    fi
  done
done < <(cd "$WT" && git diff --name-only "$BASE" 2>/dev/null)

# 3) Secret patterns added anywhere.
# shellcheck disable=SC2015
SECRET_HITS=$(cd "$WT" && git diff "$BASE" 2>/dev/null \
  | grep -E '^\+' | grep -iE 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]+|Bearer [A-Za-z0-9._-]+|api[_-]?key\s*[:=]|password\s*[:=]\s*["'\''][^"'\'']+["'\'']|aws_secret_access_key|private_key' \
  | grep -v '^\+\+\+' || true)
if [[ -n "$SECRET_HITS" ]]; then
  violations+="  SECRET pattern added:"$'\n'"$SECRET_HITS"$'\n'
fi

# 4) Secret-named files.
# shellcheck disable=SC2015
SECRET_FILES=$(cd "$WT" && git diff --name-only "$BASE" 2>/dev/null \
  | grep -iE '\.secret|\.key$|\.pem|secrets?\.|credentials' || true)
if [[ -n "$SECRET_FILES" ]]; then
  violations+="  secret-named file changed:"$'\n'"$SECRET_FILES"$'\n'
fi

if [[ -n "$violations" ]]; then
  echo "FAIL: guardrail violation — repair touches out-of-scope files:" | tee -a "$OUT"
  echo "$violations" | tee -a "$OUT"
  exit 1
fi

echo "PASS: no guardrail violation." | tee -a "$OUT"
exit 0
