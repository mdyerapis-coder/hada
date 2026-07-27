#!/usr/bin/env bash
set -euo pipefail
mkdir -p .ci-evidence
release_path=${HADA_RELEASE_PATH:-}

run_suite() {
  local suite=$1
  echo "Running $suite" | tee .ci-evidence/e2e-suite.txt
  (cd "$(dirname "$suite")" && "./$(basename "$suite")") 2>&1 | tee .ci-evidence/e2e-output.txt
}

for candidate in \
  tests/fresh-deploy/run_all.sh \
  workspace/tests/fresh-deploy/run_all.sh; do
  if [[ -x "$candidate" ]]; then run_suite "$candidate"; exit 0; fi
done

if [[ -n "$release_path" && -f "$release_path" ]]; then
  tar -xf "$release_path" -C .ci-clean-room
  suite=$(find .ci-clean-room -type f -path '*/tests/fresh-deploy/run_all.sh' -print -quit)
  [[ -n "$suite" ]] || { echo 'FAIL: E2E suite not found in release archive.' >&2; exit 1; }
  chmod +x "$suite"
  run_suite "$suite"
  exit 0
fi

echo 'FAIL: no fresh-deploy E2E suite found.' >&2
exit 1
