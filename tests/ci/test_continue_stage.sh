#!/usr/bin/env bash
# test_continue_stage.sh — hermetic verification of autonomous_repair.sh Stage B
# (--continue): the riskiest stage (it commits, pushes, opens a PR).
#
# Uses a STUBBED `gh` on PATH and a throwaway local bare git remote so no
# network or real GitHub calls occur. Proves:
#   1. Happy path: a benign fix -> guardrail passes -> verification passes ->
#      a DRAFT PR is opened (gh pr create) and gh pr merge is NEVER called.
#   2. Guardrail abort: a forbidden edit -> --continue exits 1 and gh pr create
#      is NEVER invoked (no commit, no PR).
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

# --- Build a stub `gh` that records calls and NEVER merges ---
STUB=$(mktemp -d)
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
TRACE="${GH_STUB_TRACE:-/tmp/gh-stub-trace.txt}"
echo "CALLED: $*" >> "$TRACE"
if [[ " $* " == *" pr merge "* ]]; then
  echo "VIOLATION: gh pr merge invoked" >> "$TRACE"
  exit 2
fi
if [[ " $* " == *" pr create "* ]]; then
  echo "https://github.com/example/hada/pull/999"
  exit 0
fi
exit 0
EOF
chmod +x "$STUB/gh"

# Make a throwaway bare mirror of HADA so --continue can push locally.
REMOTE=$(mktemp -d)/bare.git
git clone --bare "$HADA_ROOT" "$REMOTE" >/dev/null 2>&1

cleanup() { rm -rf "$STUB" "${REMOTE%/*}" "$WT" "$WT2" 2>/dev/null; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Scenario 1 — happy path (benign fix)
# ---------------------------------------------------------------------------
TRACE1=$(mktemp)
WT=$(mktemp -d)/wt
git clone "$REMOTE" "$WT" >/dev/null 2>&1
git -C "$WT" checkout -q origin/main
# Benign, uncommitted edit so the orchestrator's git add -A && commit has work.
printf '\n# benign test comment\n' >> "$WT/README.md"

set +e
GH_STUB_TRACE="$TRACE1" PATH="$STUB:$PATH" \
  bash "$ORCH" --continue "$WT" 101 origin/main >/dev/null 2>&1
rc1=$?
set -e

check "happy path: --continue exits 0" 0 $rc1
if grep -q 'pr create' "$TRACE1" 2>/dev/null; then
  echo "PASS: happy path opened a draft PR (gh pr create)"; pass=$((pass+1))
else
  echo "FAIL: happy path did not call gh pr create" >&2; fail=$((fail+1))
fi
if grep -q 'pr merge' "$TRACE1" 2>/dev/null; then
  echo "FAIL: happy path called gh pr merge (must never merge)" >&2; fail=$((fail+1))
else
  echo "PASS: happy path never called gh pr merge"; pass=$((pass+1))
fi

# ---------------------------------------------------------------------------
# Scenario 2 — guardrail abort (forbidden policies/ edit)
# ---------------------------------------------------------------------------
TRACE2=$(mktemp)
WT2=$(mktemp -d)/wt2
git clone "$REMOTE" "$WT2" >/dev/null 2>&1
git -C "$WT2" checkout -q origin/main
mkdir -p "$WT2/policies"
echo "change" > "$WT2/policies/RELEASE_GOVERNANCE.md"

set +e
GH_STUB_TRACE="$TRACE2" PATH="$STUB:$PATH" \
  bash "$ORCH" --continue "$WT2" 102 origin/main >/dev/null 2>&1
rc2=$?
set -e

check "guardrail abort: --continue exits non-zero" 1 $rc2
if grep -q 'pr create' "$TRACE2" 2>/dev/null; then
  echo "FAIL: guardrail abort still opened a PR" >&2; fail=$((fail+1))
else
  echo "PASS: guardrail abort opened no PR (gh pr create not called)"; pass=$((pass+1))
fi

echo "----"
echo "continue-stage tests: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
