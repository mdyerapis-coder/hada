#!/usr/bin/env bash
#
# HADA M1 Phase B — Cross-gate happy-path integration test (cross-gate
# corrections 2 and 4)
#
# Runs the runner's REAL gate functions as ONE workflow against a mocked
# fresh host:
#
#   Gate 1: locked candidate extracted; app + unit manifests generated;
#   Gate 2: clean-host refusal check, mount UUID, BEFORE state, temp dir;
#   Gate 3: payload staged (mock SCP), staging manifest-verified, dirs +
#           release marker, atomic install, installed checksums verified,
#           provision-secrets executed WITHOUT leaking values;
#   Gate 4: .env validated (root:hada 0640 mocked, values checked, none
#           printed);
#   Gate 5: Compose JSON rendered (fixture) and structurally validated.
#
# This proves a fresh host proceeds Gate 2 -> Gate 4 with NO impossible
# manual intermission, and catches path mismatches / missing handoffs
# between gates. It also proves no secret value appears in any local log,
# evidence file, or the transmitted command stream.
#
# LOCAL-ONLY, fully mocked. The candidate zip is read, never modified.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-hp-test-XXXXXX)"
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
# This happy-path test exercises the COMPLETE runtime payload (v2 candidate).
export HADA_PHASE_B_CANDIDATE_ARCHIVE="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip"
HADA_PHASE_B_CANDIDATE_SHA256="$(awk '{print $1}' "${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256")"
export HADA_PHASE_B_CANDIDATE_SHA256
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
export HADA_PHASE_B_TIMESTAMP="66666666666666"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# v3 fail-closed gate: a locked v4 Phase B0 evidence directory must exist.
export HADA_PHASE_B0_EVIDENCE_DIR="${TEMP_DIR}/evidence/phase-b0/preflight-run-66666666666666"
mkdir -p "${HADA_PHASE_B0_EVIDENCE_DIR}"
printf 'PASS: Docker state unchanged during preflight\n' > "${HADA_PHASE_B0_EVIDENCE_DIR}/state-check.txt"
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
        assert_fail "${name} FAILED (rc=${rc}) — cross-gate handoff broken:"
        tail -15 "${TEMP_DIR}/${name}.log" >&2 || true
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Gates 1 -> 5 as one workflow (fresh mocked host)
# ---------------------------------------------------------------------------
run_gate "gate1-candidate-extraction"  verify_and_extract_candidate
run_gate "gate2-remote-preparation"    remote_preparation_and_state_capture
run_gate "gate3-upload-install"        upload_and_install_application
run_gate "gate4-env-validation"        validate_production_env
run_gate "gate5-compose-render"        render_validate_compose

# ---------------------------------------------------------------------------
# Cross-gate handoff assertions
# ---------------------------------------------------------------------------
SB_OPT="${HADA_SANDBOX}/opt/hada"
SB_UNIT="${HADA_SANDBOX}/etc/systemd/system/hada-supervisor.service"

# Gate 3 must have installed the full application tree
for f in deploy/compose/compose.yaml deploy/compose/compose.gcp.yaml \
         deploy/caddy/Caddyfile.gcp Dockerfile config/hada.yaml \
         scripts/provision-secrets.sh scripts/supervisor.sh \
         scripts/validate-host.sh scripts/container-entrypoint.sh; do
    if [[ -f "${SB_OPT}/${f}" ]]; then
        assert_pass "installed: /opt/hada/${f}"
    else
        assert_fail "missing installed file: /opt/hada/${f}"
    fi
done
[[ -d "${SB_OPT}/src" ]] && assert_pass "installed: /opt/hada/src tree" \
    || assert_fail "missing installed src tree"
[[ -f "${SB_UNIT}" ]] && assert_pass "installed: service unit at /etc/systemd/system" \
    || assert_fail "service unit not installed"
[[ -f "${SB_OPT}/${RELEASE_MARKER}" ]] && assert_pass "release marker stamped by this run" \
    || assert_fail "release marker missing"

# Gate 3f must have provisioned the .env (fresh host -> Gate 4 reachable)
if [[ -f "${SB_OPT}/.env" ]]; then
    assert_pass "provision-secrets created /opt/hada/.env (Gate 4 reachable, no manual intermission)"
else
    assert_fail "no .env provisioned between Gate 3 and Gate 4"
fi
if (( ENV_CREATED == 1 )); then
    assert_pass "runner recorded ENV_CREATED=1 (env created by this run)"
else
    assert_fail "ENV_CREATED not recorded"
fi
if (( OPT_HADA_CREATED == 1 )); then
    assert_pass "runner recorded OPT_HADA_CREATED=1 (tree created by this run)"
else
    assert_fail "OPT_HADA_CREATED not recorded"
fi

# The provisioned DSN must carry the real password, not a *** placeholder
if grep -q ':\*\*\*@' "${SB_OPT}/.env"; then
    assert_fail "provisioned .env still contains the *** DSN placeholder"
else
    assert_pass "provisioned DSN carries the real password (no *** placeholder)"
fi
# The DSN must be consistent with the generated POSTGRES_PASSWORD
PG_VAL="$(grep '^POSTGRES_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
if grep -q "postgresql://hada:${PG_VAL}@postgres:5432/hada" "${SB_OPT}/.env"; then
    assert_pass "provisioned DSN is consistent with POSTGRES_PASSWORD"
else
    assert_fail "provisioned DSN not consistent with POSTGRES_PASSWORD"
fi

# ---------------------------------------------------------------------------
# Secret-leak assertions: no secret value in logs, evidence, or command log
# ---------------------------------------------------------------------------
PG_VAL="$(grep '^POSTGRES_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
VK_VAL="$(grep '^VALKEY_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
GF_VAL="$(grep '^GRAFANA_ADMIN_PASSWORD=' "${SB_OPT}/.env" | head -1 | cut -d= -f2-)"
LEAKED=0
for sec in "${PG_VAL}" "${VK_VAL}" "${GF_VAL}"; do
    [[ -n "${sec}" ]] || continue
    if grep -rF -- "${sec}" "${HADA_PHASE_B_EVIDENCE_DIR}" >/dev/null 2>&1; then LEAKED=1; fi
    for lg in "${TEMP_DIR}"/gate*.log; do
        if grep -qF -- "${sec}" "${lg}" 2>/dev/null; then LEAKED=1; fi
    done
    if mock_remote_decode_log | grep -qF -- "${sec}"; then LEAKED=1; fi
done
if (( LEAKED == 0 )); then
    assert_pass "no secret value found in evidence, gate logs, or transmitted commands"
else
    assert_fail "a provisioned secret value LEAKED into local logs/evidence/commands"
fi

# Secrets never in transmitted command arguments (the command log IS the
# full argv stream sent to the transport)
if mock_remote_decode_log | grep -q 'valkey-cli -a'; then
    assert_fail "valkey-cli -a (secret in argv) found in transmitted commands"
else
    assert_pass "no valkey-cli -a in any transmitted command"
fi

# Gate 5 must have deleted its temporary resolved JSON after validation
LEFTOVER=$(find "${HADA_PHASE_B_EVIDENCE_DIR}" -name 'effective-compose.*.json' | wc -l)
if [[ "${LEFTOVER}" -eq 0 ]]; then
    assert_pass "Gate 5 deleted the temporary resolved Compose JSON"
else
    assert_fail "Gate 5 left ${LEFTOVER} resolved JSON file(s) behind"
fi

# Evidence artifacts from every remote gate step exist (handoffs really ran)
for ev in check-existing-hada.txt verify-hada-mount-uuid.txt stage-release.txt \
          create-dirs.txt install-release.txt verify-install.txt \
          provision-secrets.txt validate-env.txt; do
    if [[ -f "${HADA_PHASE_B_EVIDENCE_DIR}/${ev}" ]]; then
        assert_pass "evidence artifact present: ${ev}"
    else
        assert_fail "evidence artifact missing: ${ev}"
    fi
done

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Cross-gate happy-path (Gates 1-5) results"
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
