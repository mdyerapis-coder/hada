#!/usr/bin/env bash
#
# HADA M1 Phase B — Deployment-runner test harness
#
# Runs all Phase B deployment-runner tests (NOT the Phase B0 port/Docker
# tests, which live in tests/static/ and remain separate).
#
# LOCAL-ONLY: no SSH, no SCP, no Docker daemon required. All remote
# interactions are mocked.
#
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TESTS=(
    test_ssh_sudo_capture.sh
    test_prohibited_operation_scanner.sh
    test_stage_aware_rollback.sh
    test_remote_temp_permissions.sh
    test_env_validation.sh
    test_installed_manifest.sh
    test_recoverable_install.sh
    test_cross_gate_happy_path.sh
    test_complete_payload.sh
    test_supervisor_invocation.sh
    test_valkey_secret_absence.sh
    test_valkey_durability_v4.sh
    test_valkey_health.sh
    test_grafana_proxy.sh
    test_b0_checksum_manifest_evidence.sh
    test_b0_failure_evidence_v4.sh
    test_deploy_execute_zero_no_remote_v4.sh
    test_compose_rollback_safety.sh
    test_full_gates_1_10.sh
)

TOTAL=0
FAILED=0

echo "=================================================="
echo "HADA M1 Phase B — deployment-runner test suite"
echo "=================================================="

for t in "${TESTS[@]}"; do
    TOTAL=$((TOTAL + 1))
    echo ""
    echo "--- RUN: ${t} ---"
    if bash "${HERE}/${t}"; then
        echo "--- OK:  ${t} ---"
    else
        echo "--- FAIL: ${t} ---" >&2
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=================================================="
echo "Suite summary: $((TOTAL - FAILED))/${TOTAL} test scripts passed"
echo "=================================================="
if (( FAILED > 0 )); then
    echo "SUITE RESULT: FAIL"
    exit 1
fi
echo "SUITE RESULT: PASS"
exit 0
