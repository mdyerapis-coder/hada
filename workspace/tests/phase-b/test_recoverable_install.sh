#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — Recoverable-installation tests (cross-gate correction 3)
#
# Proves:
#   1. Gate 3 verification failure -> bounded_rollback removes ONLY the
#      marker-verified /opt/hada release created by THIS run, so the next
#      run's Gate 2 existing-resource check is unblocked;
#   2. Gate 4 failure (after .env provisioning) is equally recoverable;
#   3. /var/lib/hada is NEVER deleted by any rollback branch;
#   4. pre-existing installations are never modified: without
#      OPT_HADA_CREATED=1 no removal command is issued at all, and even a
#      forced marker check refuses when the marker belongs to another run;
#   5. after services start (COMPOSE_UP_DONE=1), the tree is preserved.
#
# LOCAL-ONLY, fully mocked.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-rec-test-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found: ${RUNNER}" >&2; exit 1; }

# shellcheck source=lib_mock_remote.sh
source "${HERE}/lib_mock_remote.sh"
mock_remote_init "${TEMP_DIR}"

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
export HADA_PHASE_B_TIMESTAMP="77777777777777"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

SB_OPT="${HADA_SANDBOX}/opt/hada"
SB_VARLIB="${HADA_SANDBOX}/var/lib/hada"
SB_UNIT="${HADA_SANDBOX}/etc/systemd/system/hada-supervisor.service"

make_this_run_tree() {
    rm -rf "${SB_OPT}"
    mkdir -p "${SB_OPT}/scripts"
    echo "partial content" > "${SB_OPT}/Dockerfile"
    printf '%s\n' "${REMOTE_PREFIX}" > "${SB_OPT}/${RELEASE_MARKER}"
    touch "${SB_UNIT}"
    mkdir -p "${SB_VARLIB}/docker-volumes/postgres-data"
    echo "precious" > "${SB_VARLIB}/docker-volumes/postgres-data/data.bin"
}

make_foreign_tree() {
    rm -rf "${SB_OPT}"
    mkdir -p "${SB_OPT}/scripts"
    echo "pre-existing install" > "${SB_OPT}/Dockerfile"
    printf '%s\n' "hada-b-deploy-11111111111111" > "${SB_OPT}/${RELEASE_MARKER}"
    mkdir -p "${SB_VARLIB}/docker-volumes/postgres-data"
    echo "precious" > "${SB_VARLIB}/docker-volumes/postgres-data/data.bin"
}

reset_tracking() {
    CREATED_CONTAINERS=()
    CREATED_VOLUMES=()
    CREATED_NETWORKS=()
    CREATED_IMAGES=()
    UNIT_INSTALLED=0
    SUPERVISOR_STARTED=0
    COMPOSE_UP_DONE=0
    OPT_HADA_CREATED=0
    ENV_CREATED=0
}

# ---------------------------------------------------------------------------
# Test 1: Gate 3 verification failure -> rollback removes this run's
# incomplete release; next run's Gate 2 is unblocked
# ---------------------------------------------------------------------------
make_this_run_tree
reset_tracking
OPT_HADA_CREATED=1
UNIT_INSTALLED=1
: > "${HADA_MOCK_SSH_LOG}"

bounded_rollback >"${TEMP_DIR}/rb1.out" 2>&1 || true

if [[ ! -e "${SB_OPT}" ]]; then
    assert_pass "Gate 3 failure: incomplete /opt/hada release removed (next run unblocked)"
else
    assert_fail "Gate 3 failure: /opt/hada still present — next run permanently blocked"
fi
if [[ ! -e "${SB_UNIT}" ]]; then
    assert_pass "Gate 3 failure: unit installed by this run removed"
else
    assert_fail "Gate 3 failure: unit not removed"
fi
if [[ -f "${SB_VARLIB}/docker-volumes/postgres-data/data.bin" ]]; then
    assert_pass "/var/lib/hada data preserved after Gate 3 rollback"
else
    assert_fail "/var/lib/hada data LOST after Gate 3 rollback"
fi
if mock_remote_decode_log | grep -Eq 'compose .*down|systemctl stop'; then
    assert_fail "Gate 3 rollback touched compose/services (never started)"
else
    assert_pass "Gate 3 rollback issued no compose/service commands"
fi

# ---------------------------------------------------------------------------
# Test 2: Gate 4 failure (env provisioned) is recoverable the same way
# ---------------------------------------------------------------------------
make_this_run_tree
echo "SECRETS" > "${SB_OPT}/.env"
reset_tracking
OPT_HADA_CREATED=1
UNIT_INSTALLED=1
ENV_CREATED=1
: > "${HADA_MOCK_SSH_LOG}"

bounded_rollback >"${TEMP_DIR}/rb2.out" 2>&1 || true

if [[ ! -e "${SB_OPT}" ]]; then
    assert_pass "Gate 4 failure: this run's release (incl. its .env) removed — recoverable"
else
    assert_fail "Gate 4 failure: /opt/hada left behind — next run blocked"
fi
if [[ -f "${SB_VARLIB}/docker-volumes/postgres-data/data.bin" ]]; then
    assert_pass "/var/lib/hada data preserved after Gate 4 rollback"
else
    assert_fail "/var/lib/hada data LOST after Gate 4 rollback"
fi

# ---------------------------------------------------------------------------
# Test 3: pre-existing installation NEVER modified (OPT_HADA_CREATED=0)
# ---------------------------------------------------------------------------
make_foreign_tree
reset_tracking          # OPT_HADA_CREATED=0 — this run created nothing
: > "${HADA_MOCK_SSH_LOG}"

bounded_rollback >"${TEMP_DIR}/rb3.out" 2>&1 || true

if [[ -f "${SB_OPT}/Dockerfile" ]] && grep -q 'pre-existing install' "${SB_OPT}/Dockerfile"; then
    assert_pass "pre-existing installation untouched when this run created nothing"
else
    assert_fail "pre-existing installation modified or removed"
fi
if [[ ! -s "${HADA_MOCK_SSH_LOG}" ]]; then
    assert_pass "zero remote commands issued for pre-existing-tree rollback"
else
    assert_fail "rollback issued remote commands despite creating nothing"
fi

# ---------------------------------------------------------------------------
# Test 4: marker mismatch refusal — even if OPT_HADA_CREATED were forced on,
# the remote guard preserves a tree whose marker belongs to another run
# ---------------------------------------------------------------------------
make_foreign_tree
reset_tracking
OPT_HADA_CREATED=1      # adversarial: flag forced on
: > "${HADA_MOCK_SSH_LOG}"

bounded_rollback >"${TEMP_DIR}/rb4.out" 2>&1 || true

if [[ -f "${SB_OPT}/Dockerfile" ]]; then
    assert_pass "marker-mismatch guard preserved a foreign tree despite forced flag"
else
    assert_fail "foreign tree removed despite marker belonging to another run"
fi
if mock_remote_decode_log | grep -q 'REFUSED: release marker belongs to a different run'; then
    assert_pass "remote guard explicitly refused on marker mismatch"
else
    assert_fail "no explicit marker-mismatch refusal recorded"
fi

# ---------------------------------------------------------------------------
# Test 5: after services started, the tree is preserved (no release removal)
# ---------------------------------------------------------------------------
make_this_run_tree
reset_tracking
OPT_HADA_CREATED=1
COMPOSE_UP_DONE=1
CREATED_CONTAINERS=("hada-m1-postgres-1")
: > "${HADA_MOCK_SSH_LOG}"

bounded_rollback >"${TEMP_DIR}/rb5.out" 2>&1 || true

if [[ -f "${SB_OPT}/Dockerfile" ]]; then
    assert_pass "after services started, /opt/hada release is preserved"
else
    assert_fail "release removed even though services had started"
fi

# ---------------------------------------------------------------------------
# Test 6: static guard — no rollback branch can ever delete /var/lib/hada
# ---------------------------------------------------------------------------
RB_SRC="$(sed -n '/^bounded_rollback()/,/^}/p' "${RUNNER}")"
if grep -q "rm -rf.*HADA_STATE_ROOT\|rm -rf /var/lib/hada" <<<"${RB_SRC}"; then
    assert_fail "bounded_rollback contains a /var/lib/hada deletion path"
else
    assert_pass "bounded_rollback contains no /var/lib/hada deletion path (static)"
fi
if grep -q "sudo -n rm -rf -- \\\\\"\\\${D}\\\\\"" <<<"${RB_SRC}" || grep -q 'rm -rf -- ' <<<"${RB_SRC}"; then
    if grep -B4 'rm -rf -- ' <<<"${RB_SRC}" | grep -q 'marker'; then
        assert_pass "the only recursive removal in rollback is marker-guarded"
    else
        assert_fail "recursive removal in rollback is not marker-guarded"
    fi
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Recoverable-installation test results"
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
