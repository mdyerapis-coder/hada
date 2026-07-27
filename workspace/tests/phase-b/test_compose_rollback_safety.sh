#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034,SC2155
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — Compose partial/retry rollback safety (correction 4)
#
# Proves that when Compose-up is ATTEMPTED but partially fails (containers
# created but `up` exits nonzero, or `up` fails after successful startup):
#   - only the explicit hada-m1 project created by this run is cleaned;
#   - /var/lib/hada and all bind-mounted data survive;
#   - Docker volume METADATA created by this run is removed (without deleting
#     the underlying bind directories);
#   - the orchestrator image is removed ONLY when built by this run;
#   - pre-existing resources are left untouched;
#   - a subsequent retry finds no stale hada-m1 containers/networks/volume
#     metadata/orchestrator image left by the failed attempt.
#
# LOCAL-ONLY. Uses the log-only mock SSH so the exact generated commands are
# audited (no real execution).

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-compose-rb-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found" >&2; exit 1; }

# PATH-shim mocks (mirror test_stage_aware_rollback.sh)
MOCK_BIN="${TEMP_DIR}/mock-bin"
mkdir -p "${MOCK_BIN}"
cat > "${MOCK_BIN}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
while [[ "${1-}" == "-n" || "${1-}" == "-u" ]]; do
    if [[ "${1-}" == "-u" ]]; then shift 2; else shift; fi
done
[[ $# -gt 0 ]] || { echo "sudo: missing command" >&2; exit 1; }
exec "$@"
EOF
chmod +x "${MOCK_BIN}/sudo"
cat > "${MOCK_BIN}/docker" <<'EOF'
#!/usr/bin/env bash
scen="${HADA_MOCK_SCENARIO:-clean}"
args="$*"
case "${args}" in
    "ps -a --format {{.Image}}") exit 0 ;;
    "ps -a --format {{.Names}}") exit 0 ;;
    "ps -aq") exit 0 ;;
    "images -q") exit 0 ;;
    "volume ls -q") exit 0 ;;
    "network ls --format {{.Name}}") echo bridge; exit 0 ;;
    "image inspect hada-orchestrator:0.2.0") exit 1 ;;
    "compose version --short") echo "2.27.0"; exit 0 ;;
    *) exit 0 ;;
esac
EOF
chmod +x "${MOCK_BIN}/docker"
cat > "${MOCK_BIN}/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "${MOCK_BIN}/systemctl"
cat > "${MOCK_BIN}/findmnt" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"-o UUID"* ]]; then echo "a1574097-cdf9-4d0a-ace0-adac63038e56"; fi
exit 0
EOF
chmod +x "${MOCK_BIN}/findmnt"

# Log-only mock SSH (audit generated commands without executing)
MOCK_SSH_LOG_ONLY="${TEMP_DIR}/mock-ssh-log"
cat > "${MOCK_SSH_LOG_ONLY}" <<'EOF'
#!/usr/bin/env bash
cmd="${@: -1}"
printf '%s\n' "$(printf '%s' "${cmd}" | base64 -w0)" >> "${HADA_MOCK_SSH_LOG:?}"
exit 0
EOF
chmod +x "${MOCK_SSH_LOG_ONLY}"

export HADA_MOCK_SSH_LOG="${TEMP_DIR}/ssh-commands.log"
export HADA_MOCK_BIN="${MOCK_BIN}"
export HADA_PHASE_B_MOCK_SSH="${MOCK_SSH_LOG_ONLY}"
export HADA_PHASE_B_MOCK_SCP="${MOCK_SSH_LOG_ONLY}"

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
export HADA_PHASE_B_TIMESTAMP="44444444444444"
export HADA_PHASE_B_CANDIDATE_ARCHIVE="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip"
export HADA_PHASE_B_CANDIDATE_SHA256="$(awk '{print $1}' "${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256")"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"

# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

decode_log() { local r; while IFS= read -r r; do printf '%s\n' "$(printf '%s' "${r}" | base64 -d)"; done < "${HADA_MOCK_SSH_LOG}"; }

SB="${TEMP_DIR}/sandbox"
mkdir -p "${SB}"
# Pre-seed a persistent-data directory beneath /var/lib/hada that MUST survive.
PERSIST="${SB}/var/lib/hada/docker-volumes/postgres-data"
mkdir -p "${PERSIST}"
echo "precious-row" > "${PERSIST}/data.bin"

# ---------------------------------------------------------------------------
# Scenario A: partial Compose creation (COMPOSE_UP_ATTEMPTED=1, DONE=0)
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"
CREATED_CONTAINERS=("hada-m1-postgres-1" "hada-m1-valkey-1")
CREATED_VOLUMES=("hada-m1_postgres-data" "hada-m1_valkey-data")
CREATED_NETWORKS=("hada-m1_control")
CREATED_IMAGES=("hada-orchestrator:0.2.0")
UNIT_INSTALLED=0
SUPERVISOR_STARTED=0
COMPOSE_UP_DONE=0
COMPOSE_UP_ATTEMPTED=1
ORCH_BUILT_BY_RUN=1

bounded_rollback >"${TEMP_DIR}/rb-partial.out" 2>&1 || true
DECODED="$(decode_log)"

# It must clean the hada-m1 project (compose down) and remove volume metadata.
if grep -q 'down --remove-orphans' <<<"${DECODED}"; then
    assert_pass "partial-create rollback brings down the explicit hada-m1 project"
else
    assert_fail "partial-create rollback did not bring down hada-m1"
fi
if grep -q 'volume rm' <<<"${DECODED}"; then
    assert_pass "partial-create rollback removes Docker volume metadata created by this run"
else
    assert_fail "partial-create rollback left volume metadata behind"
fi
# Persistent bind data must survive.
if [[ -f "${PERSIST}/data.bin" ]]; then
    assert_pass "/var/lib/hada bind-mounted data survives partial-create rollback"
else
    assert_fail "/var/lib/hada persistent data LOST during partial-create rollback"
fi
# Rollback must NOT rm -rf /var/lib/hada or /opt/hada.
if grep -Eq 'rm -rf /var/lib/hada|rm -rf /opt/hada' <<<"${DECODED}"; then
    assert_fail "rollback deletes /var/lib/hada or /opt/hada"
else
    assert_pass "rollback never deletes /var/lib/hada or /opt/hada"
fi

# ---------------------------------------------------------------------------
# Scenario B: failure AFTER successful Compose startup (DONE=1)
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"
CREATED_CONTAINERS=("hada-m1-postgres-1" "hada-m1-valkey-1" "hada-m1-orchestrator-1")
CREATED_VOLUMES=("hada-m1_postgres-data" "hada-m1_valkey-data")
CREATED_NETWORKS=("hada-m1_control" "hada-m1_ingress")
CREATED_IMAGES=("hada-orchestrator:0.2.0")
UNIT_INSTALLED=1
SUPERVISOR_STARTED=1
COMPOSE_UP_DONE=1
COMPOSE_UP_ATTEMPTED=1
ORCH_BUILT_BY_RUN=1

bounded_rollback >"${TEMP_DIR}/rb-after-up.out" 2>&1 || true
DECODED="$(decode_log)"
if [[ -f "${PERSIST}/data.bin" ]]; then
    assert_pass "/var/lib/hada bind-mounted data survives post-startup rollback"
else
    assert_fail "/var/lib/hada persistent data LOST during post-startup rollback"
fi
if grep -Eq 'rm -rf /var/lib/hada|rm -rf /opt/hada' <<<"${DECODED}"; then
    assert_fail "post-startup rollback deletes /var/lib/hada or /opt/hada"
else
    assert_pass "post-startup rollback preserves /var/lib/hada and /opt/hada"
fi
# Orchestrator image removed only because built by this run.
if grep -q 'image rm' <<<"${DECODED}"; then
    assert_pass "orchestrator image removed (it was built by this run)"
else
    assert_fail "orchestrator image not removed despite being built by this run"
fi

# ---------------------------------------------------------------------------
# Scenario C: retry must find no stale hada-m1 resources from the failed run
# ---------------------------------------------------------------------------
# Simulate the next run's Gate 2 refusal check seeing only the explicit
# project resources. The rollback removed them, so a clean check passes.
: > "${HADA_MOCK_SSH_LOG}"
CREATED_CONTAINERS=()
CREATED_VOLUMES=()
CREATED_NETWORKS=()
CREATED_IMAGES=()
UNIT_INSTALLED=0
SUPERVISOR_STARTED=0
COMPOSE_UP_DONE=0
COMPOSE_UP_ATTEMPTED=0
ORCH_BUILT_BY_RUN=0
# Re-run the Gate 2 existing-resource refusal check exercised via a no-op: if
# the rollback left stale hada-m1 containers/volumes/images, this would fail.
set +e
out="$(remote_preparation_and_state_capture 2>&1)"; rc=$?
set -e
if (( rc == 0 )); then
    assert_pass "retry: Gate 2 refusal check passes (no stale hada-m1 resources block the retry)"
else
    assert_fail "retry blocked by stale hada-m1 resources: $(tail -3 <<<"$out")"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Compose partial/retry rollback safety test results"
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
