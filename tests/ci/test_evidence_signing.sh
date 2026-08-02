#!/usr/bin/env bash
# test_evidence_signing.sh — exercises sign_evidence.sh + verify_evidence.sh:
#   pass 1: sign two files, verify returns CHAIN OK
#   pass 2: tamper a signed artifact, verify exits 1
#   pass 3: tamper then restore, verify returns CHAIN OK (recovery)
# Uses only mktemp scratch dirs (never pollutes a repo evidence root).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIGN="$ROOT/scripts/ci/sign_evidence.sh"
VERIFY="$ROOT/scripts/ci/verify_evidence.sh"
B="$(mktemp -d)"
trap 'rm -rf "$B"' EXIT

printf 'alpha payload\n' > "$B/a.json"
printf 'beta payload\n' > "$B/b.json"

pass=0; fail=0
ck() { if "$@"; then pass=$((pass+1)); else fail=$((fail+1)); echo "  FAIL: $*"; fi; }

# 1 — sign two artifacts into a fresh chain, verify
ck bash "$SIGN" "$B/a.json" a01 "$B/chain.tsv"
ck bash "$SIGN" "$B/b.json" b02 "$B/chain.tsv"
ck bash "$VERIFY" "$B/chain.tsv" 2>/dev/null

# 2 — tamper the artifact, verifier must reject
printf 'evil\n' >> "$B/a.json"
if bash "$VERIFY" "$B/chain.tsv" >/dev/null 2>&1; then
  echo "  FAIL: verifier accepted tampered artifact"; fail=$((fail+1))
else
  pass=$((pass+1))
fi

# 3 — restore and confirm recovery
printf 'alpha payload\n' > "$B/a.json"
ck bash "$VERIFY" "$B/chain.tsv" 2>/dev/null

echo "evidence-signing: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]