#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="$ROOT/scripts/ci/full_green_gate.sh"
SCANNER="$ROOT/scripts/ci/reject_conflict_artifacts.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Missing required tooling is fatal, never a warning/skip.
mkdir -p "$TMP/bin"
for tool in bash dirname git python3 pytest shellcheck; do
  ln -s "$(command -v "$tool")" "$TMP/bin/$tool"
done
set +e
PATH="$TMP/bin" "$GATE" >"$TMP/missing.out" 2>&1
rc=$?
set -e
[[ $rc == 127 ]]
grep -q 'required tool missing: uv' "$TMP/missing.out"

# Scanner rejects only anchored real markers and ignores decorative separators.
repo="$TMP/repo"
mkdir "$repo"
git -C "$repo" init -q
git -C "$repo" config user.name Test
git -C "$repo" config user.email test@example.invalid
printf '# ===== decorative\n' >"$repo/good.sh"
# shellcheck disable=SC2016
printf '```\n<<<<<<< documented-example\n=======\n>>>>>>> branch\n```\n' >"$repo/example.md"
git -C "$repo" add .
git -C "$repo" commit -qm clean
(cd "$repo" && python3 "$SCANNER") >/dev/null
printf '<<<<<<< HEAD\nbad\n=======\nworse\n>>>>>>> branch\n' >"$repo/bad.py"
git -C "$repo" add bad.py
git -C "$repo" commit -qm bad
set +e
(cd "$repo" && python3 "$SCANNER") >"$TMP/marker.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
grep -q 'bad.py:1:<<<<<<< HEAD' "$TMP/marker.out"
if grep -q 'good.sh' "$TMP/marker.out" || grep -q 'example.md' "$TMP/marker.out"; then
  echo 'scanner rejected a decorative or documented marker' >&2
  exit 1
fi

# The central gate must include every repository-wide validation surface.
for required in \
  reject_conflict_artifacts.py repair_guardrails.sh reject_operator_paths.sh \
  verify_release_manifests.sh run_fast_tests.sh workspace/tests/phase-b/run_all.sh \
  compileall pytest 'ruff check' 'mypy src/hada'; do
  grep -q "$required" "$GATE" || {
    printf 'missing full-gate step: %s\n' "$required" >&2
    exit 1
  }
done
if grep -Eq 'pytest.*\|\||shellcheck not installed.*skipping' "$GATE"; then
  echo 'full gate contains a failure-swallowing pattern' >&2
  exit 1
fi

printf 'PASS: missing tools fail closed and required full-gate surfaces are present\n'
printf 'PASS: anchored conflict markers are rejected without separator false positives\n'
