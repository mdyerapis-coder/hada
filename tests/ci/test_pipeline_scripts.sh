#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

EVIDENCE_SHA256=$(printf x | sha256sum | awk '{print $1}') \
AUTHORIZATION_REFERENCE=review/test \
TARGET_ENVIRONMENT=staging \
  bash scripts/ci/validate_deployment_authority.sh >/dev/null

if EVIDENCE_SHA256=bad AUTHORIZATION_REFERENCE=x TARGET_ENVIRONMENT=staging \
  bash scripts/ci/validate_deployment_authority.sh >/dev/null 2>&1; then
  echo 'FAIL: invalid hash accepted.' >&2
  exit 1
fi

bash -n scripts/ci/*.sh
echo 'PASS: pipeline bootstrap scripts.'

# Release-manifest gate regression test (validates verify_release_manifests.sh fix).
if [[ -x tests/ci/test_release_manifests.sh ]]; then
  tests/ci/test_release_manifests.sh
fi

# Central full-green gate and conflict-artifact scanner fail-closed tests.
if [[ -x tests/ci/test_full_green_gate.sh ]]; then
  tests/ci/test_full_green_gate.sh
fi

# The --continue/--scan self-tests re-invoke autonomous_repair.sh. Running them
# *inside* a repair's own verification (verify_in_worktree) would recurse
# infinitely. Skip them when HADA_REPAIR_VERIFY is set (set by the repair
# script's verification step). CI runs the full suite (no guard).
if [[ -z "${HADA_REPAIR_VERIFY:-}" ]]; then
  # Orchestrator --continue stage: hermetic (stubbed gh + local bare remote).
  if [[ -x tests/ci/test_continue_stage.sh ]]; then
    tests/ci/test_continue_stage.sh
  fi

  # Orchestrator --scan stage: hermetic (stubbed gh + git, no network).
  if [[ -x tests/ci/test_scan_stage.sh ]]; then
    tests/ci/test_scan_stage.sh
  fi

  # Build-loop guard: isolated worktree, immutable base, bounded lease, draft PR.
  if [[ -x tests/ci/test_build_cycle_guard.sh ]]; then
    tests/ci/test_build_cycle_guard.sh
  fi
else
  echo "SKIP: repair self-tests (--continue/--scan) during in-repair verification (recursion guard)."
fi
