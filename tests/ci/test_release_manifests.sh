#!/usr/bin/env bash
# test_release_manifests.sh — regression test for the release-manifest CI gate
# (scripts/ci/verify_release_manifests.sh). Ensures the gate both accepts a
# valid releases/ tree AND rejects a corrupt checksum (not just "files found").
#
# Run via tests/ci/test_pipeline_scripts.sh (CI "Run fast tests") or directly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERIFY="$ROOT/scripts/ci/verify_release_manifests.sh"

fail=0
pass=0
check() {
  local desc="$1" want="$2" got="$3"
  if [[ "$want" -eq 0 && "$got" -eq 0 ]] || [[ "$want" -ne 0 && "$got" -ne 0 ]]; then
    echo "PASS: $desc"; pass=$((pass+1))
  else
    echo "FAIL: $desc (expected exit~$want, got $got)" >&2; fail=$((fail+1))
  fi
}

# --- Positive: the real releases/ tree must verify (all 4 candidates) ---
bash "$VERIFY" >/dev/null 2>&1
check "release-manifest gate accepts valid releases/ tree" 0 $?

# Remaining probes are expected-failure cases; disable errexit so the
# expected non-zero exits are captured by check() rather than aborting.
set +e

# --- Negative: a corrupt checksum must be rejected (gate actually verifies) ---
T=$(mktemp -d)
mkdir -p "$T/releases/v1"
echo "artifact.zip" > "$T/releases/v1/artifact.zip"
# Intentional WRONG checksum
echo "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef  artifact.zip" > "$T/releases/v1/artifact.zip.sha256"
( cd "$T" && bash "$VERIFY" >/dev/null 2>&1 ); rc=$?
check "release-manifest gate rejects corrupt checksum" 1 $rc
rm -rf "$T"

# --- Negative: a manifest referencing a missing path must be rejected ---
T=$(mktemp -d)
mkdir -p "$T/releases/v2"
# References a file that does not exist
echo "cafebabecafebabecafebabecafebabecafebabecafebabecafebabecafebabe  nope.zip" > "$T/releases/v2/nope.zip.sha256"
( cd "$T" && bash "$VERIFY" >/dev/null 2>&1 ); rc=$?
check "release-manifest gate rejects manifest for missing file" 1 $rc
rm -rf "$T"

set -e
echo "----"
echo "release-manifest tests: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
