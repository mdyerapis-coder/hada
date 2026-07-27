#!/usr/bin/env bash
set -euo pipefail

mkdir -p .ci-evidence
patterns='(/home/[^/]+/|/Users/[^/]+/|C:\\Users\\)'
search_roots=(workspace scripts tests .github)
existing=()
for path in "${search_roots[@]}"; do [[ -e "$path" ]] && existing+=("$path"); done

if ((${#existing[@]} == 0)); then
  echo 'No searchable implementation paths found.' | tee .ci-evidence/operator-path-scan.txt
  exit 0
fi

# Historical evidence, inspection snapshots, packaged release artifacts, and
# review bundles are immutable records of past operator runs; they legitimately
# contain the operator paths they captured at the time. The governance goal of
# this gate is that no *executable/deployable implementation* (scripts, tests,
# configs, workflows) hardcodes an operator-local path, so the scan excludes
# only those recorded-evidence locations.
set +e
grep -RInE --exclude='reject_operator_paths.sh' --exclude-dir='.git' \
  --exclude-dir='evidence' \
  --exclude-dir='inspection' \
  --exclude-dir='artifacts' \
  --exclude='HADA-TAKEOVER.md' \
  --exclude='phase-b-review-bundle.txt' \
  --exclude='phase-b0-review-bundle.txt' \
  "$patterns" "${existing[@]}" > .ci-evidence/operator-path-scan.txt
status=$?
set -e
if [[ $status -eq 0 ]]; then
  cat .ci-evidence/operator-path-scan.txt
  echo 'FAIL: operator-local absolute path detected.' >&2
  exit 1
fi
[[ $status -eq 1 ]] || exit "$status"
echo 'PASS: no operator-local absolute paths detected.' | tee .ci-evidence/operator-path-scan.txt
