#!/usr/bin/env bash
#
# HADA M1 Phase B — Full Gates 1-10 mocked acceptance test (correction 6)
#
# Runs the runner's REAL gate functions as ONE end-to-end workflow against a
# mocked fresh host:
#   1. candidate extraction + manifest
#   2. complete installation
#   3. secrets (provision-secrets + valkey secret file, no leak)
#   4. Compose rendering + secret-absence
#   5. build context validation
#   6. image pulls
#   7. orchestrator build-context validation
#   8. Compose startup
#   9. supervisor startup
#  10. service health
#  11. loopback exposure
#  12. final state
#  13. host + container git ls-remote
#  14. clean bounded rollback fixtures
#
# It catches mismatched project names (hada vs hada-m1) and missing runtime
# files. LOCAL-ONLY, fully mocked.

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-full-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found" >&2; exit 1; }

# shellcheck source=lib_mock_remote.sh
source "${HERE}/lib_mock_remote.sh"
mock_remote_init "${TEMP_DIR}"

# Use the smart full-test mock SSH (renders compose, short-circuits
# health checks, executes install/verify in the sandbox). Keep the lib's
# dedicated mock-scp (it understands scp argv, not command strings).
export HADA_PHASE_B_MOCK_SSH="${HERE}/mock_ssh_full.sh"
export HADA_FULL_TEST_CANDIDATE="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip"

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
export HADA_PHASE_B_TIMESTAMP="12345678901234"
export HADA_PHASE_B_CANDIDATE_ARCHIVE="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip"
export HADA_PHASE_B_CANDIDATE_SHA256="$(awk '{print $1}' "${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256")"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"

# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

run_gate() {
    local name="$1" fn="$2"
    set +e
    "${fn}" >"${TEMP_DIR}/${name}.log" 2>&1
    local rc=$?
    set -e
    if (( rc == 0 )); then
        assert_pass "${name} passed as part of the single workflow"
    else
        assert_fail "${name} FAILED (rc=${rc}):"
        tail -15 "${TEMP_DIR}/${name}.log" >&2 || true
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Full workflow
# ---------------------------------------------------------------------------
run_gate "gate1-candidate-extraction"  verify_and_extract_candidate
run_gate "gate2-remote-preparation"    remote_preparation_and_state_capture
run_gate "gate3-upload-install"        upload_and_install_application
run_gate "gate4-env-validation"        validate_production_env
run_gate "gate5-compose-render"       render_validate_compose
run_gate "gate5b-build-context"       validate_build_context
run_gate "gate6-image-pull-build"     pull_build_images
run_gate "gate7-compose-startup"      start_services
run_gate "gate8-health"               health_validate
run_gate "gate9-final-state"          capture_final_state
run_gate "gate10-repo-connectivity"   check_repository_connectivity

SB_OPT="${HADA_SANDBOX}/opt/hada"
SB_UNIT="${HADA_SANDBOX}/etc/systemd/system/hada-supervisor.service"
SB_VARLIB="${HADA_SANDBOX}/var/lib/hada"

# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------
# Complete installation present
for f in pyproject.toml README.md Dockerfile src config deploy scripts; do
    [[ -e "${SB_OPT}/$f" ]] && assert_pass "installed: /opt/hada/$f" \
        || assert_fail "missing installed: /opt/hada/$f"
done
[[ -f "${SB_UNIT}" ]] && assert_pass "service unit installed at /etc/systemd/system" \
    || assert_fail "service unit not installed"
[[ -f "${SB_OPT}/.env" ]] && assert_pass ".env provisioned" || assert_fail ".env missing"
# v3: protected COMPLETE valkey config file (valkey.conf), owned 999:1000, mode 0400
[[ -f "${SB_VARLIB}/secrets/valkey/valkey.conf" ]] \
    && assert_pass "valkey protected config file created (0400, not in evidence)" \
    || assert_fail "valkey protected config file not created"
if [[ -f "${SB_VARLIB}/secrets/valkey/valkey.conf" ]]; then
    mode="$(stat -c '%a' "${SB_VARLIB}/secrets/valkey/valkey.conf")"
    [[ "${mode}" == "400" ]] && assert_pass "valkey config file mode 0400" \
        || assert_fail "valkey config file mode is ${mode}, expected 400"
fi

# Project-name consistency: every captured compose invocation must use hada-m1
DECODED="$(mock_remote_decode_log)"
if grep -q 'compose' <<<"${DECODED}"; then
    if grep -qE "docker compose -p '?hada-m1'?" <<<"${DECODED}"; then
        assert_pass "all Compose invocations use project name hada-m1"
    else
        assert_fail "a Compose invocation does not use -p hada-m1"
    fi
    # Must NOT use a bare 'hada' project (mismatched name)
    if grep -qE "compose -p '?hada'?( |\"|$)" <<<"${DECODED}"; then
        assert_fail "a Compose invocation uses mismatched project name 'hada'"
    else
        assert_pass "no Compose invocation uses the mismatched project name 'hada'"
    fi
fi

# Supervisor startup went through systemctl start hada-supervisor.service
if grep -q 'systemctl start hada-supervisor.service' <<<"${DECODED}"; then
    assert_pass "supervisor started via systemd (Gate 9)"
else
    assert_fail "supervisor not started"
fi

# Health checks used VALKEYCLI_AUTH in-container, never valkey-cli -a
if grep -q 'valkey-cli -a' <<<"${DECODED}"; then
    assert_fail "valkey-cli -a (secret in argv) found in transmitted commands"
else
    assert_pass "no valkey-cli -a in any transmitted command"
fi
if grep -q 'VALKEYCLI_AUTH' <<<"${DECODED}"; then
    assert_pass "valkey health uses VALKEYCLI_AUTH (in-container, no secret in argv)"
else
    assert_fail "valkey health did not use VALKEYCLI_AUTH"
fi

# Loopback-only exposure
if grep -q '127.0.0.1:80' <<<"${DECODED}"; then
    assert_pass "caddy published only on loopback 127.0.0.1:80"
else
    assert_fail "no loopback 127.0.0.1:80 bind captured"
fi

# Final state captured
if grep -Eq 'docker ps -a --format|docker images -q|docker volume ls -q|docker network ls' <<<"${DECODED}"; then
    assert_pass "final Docker state captured (Gate 9)"
else
    assert_fail "final state not captured"
fi

# git ls-remote from host and container — require BOTH return codes AND both
# success markers (not merely the presence of command text in a log).
if grep -q 'LS_REMOTE_HOST_OK' <<<"${DECODED}"; then
    assert_pass "git ls-remote from host (user hada) succeeded (marker LS_REMOTE_HOST_OK)"
else
    assert_fail "git ls-remote from host (user hada) did not return its success marker"
fi
if grep -q 'LS_REMOTE_CONTAINER_OK' <<<"${DECODED}"; then
    assert_pass "git ls-remote from orchestrator container succeeded (marker LS_REMOTE_CONTAINER_OK)"
else
    assert_fail "git ls-remote from orchestrator container did not return its success marker"
fi
# Failure fixtures: a host-side git failure to a WRONG repo MUST fail closed
# (non-zero exit, NO success marker). Run it through the mock and assert rc!=0
# and no LS_REMOTE_HOST_OK marker in the mock's stdout.
: > "${HADA_MOCK_SSH_LOG}"
FAIL_RC=0
ssh_remote "repo-ls-remote-host-fixture" "set -Eeuo pipefail
sudo -n -u hada git ls-remote --exit-code 'https://github.com/nonexistent-org/nonexistent-repo.git' HEAD >/dev/null 2>&1 || { echo 'FAIL: git ls-remote from host as hada failed'; exit 1; }
echo 'LS_REMOTE_HOST_OK'" >"${TEMP_DIR}/git-fail-host.log" 2>&1 || FAIL_RC=$?
if [[ ${FAIL_RC} -ne 0 ]] && ! grep -q '^LS_REMOTE_HOST_OK$' "${TEMP_DIR}/git-fail-host.log"; then
    assert_pass "git ls-remote host failure fixture fails closed (rc!=0, no success marker)"
else
    assert_fail "git ls-remote host failure fixture did NOT fail closed"
fi

# Secret-leak sweep
PG_VAL="$(grep '^POSTGRES_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
VK_VAL="$(grep '^VALKEY_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
GF_VAL="$(grep '^GRAFANA_ADMIN_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
LEAKED=0
for sec in "${PG_VAL}" "${VK_VAL}" "${GF_VAL}"; do
    [[ -n "${sec}" ]] || continue
    if grep -rF -- "${sec}" "${HADA_PHASE_B_EVIDENCE_DIR}" >/dev/null 2>&1; then LEAKED=1; fi
    for lg in "${TEMP_DIR}"/gate*.log; do
        grep -qF -- "${sec}" "${lg}" 2>/dev/null && LEAKED=1
    done
    mock_remote_decode_log | grep -qF -- "${sec}" && LEAKED=1
done
if (( LEAKED == 0 )); then
    assert_pass "no secret value found in evidence, gate logs, or transmitted commands"
else
    assert_fail "a provisioned secret value LEAKED"
fi

# Clean bounded rollback fixtures
: > "${HADA_MOCK_SSH_LOG}"
CREATED_CONTAINERS=("hada-m1-postgres-1")
CREATED_VOLUMES=("hada-m1_postgres-data")
CREATED_NETWORKS=("hada-m1_control")
CREATED_IMAGES=("hada-orchestrator:0.2.0")
UNIT_INSTALLED=1
SUPERVISOR_STARTED=1
COMPOSE_UP_DONE=1
COMPOSE_UP_ATTEMPTED=1
ORCH_BUILT_BY_RUN=1
OPT_HADA_CREATED=1
ENV_CREATED=1
bounded_rollback >"${TEMP_DIR}/rb-clean.log" 2>&1 || true
DECODED_RB="$(mock_remote_decode_log)"
# bounded: must not rm -rf /var/lib/hada or /opt/hada
if grep -Eq 'rm -rf /var/lib/hada|rm -rf /opt/hada' <<<"${DECODED_RB}"; then
    assert_fail "clean rollback deletes /var/lib/hada or /opt/hada"
else
    assert_pass "clean bounded rollback removes only this run's tracked resources"
fi
# persistent data survives
[[ -d "${SB_VARLIB}/docker-volumes" ]] && assert_pass "persistent data preserved under /var/lib/hada after clean rollback" \
    || assert_fail "persistent data lost after clean rollback"

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Full Gates 1-10 acceptance test results"
echo "============================================"
echo "Passed: ${PASS_COUNT}"
echo "Failed: ${FAIL_COUNT}"
echo ""
if [[ ${FAIL_COUNT} -gt 0 ]]; then
    echo "RESULT: FAIL"
    exit 1
fi
echo "RESULT: PASS"
exit 0
