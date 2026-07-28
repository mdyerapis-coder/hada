#!/usr/bin/env bash
# test_scan_stage.sh — hermetic verification of autonomous_repair.sh Stage A
# (--scan): the entry point that monitors PRs, classifies CI state, and writes
# a diagnosis for failing PRs.
#
# Uses STUBBED `gh` and `git` on PATH (no network, no real repo, no real PRs)
# and proves:
#   1. A PR whose statusCheckRollup contains a FAILURE is classified "failing"
#      and gets a .ci-evidence/diagnosis.{md,json} written.
#   2. A PR with a passing rollup is NOT diagnosed (no diagnosis file).
#   3. --scan never opens or merges a PR (gh pr create / pr merge never called).
#   4. --scan exits 0.
#
# Run via tests/ci/test_pipeline_scripts.sh (CI "Run fast tests") or directly.
set -euo pipefail

HADA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ORCH="$HADA_ROOT/scripts/ci/autonomous_repair.sh"

fail=0; pass=0
check() {
  local desc="$1" want="$2" got="$3"
  if [[ ("$want" -eq 0 && "$got" -eq 0) || ("$want" -ne 0 && "$got" -ne 0) ]]; then
    echo "PASS: $desc"; pass=$((pass+1))
  else
    echo "FAIL: $desc (expected exit~$want, got $got)" >&2; fail=$((fail+1))
  fi
}

STUB=$(mktemp -d)

# Stub `gh`: returns canned PR list / view data; records pr create|merge.
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
TRACE="${GH_STUB_TRACE:-/tmp/gh-stub-trace.txt}"
echo "CALLED: $*" >> "$TRACE"
if [[ " $* " == *" pr merge "* ]]; then echo "VIOLATION" >> "$TRACE"; exit 2; fi
if [[ " $* " == *" pr create "* ]]; then echo "https://github.com/example/hada/pull/1"; exit 0; fi
if [[ " $* " == *" pr list "* ]]; then
  # Two PRs: #201 failing, #202 passing.
  cat <<'JSON'
[{"number":201,"title":"broken fix","headRefName":"fix/201","baseRefName":"main"},
 {"number":202,"title":"good fix","headRefName":"fix/202","baseRefName":"main"}]
JSON
  exit 0
fi
if [[ " $* " == *" pr view 201 "*" statusCheckRollup"* ]]; then
  echo '{"statusCheckRollup":[{"conclusion":"FAILURE","status":"COMPLETED"}]}'; exit 0
fi
if [[ " $* " == *" pr view 202 "*" statusCheckRollup"* ]]; then
  echo '{"statusCheckRollup":[{"conclusion":"SUCCESS","status":"COMPLETED"}]}'; exit 0
fi
if [[ " $* " == *" pr view 201 "*" title"* ]]; then echo "broken fix"; exit 0; fi
if [[ " $* " == *" pr view 202 "*" title"* ]]; then echo "good fix"; exit 0; fi
if [[ " $* " == *" run list "* ]]; then echo '[]'; exit 0; fi
if [[ " $* " == *" run view "* ]]; then echo ""; exit 0; fi
exit 0
EOF
chmod +x "$STUB/gh"

# Stub `git`: make clone/fetch/checkout/no-op reads against base refs no-ops so
# --scan never touches network or requires a fetched origin/main in CI.
cat > "$STUB/git" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "clone" ]]; then
  tgt="${!#}"; mkdir -p "$tgt" 2>/dev/null || true; exit 0
fi
if [[ "$1" == "fetch" || "$1" == "checkout" ]]; then exit 0; fi
# Base-ref reads (e.g. `git diff --quiet origin/main`) must not require a real
# fetched remote in the hermetic test environment.
if [[ "$1" == "diff" || "$1" == "rev-parse" || "$1" == "merge-base" || "$1" == "log" || "$1" == "show" ]]; then
  if [[ " $* " == *" main"* || " $* " == *"origin/"* ]]; then exit 0; fi
fi
exec /usr/bin/git "$@"
EOF
chmod +x "$STUB/git"

TRACE=$(mktemp)
trap 'rm -rf "$STUB" "$TRACE" 2>/dev/null' EXIT

set +e
GH_STUB_TRACE="$TRACE" PATH="$STUB:$PATH" \
  bash "$ORCH" --scan --repo mdyerapis-coder/hada --limit 5 >/dev/null 2>&1
rc=$?
set -e
check "scan: --scan exits 0" 0 $rc

# The failing PR (#201) should have produced a diagnosis under a worktree.
# Worktrees are mktemp dirs under /tmp/hada-repair-XXXXXX; scan writes
# .ci-evidence/diagnosis.json into each. Find any produced for PR 201.
diag201=""
while IFS= read -r f; do diag201="$f"; break; done < <(grep -rl '"pr": 201' /tmp/hada-repair-*/.ci-evidence/diagnosis.json 2>/dev/null)
if [[ -n "$diag201" ]]; then
  echo "PASS: scan wrote diagnosis for failing PR #201"; pass=$((pass+1))
else
  echo "FAIL: scan did not diagnose failing PR #201" >&2; fail=$((fail+1))
fi

# Passing PR (#202) must NOT be diagnosed.
diag202=""
while IFS= read -r f; do diag202="$f"; break; done < <(grep -rl '"pr": 202' /tmp/hada-repair-*/.ci-evidence/diagnosis.json 2>/dev/null)
if [[ -z "$diag202" ]]; then
  echo "PASS: scan did not diagnose passing PR #202"; pass=$((pass+1))
else
  echo "FAIL: scan incorrectly diagnosed passing PR #202" >&2; fail=$((fail+1))
fi

# Never opens or merges a PR during scan.
if grep -q 'pr create' "$TRACE" 2>/dev/null; then
  echo "FAIL: scan opened a PR (must not)" >&2; fail=$((fail+1))
else
  echo "PASS: scan never called gh pr create"; pass=$((pass+1))
fi
if grep -q 'pr merge' "$TRACE" 2>/dev/null; then
  echo "FAIL: scan called gh pr merge (must never)" >&2; fail=$((fail+1))
else
  echo "PASS: scan never called gh pr merge"; pass=$((pass+1))
fi

echo "----"
echo "scan-stage tests: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
