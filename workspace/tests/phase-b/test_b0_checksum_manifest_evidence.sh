#!/usr/bin/env bash
# shellcheck disable=SC2034
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — v4 B0 checksum, versioned manifest, and evidence-binding tests
#
# LOCAL-ONLY: no SSH, no SCP, no Docker daemon, no Phase B0 execution.
# Exercises the exact v4 checksum gate, the versioned v4 manifest, and the
# Phase B Gate 0f evidence lock.
#
set -Euo pipefail

PASS_COUNT=0
FAIL_COUNT=0

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
B0_RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b0-v4-preflight.sh"
PHASEB_RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
V4_ZIP="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip"
V4_SHA="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256"
V4_MANIFEST="${DEPLOY_ROOT}/deploy-v4/candidate-manifest-v4.txt"
EXPECTED_V4="d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac"

# ---------------------------------------------------------------------------
# 1. CHECKSUM GATE — exact gate, executed from the deployment root
# ---------------------------------------------------------------------------
TMPX="$(mktemp -d /tmp/hada-b0-ck-XXXXXX)"

# Source the B0 runner as a test library (no SSH, no auto-run).
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${V4_ZIP}" \
  HADA_PHASE_B0_CANDIDATE_SHA256_FILE="${V4_SHA}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_checksum '${TMPX}'"
rc=$?
if [[ ${rc} -eq 0 ]]; then
    assert_pass "checksum gate passes for the locked v4 archive (from deployment root)"
else
    assert_fail "checksum gate unexpectedly failed for the locked v4 archive"
fi

# Wrong archive hash (tampered copy) must fail before any remote contact.
BAD_ZIP="${TMPX}/bad.zip"
cp "${V4_ZIP}" "${BAD_ZIP}"
printf 'x' >> "${BAD_ZIP}"
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${BAD_ZIP}" \
  HADA_PHASE_B0_CANDIDATE_SHA256_FILE="${V4_SHA}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_checksum '${TMPX}'"
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "wrong archive hash fails the checksum gate (before SSH)"
else
    assert_fail "wrong archive hash did NOT fail the checksum gate"
fi

# Wrong SHA file (altered expected hash) must fail.
BAD_SHA="${TMPX}/bad.sha256"
printf '0000000000000000000000000000000000000000000000000000000000000000  HADA-M1-gcp-candidate-v4.zip\n' > "${BAD_SHA}"
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${V4_ZIP}" \
  HADA_PHASE_B0_CANDIDATE_SHA256_FILE="${BAD_SHA}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_checksum '${TMPX}'"
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "wrong SHA file fails the checksum gate (before SSH)"
else
    assert_fail "wrong SHA file did NOT fail the checksum gate"
fi

# ---------------------------------------------------------------------------
# 2. VERSIONED MANIFEST
# ---------------------------------------------------------------------------
EXTRACT="${TMPX}/extract"
mkdir -p "${EXTRACT}"
( cd "${EXTRACT}" && unzip -q "${V4_ZIP}" )
CAND_ROOT="${EXTRACT}/HADA-M1-durable-orchestrator"

# 2a. Untouched v4 extraction passes.
HADA_PHASE_B0_DEPLOY_DIR="${DEPLOY_ROOT}" \
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${V4_ZIP}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_manifest '${CAND_ROOT}' '${TMPX}'"
rc=$?
if [[ ${rc} -eq 0 ]]; then
    assert_pass "untouched v4 extraction passes the versioned manifest gate"
else
    assert_fail "untouched v4 extraction FAILED the versioned manifest gate"
fi

# 2b. One modified extracted file fails.
MOD="${CAND_ROOT}/README.md"
echo "tampered" >> "${MOD}"
HADA_PHASE_B0_DEPLOY_DIR="${DEPLOY_ROOT}" \
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${V4_ZIP}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_manifest '${CAND_ROOT}' '${TMPX}'"
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "one modified extracted file fails the versioned manifest gate"
else
    assert_fail "modified extracted file did NOT fail the manifest gate"
fi

# restore
( cd "${EXTRACT}" && unzip -oq "${V4_ZIP}" )

# 2c. The old v1 manifest cannot satisfy the v4 manifest gate.
# Generate the v1 manifest directly from the v1 candidate (which is in the
# repo/bundle) so this required security-gate assertion ALWAYS executes.
V1_ZIP="${DEPLOY_ROOT}/HADA-M1-gcp-candidate.zip"
V1_EXTRACT="${TMPX}/v1-extract"
mkdir -p "${V1_EXTRACT}"
( cd "${V1_EXTRACT}" && unzip -q "${V1_ZIP}" )
V1_ROOT="${V1_EXTRACT}/HADA-M1-durable-orchestrator"
V1_MANIFEST="${TMPX}/candidate-manifest-v1.txt"
( cd "${V1_ROOT}" && find . -type f -not -path '*/.git/*' | sort | sed 's|^\./||' | xargs sha256sum ) > "${V1_MANIFEST}"
# Point the B0 manifest var at the generated v1 manifest and verify against the
# v4 extracted tree. The v1 file set/hashes differ from v4, so it must fail.
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" MANIFEST_FILE="${V1_MANIFEST}" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${V4_ZIP}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_manifest '${CAND_ROOT}' '${TMPX}'"
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "stale v1 manifest cannot satisfy the v4 manifest gate"
else
    assert_fail "stale v1 manifest incorrectly satisfied the v4 manifest gate"
fi
rm -rf "${V1_EXTRACT}"

# 2d. Missing v4 manifest fails before remote contact.
HADA_PHASE_B0_TEST_LIB=1 RUN_DIR="${TMPX}" MANIFEST_FILE="${TMPX}/does-not-exist.txt" \
  HADA_PHASE_B0_CANDIDATE_ARCHIVE="${V4_ZIP}" \
  bash -c "source '${B0_RUNNER}'; b0_verify_candidate_manifest '${CAND_ROOT}' '${TMPX}'"
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "missing v4 manifest fails the manifest gate (before SSH)"
else
    assert_fail "missing v4 manifest did NOT fail the manifest gate"
fi

# ---------------------------------------------------------------------------
# 3. PHASE B GATE 0f — evidence lock
# ---------------------------------------------------------------------------
# Build a synthetic v4 evidence directory with the correct identity and all
# required PASS files (no remote command issued).
B0E="${TMPX}/b0-evidence-v4"
mkdir -p "${B0E}"
printf '%s\n' "${EXPECTED_V4}" > "${B0E}/candidate-sha256.txt"
{
    echo "project=api-intergrations-501314"
    echo "zone=australia-southeast1-b"
    echo "vm=hada-control"
} > "${B0E}/target-identity.txt"
echo "PASS: Compose version requirement: PASS" > "${B0E}/compose-version-check.txt"
echo "PASS: Compose JSON render: PASS" > "${B0E}/compose-render-check.txt"
echo "PASS: Port assertion: PASS" > "${B0E}/port-assertion-check.txt"
echo "PASS: Volume assertion: PASS" > "${B0E}/volume-assertion-check.txt"
echo "PASS: Docker state unchanged during preflight" > "${B0E}/state-check.txt"
{
    echo "overall-result: PASS"
    echo "failed-gate: none"
    echo "after-state-capture-succeeded: YES"
    echo "container-state-changed: NO"
    echo "image-state-changed: NO"
    echo "remote-cleanup-result: PASS"
    echo "candidate-checksum: PASS"
    echo "candidate-manifest: PASS"
    echo "compose-version: PASS"
    echo "compose-render: PASS"
    echo "port-assertion: PASS"
    echo "volume-assertion: PASS"
    echo "container-state-unchanged: PASS"
    echo "image-state-unchanged: PASS"
    echo "candidate-sha256: ${EXPECTED_V4}"
    echo "project: api-intergrations-501314"
    echo "zone: australia-southeast1-b"
    echo "vm: hada-control"
} > "${B0E}/preflight-summary.txt"

# Run the Phase B runner's Gate 0f via a controlled invocation that records
# whether a remote command was attempted (DEPLOY_EXECUTE guard).
REMOTE_ATTEMPTED=0
EXEC_LOG="${TMPX}/exec.log"
# Intercept gcloud by prepending a fake on PATH.
FAKEBIN="${TMPX}/fakebin"
mkdir -p "${FAKEBIN}"
cat > "${FAKEBIN}/gcloud" <<'SH'
#!/usr/bin/env bash
echo "REMOTE_ATTEMPT: $*" >> "${EXEC_LOG:-/dev/stderr}"
exit 0
SH
chmod +x "${FAKEBIN}/gcloud"

# The Phase B runner exposes verify_phase_b0_evidence() (top-level, test-lib
# callable). We source the runner in test-lib mode and call it directly.
HADA_PHASE_B_TEST_LIB=1 HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}" \
  HADA_PHASE_B0_EVIDENCE_DIR="${B0E}" \
  PATH="${FAKEBIN}:${PATH}" EXEC_LOG="${EXEC_LOG}" \
  DEPLOY_EXECUTE=0 \
  bash -c "
  source '${PHASEB_RUNNER}'
  verify_phase_b0_evidence; rc=\$?
  exit \$rc
  " 2>/dev/null
  GATE0F_RC=$?
if [[ ${GATE0F_RC} -eq 0 ]]; then
    assert_pass "synthetic v4 evidence with correct identity + all PASS files is accepted by Phase B Gate 0f"
else
    assert_fail "synthetic v4 evidence was REJECTED by Phase B Gate 0f (rc=${GATE0F_RC})"
fi
if [[ ! -s "${EXEC_LOG}" ]]; then
    assert_pass "no remote command attempted during Gate 0f (DEPLOY_EXECUTE=0 honored)"
else
    assert_fail "remote command was attempted during Gate 0f: $(cat "${EXEC_LOG}")"
fi

# 3b. Stale v1 Phase B0 evidence (only a PASS state-check.txt, no v4 files)
#     must be rejected.
B0E1="${TMPX}/b0-evidence-v1"
mkdir -p "${B0E1}"
echo "PASS: Docker state unchanged during preflight" > "${B0E1}/state-check.txt"
HADA_PHASE_B_TEST_LIB=1 HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}" \
  HADA_PHASE_B0_EVIDENCE_DIR="${B0E1}" \
  PATH="${FAKEBIN}:${PATH}" EXEC_LOG="${EXEC_LOG}" \
  DEPLOY_EXECUTE=0 \
  bash -c "
source '${PHASEB_RUNNER}'
verify_phase_b0_evidence; rc=\$?
exit \$rc
" 2>/dev/null
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "stale v1 Phase B0 evidence (no v4 files) is REJECTED by Gate 0f"
else
    assert_fail "stale v1 Phase B0 evidence was incorrectly ACCEPTED by Gate 0f"
fi

# Complete-looking v2 and v3 evidence must also be rejected by candidate hash.
for stale_version in v2 v3; do
    STALE_DIR="${TMPX}/b0-evidence-${stale_version}"
    cp -a "${B0E}" "${STALE_DIR}"
    if [[ "${stale_version}" == "v2" ]]; then
        STALE_HASH="$(awk 'NR==1{print $1}' "${DEPLOY_ROOT}/deploy-v2/HADA-M1-gcp-candidate-v2.zip.sha256")"
    else
        STALE_HASH="$(awk 'NR==1{print $1}' "${DEPLOY_ROOT}/deploy-v3/HADA-M1-gcp-candidate-v3.zip.sha256")"
    fi
    printf '%s\n' "${STALE_HASH}" >"${STALE_DIR}/candidate-sha256.txt"
    HADA_PHASE_B_TEST_LIB=1 HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}" \
      HADA_PHASE_B0_EVIDENCE_DIR="${STALE_DIR}" DEPLOY_EXECUTE=0 \
      bash -c "source '${PHASEB_RUNNER}'; verify_phase_b0_evidence"
    rc=$?
    if [[ ${rc} -ne 0 ]]; then
        assert_pass "stale ${stale_version} Phase B0 evidence is REJECTED by Gate 0f"
    else
        assert_fail "stale ${stale_version} Phase B0 evidence was incorrectly ACCEPTED"
    fi
done

# 3c. Malformed evidence (FAIL line or duplicate identity) must be REJECTED.
# 3c-i: a check file containing a FAIL line must be rejected.
B0E2="${TMPX}/b0-evidence-malformed-fail"
mkdir -p "${B0E2}"
printf '%s\n' "${EXPECTED_V4}" > "${B0E2}/candidate-sha256.txt"
{ echo "project=api-intergrations-501314"; echo "zone=australia-southeast1-b"; echo "vm=hada-control"; } > "${B0E2}/target-identity.txt"
echo "FAIL: Compose version requirement: FAIL" > "${B0E2}/compose-version-check.txt"
echo "PASS: Compose JSON render: PASS" > "${B0E2}/compose-render-check.txt"
echo "PASS: Port assertion: PASS" > "${B0E2}/port-assertion-check.txt"
echo "PASS: Volume assertion: PASS" > "${B0E2}/volume-assertion-check.txt"
echo "PASS: Docker state unchanged during preflight" > "${B0E2}/state-check.txt"
{ echo "candidate-checksum: PASS"; echo "candidate-manifest: PASS"; echo "compose-version: PASS"; echo "compose-render: PASS"; echo "port-assertion: PASS"; echo "volume-assertion: PASS"; echo "container-state-unchanged: PASS"; echo "image-state-unchanged: PASS"; echo "candidate-sha256: ${EXPECTED_V4}"; } > "${B0E2}/preflight-summary.txt"
HADA_PHASE_B_TEST_LIB=1 HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}" \
  HADA_PHASE_B0_EVIDENCE_DIR="${B0E2}" \
  PATH="${FAKEBIN}:${PATH}" EXEC_LOG="${EXEC_LOG}" \
  DEPLOY_EXECUTE=0 \
  bash -c "source '${PHASEB_RUNNER}'; verify_phase_b0_evidence; rc=\$?; exit \$rc" 2>/dev/null
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "malformed evidence with a FAIL line is REJECTED by Gate 0f"
else
    assert_fail "malformed evidence with a FAIL line was incorrectly ACCEPTED by Gate 0f"
fi

# 3c-ii: duplicate identity field must be rejected.
B0E3="${TMPX}/b0-evidence-dup-ident"
mkdir -p "${B0E3}"
printf '%s\n' "${EXPECTED_V4}" > "${B0E3}/candidate-sha256.txt"
{ echo "project=api-intergrations-501314"; echo "project=attacker-project"; echo "zone=australia-southeast1-b"; echo "vm=hada-control"; } > "${B0E3}/target-identity.txt"
echo "PASS: Compose version requirement: PASS" > "${B0E3}/compose-version-check.txt"
echo "PASS: Compose JSON render: PASS" > "${B0E3}/compose-render-check.txt"
echo "PASS: Port assertion: PASS" > "${B0E3}/port-assertion-check.txt"
echo "PASS: Volume assertion: PASS" > "${B0E3}/volume-assertion-check.txt"
echo "PASS: Docker state unchanged during preflight" > "${B0E3}/state-check.txt"
{ echo "candidate-checksum: PASS"; echo "candidate-manifest: PASS"; echo "compose-version: PASS"; echo "compose-render: PASS"; echo "port-assertion: PASS"; echo "volume-assertion: PASS"; echo "container-state-unchanged: PASS"; echo "image-state-unchanged: PASS"; echo "candidate-sha256: ${EXPECTED_V4}"; } > "${B0E3}/preflight-summary.txt"
HADA_PHASE_B_TEST_LIB=1 HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}" \
  HADA_PHASE_B0_EVIDENCE_DIR="${B0E3}" \
  PATH="${FAKEBIN}:${PATH}" EXEC_LOG="${EXEC_LOG}" \
  DEPLOY_EXECUTE=0 \
  bash -c "source '${PHASEB_RUNNER}'; verify_phase_b0_evidence; rc=\$?; exit \$rc" 2>/dev/null
rc=$?
if [[ ${rc} -ne 0 ]]; then
    assert_pass "evidence with duplicate identity field is REJECTED by Gate 0f"
else
    assert_fail "evidence with duplicate identity field was incorrectly ACCEPTED by Gate 0f"
fi

rm -rf "${TMPX}"

echo ""
echo "============================================"
echo "v4 B0 checksum / manifest / evidence-binding test results"
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
