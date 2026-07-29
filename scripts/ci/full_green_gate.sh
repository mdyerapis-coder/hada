#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'FULL_GATE_ERROR: required tool missing: %s\n' "$1" >&2
    exit 127
  }
}

need git
need bash
need python3
need pytest
need shellcheck
need uv

if [[ -n "$(git status --porcelain)" ]]; then
  echo 'FULL_GATE_ERROR: candidate must be clean and committed before verification' >&2
  git status --short >&2
  exit 1
fi
cleanup_evidence() {
  git restore -- .ci-evidence 2>/dev/null || true
  git clean -fd -- .ci-evidence >/dev/null 2>&1 || true
}
trap cleanup_evidence EXIT

git diff --check
python3 scripts/ci/reject_conflict_artifacts.py

mapfile -d '' shell_scripts < <(git ls-files -z '*.sh')
if ((${#shell_scripts[@]})); then
  for script in "${shell_scripts[@]}"; do bash -n "$script"; done
  # Fail on ShellCheck errors/warnings; informational style findings in vendored
  # candidate appliances remain visible to dedicated cleanup work.
  shellcheck --severity=warning "${shell_scripts[@]}"
fi

bash scripts/ci/reject_operator_paths.sh
base_ref="${HADA_BUILD_BASE_SHA:-}"
if [[ -z "$base_ref" ]]; then
  base_ref=$(git merge-base HEAD origin/main 2>/dev/null || git rev-parse HEAD^)
fi
bash scripts/ci/repair_guardrails.sh "$ROOT" "$base_ref"
bash scripts/ci/verify_release_manifests.sh
HADA_REPAIR_VERIFY=1 bash scripts/ci/run_fast_tests.sh
bash workspace/tests/phase-b/run_all.sh

CTL="$ROOT/candidate/phase2-hermes-ctl"
python3 -m compileall -q "$CTL/hermes_ctl"
(
  cd "$CTL"
  PYTHONPATH="$CTL" python3 -m pytest -q tests
)

ORCH="$ROOT/candidate/v5/HADA-M1-durable-orchestrator"
(
  cd "$ORCH"
  uv run --python 3.12 --extra dev ruff check src tests
  uv run --python 3.12 --extra dev mypy src/hada
  uv run --python 3.12 --extra dev pytest -q -m 'not integration'
)

# Verification must leave the candidate committed and free of unmerged entries.
cleanup_evidence
if git ls-files -u | grep -q .; then
  echo 'FULL_GATE_ERROR: unmerged Git index entries remain' >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'FULL_GATE_ERROR: verification changed or found uncommitted files' >&2
  git status --short >&2
  exit 1
fi

printf 'FULL_GREEN_GATE: PASS\n'
