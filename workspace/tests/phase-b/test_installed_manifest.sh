#!/usr/bin/env bash
#
# HADA M1 Phase B — Installed-manifest integration tests (cross-gate
# correction 1)
#
# Executes the runner's REAL Gate 1 manifest generation and the REAL Gate 3e
# verify_installed_tree remote command inside a local sandbox, proving:
#   1. a byte-identical installed app tree AND unit pass;
#   2. a modified app file fails;
#   3. a modified service unit fails (content verification, not existence);
#   4. a missing service unit fails;
#   5. no unavoidable path mismatch remains (identical-content verification
#      passes cleanly, and the unit is verified at its INSTALLED path from a
#      checksum derived from the candidate's scripts/ path).
#
# LOCAL-ONLY. The candidate zip is read (never modified); the mock SSH
# transport executes the exact generated remote command in the sandbox.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-mf-test-XXXXXX)"
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
export HADA_PHASE_B_TIMESTAMP="88888888888888"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

# ---------------------------------------------------------------------------
# Real Gate 1: extract the locked candidate, generate BOTH manifests
# ---------------------------------------------------------------------------
verify_and_extract_candidate >"${TEMP_DIR}/gate1.log" 2>&1 \
    || { echo "FAIL: Gate 1 failed in sandbox" >&2; cat "${TEMP_DIR}/gate1.log" >&2; exit 1; }

[[ -s "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256" ]] \
    && assert_pass "Gate 1 produced candidate-app.sha256" \
    || assert_fail "candidate-app.sha256 missing/empty"
[[ -s "${CANDIDATE_EXTRACT_DIR}/candidate-unit.sha256" ]] \
    && assert_pass "Gate 1 produced candidate-unit.sha256" \
    || assert_fail "candidate-unit.sha256 missing/empty"

# The app manifest must NOT contain the unit; the unit checksum must carry
# the INSTALLED path — this removes the old guaranteed path mismatch.
if grep -q 'hada-supervisor.service' "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256"; then
    assert_fail "app manifest still contains the service unit (path mismatch remains)"
else
    assert_pass "app manifest excludes the service unit (no path mismatch possible)"
fi
if grep -q ' /etc/systemd/system/hada-supervisor.service$' "${CANDIDATE_EXTRACT_DIR}/candidate-unit.sha256"; then
    assert_pass "unit checksum line carries the installed path"
else
    assert_fail "unit checksum line does not carry the installed path"
fi

# ---------------------------------------------------------------------------
# Sandbox installation helper: install the candidate tree byte-identically
# ---------------------------------------------------------------------------
SB_OPT="${HADA_SANDBOX}/opt/hada"
SB_UNIT="${HADA_SANDBOX}/etc/systemd/system/hada-supervisor.service"
SB_REMOTE="${HADA_SANDBOX}${REMOTE_DIR}"

install_sandbox_tree() {
    rm -rf "${SB_OPT}" "${SB_UNIT}" "${SB_REMOTE}"
    mkdir -p "${SB_OPT}" "$(dirname "${SB_UNIT}")" "${SB_REMOTE}"
    # Copy the COMPLETE candidate payload (matches the runner's atomic install
    # of the full verified staging tree).
    cp -a "${CANDIDATE_ROOT}/pyproject.toml" "${SB_OPT}/pyproject.toml"
    cp -a "${CANDIDATE_ROOT}/README.md" "${SB_OPT}/README.md"
    cp -a "${CANDIDATE_ROOT}/Dockerfile" "${SB_OPT}/Dockerfile"
    cp -a "${CANDIDATE_ROOT}/src" "${SB_OPT}/src"
    cp -a "${CANDIDATE_ROOT}/config" "${SB_OPT}/config"
    cp -a "${CANDIDATE_ROOT}/deploy" "${SB_OPT}/deploy"
    cp -a "${CANDIDATE_ROOT}/scripts" "${SB_OPT}/scripts"
    cp "${CANDIDATE_ROOT}/scripts/hada-supervisor.service" "${SB_UNIT}"
    cp "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256" "${SB_REMOTE}/candidate-app.sha256"
    cp "${CANDIDATE_EXTRACT_DIR}/candidate-unit.sha256" "${SB_REMOTE}/candidate-unit.sha256"
}

run_verify() {
    set +e
    verify_installed_tree >"${TEMP_DIR}/verify.out" 2>&1
    local rc=$?
    set -e
    return ${rc}
}

# ---------------------------------------------------------------------------
# Test 1: byte-identical app tree and unit PASS
# ---------------------------------------------------------------------------
install_sandbox_tree
if run_verify; then
    assert_pass "byte-identical app tree and unit pass verification"
else
    assert_fail "byte-identical tree failed verification (unavoidable mismatch remains): $(cat "${TEMP_DIR}/verify.out")"
fi
if grep -q 'unit content-verified' "${TEMP_DIR}/verify.out"; then
    assert_pass "unit was content-verified (not merely existence-checked)"
else
    assert_fail "no unit content-verification message in output"
fi

# ---------------------------------------------------------------------------
# Test 2: modified app file FAILS
# ---------------------------------------------------------------------------
install_sandbox_tree
printf '\n# tampered\n' >> "${SB_OPT}/config/hada.yaml"
if run_verify; then
    assert_fail "modified app file passed verification"
else
    assert_pass "modified app file fails verification"
fi

# ---------------------------------------------------------------------------
# Test 3: modified service unit FAILS (content verification)
# ---------------------------------------------------------------------------
install_sandbox_tree
printf '\n# tampered unit\n' >> "${SB_UNIT}"
if run_verify; then
    assert_fail "modified service unit passed verification (existence-only check)"
else
    assert_pass "modified service unit fails verification (content-verified)"
fi

# ---------------------------------------------------------------------------
# Test 4: missing service unit FAILS
# ---------------------------------------------------------------------------
install_sandbox_tree
rm -f "${SB_UNIT}"
if run_verify; then
    assert_fail "missing service unit passed verification"
else
    assert_pass "missing service unit fails verification"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Installed-manifest integration test results"
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
