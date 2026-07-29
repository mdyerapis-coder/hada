#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034,SC2329,SC2317
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — Mocked stage-aware rollback tests (correction 3)
#
# Proves:
#   1. Existing HADA resources cause immediate refusal with no mutation and
#      ZERO rollback commands (no compose down, no systemctl stop/disable,
#      no unit removal, no docker mutation).
#   2. The Gate 2 existing-resource check is the FIRST remote command —
#      before temp-dir creation or any upload.
#   3. bounded_rollback() with nothing tracked issues zero remote commands
#      (Gate 2 refusal / initial-state failure path).
#   4. bounded_rollback() with tracked resources rolls back exactly those
#      (supervisor stop, compose down WITHOUT -v, unit removal) and never
#      deletes /var/lib/hada or /opt/hada.
#
# No contact with hada-control. The mock SSH transport executes the exact
# generated remote command locally against PATH-shimmed sudo/docker/
# systemctl/findmnt mocks (Gate 2 tests) or logs without executing
# (rollback tests).
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-rb-test-XXXXXX)"
CREATED_TMP_REMOTE=""
cleanup_test() {
    rm -rf "${TEMP_DIR}"
    [[ -n "${CREATED_TMP_REMOTE}" && "${CREATED_TMP_REMOTE}" =~ ^/tmp/hada-b-deploy-[0-9]+$ ]] && rm -rf "${CREATED_TMP_REMOTE}"
    return 0
}
trap cleanup_test EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found: ${RUNNER}" >&2; exit 1; }

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
export HADA_PHASE_B_TIMESTAMP="99999999999999"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"
CREATED_TMP_REMOTE="${REMOTE_DIR}"

# ---------------------------------------------------------------------------
# PATH-shim mocks for the remote host's sudo/docker/systemctl/findmnt
# ---------------------------------------------------------------------------
MOCK_BIN="${TEMP_DIR}/mock-bin"
mkdir -p "${MOCK_BIN}"

cat > "${MOCK_BIN}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
while [[ "${1-}" == "-n" || "${1-}" == "-u" ]]; do
    if [[ "${1-}" == "-u" ]]; then shift 2; else shift; fi
done
[[ "$#" -gt 0 ]] || { echo "sudo: missing command" >&2; exit 1; }
exec "$@"
EOF
chmod +x "${MOCK_BIN}/sudo"

cat > "${MOCK_BIN}/docker" <<'EOF'
#!/usr/bin/env bash
scen="${HADA_MOCK_SCENARIO:-clean}"
args="$*"
case "${args}" in
    "ps -a --format {{.Image}}")
        if [[ "${scen}" == "existing" ]]; then echo "hada-orchestrator:0.2.0"; fi
        exit 0 ;;
    "ps -a --format {{.Names}}") exit 0 ;;
    "ps -aq") exit 0 ;;
    "images -q") exit 0 ;;
    "volume ls -q") exit 0 ;;
    "network ls --format {{.Name}}") echo bridge; exit 0 ;;
    "image inspect hada-orchestrator:0.2.0")
        if [[ "${scen}" == "existing" ]]; then exit 0; fi
        exit 1 ;;
    "compose version --short") echo "2.27.0"; exit 0 ;;
    *) exit 0 ;;
esac
EOF
chmod +x "${MOCK_BIN}/docker"

cat > "${MOCK_BIN}/systemctl" <<'EOF'
#!/usr/bin/env bash
# list-unit-files: report no hada-supervisor unit installed
exit 0
EOF
chmod +x "${MOCK_BIN}/systemctl"

cat > "${MOCK_BIN}/findmnt" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"-o UUID"* ]]; then
    echo "a1574097-cdf9-4d0a-ace0-adac63038e56"
fi
exit 0
EOF
chmod +x "${MOCK_BIN}/findmnt"

# Executing mock SSH: logs one base64 record per command, then executes the
# generated command with the shims on PATH. Rewrite the production install
# root only for execution so a live /opt/hada on the test host cannot make the
# hermetic "clean host" fixture fail; the original command remains in the audit
# log and assertions.
MOCK_SSH_EXEC="${TEMP_DIR}/mock-ssh-exec"
cat > "${MOCK_SSH_EXEC}" <<'EOF'
#!/usr/bin/env bash
cmd="${@: -1}"
printf '%s\n' "$(printf '%s' "${cmd}" | base64 -w0)" >> "${HADA_MOCK_SSH_LOG:?}"
exec_cmd="${cmd//\/opt\/hada/${HADA_MOCK_OPT_HADA:?}}"
PATH="${HADA_MOCK_BIN:?}:${PATH}" exec bash -c "${exec_cmd}"
EOF
chmod +x "${MOCK_SSH_EXEC}"

# Log-only mock SSH (never executes — used for rollback command auditing)
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
export HADA_MOCK_OPT_HADA="${TEMP_DIR}/mock-opt/hada"
# Rollback tests audit the exact generated commands; use the log-only mock
# SSH so every remote command is captured (base64) without executing.
export HADA_PHASE_B_MOCK_SSH="${MOCK_SSH_LOG_ONLY}"
export HADA_PHASE_B_MOCK_SCP="${MOCK_SSH_LOG_ONLY}"

decode_log() {
    local rec
    while IFS= read -r rec; do
        printf '%s\n----\n' "$(printf '%s' "${rec}" | base64 -d)"
    done < "${HADA_MOCK_SSH_LOG}"
}

# ---------------------------------------------------------------------------
# Test 1: existing-resource refusal performs ZERO rollback/mutation commands
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"
export HADA_MOCK_SCENARIO="existing"
SSH_CMD=("${MOCK_SSH_EXEC}")

set +e
remote_preparation_and_state_capture >"${TEMP_DIR}/gate2-existing.stdout" 2>&1
RC=$?
set -e

if [[ ${RC} -ne 0 ]]; then
    assert_pass "existing HADA resources cause immediate refusal (rc=${RC})"
else
    assert_fail "existing HADA resources must cause refusal (got rc=0)"
fi

CMD_COUNT=$(wc -l < "${HADA_MOCK_SSH_LOG}")
if [[ "${CMD_COUNT}" -eq 1 ]]; then
    assert_pass "refusal issued exactly one remote command (the read-only check)"
else
    assert_fail "refusal should issue exactly one remote command (got ${CMD_COUNT})"
fi

DECODED="$(decode_log)"
if grep -Eq 'compose .*down|systemctl (stop|disable)|rm -f /etc/systemd|docker (rm|stop|rmi)|docker volume rm|docker network rm|install -d|mkdir' <<<"${DECODED}"; then
    assert_fail "existing-resource refusal issued mutation/rollback commands"
else
    assert_pass "existing-resource refusal performed zero rollback/mutation commands"
fi

if [[ "${REMOTE_DIR_CREATED}" == "0" ]]; then
    assert_pass "refusal happened before remote temp-dir creation (REMOTE_DIR_CREATED=0)"
else
    assert_fail "remote temp dir must not be created when refusing on existing resources"
fi

# ---------------------------------------------------------------------------
# Test 2: clean host — the existing-resource check is the FIRST remote
# command, before any mutation; Gate 2 then completes.
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"
export HADA_MOCK_SCENARIO="clean"
REMOTE_DIR_CREATED=0

set +e
remote_preparation_and_state_capture >"${TEMP_DIR}/gate2-clean.stdout" 2>&1
RC=$?
set -e

if [[ ${RC} -eq 0 ]]; then
    assert_pass "Gate 2 completes on a clean host (rc=0)"
else
    assert_fail "Gate 2 failed on a clean host (rc=${RC}); see ${TEMP_DIR}/gate2-clean.stdout"
    sed -n '1,40p' "${TEMP_DIR}/gate2-clean.stdout" >&2 || true
fi

FIRST_CMD="$(head -1 "${HADA_MOCK_SSH_LOG}" | base64 -d)"
if grep -q 'existing HADA' <<<"${FIRST_CMD}"; then
    assert_pass "Gate 2's first remote command is the read-only existing-resource check"
else
    assert_fail "Gate 2 must run the existing-resource check first"
fi
if grep -Eq 'install -d|mkdir' <<<"${FIRST_CMD}"; then
    assert_fail "a mutation command (install/mkdir) was Gate 2's first remote action"
else
    assert_pass "no mutation command in Gate 2's first remote action"
fi

# Temp-dir creation must be the LAST Gate 2 command (after all read-only checks)
LAST_CMD="$(tail -1 "${HADA_MOCK_SSH_LOG}" | base64 -d)"
if grep -q "install -d -m 0700 '${REMOTE_DIR}'" <<<"${LAST_CMD}"; then
    assert_pass "remote temp-dir creation is Gate 2's final step (first mutation)"
else
    assert_fail "expected temp-dir creation as Gate 2's final command"
fi

# ---------------------------------------------------------------------------
# Test 3: bounded_rollback with NOTHING tracked issues zero remote commands
# (this is the post-Gate-2-refusal / initial-state-failure path)
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"
SSH_CMD=("${MOCK_SSH_LOG_ONLY}")
CREATED_CONTAINERS=()
CREATED_VOLUMES=()
CREATED_NETWORKS=()
CREATED_IMAGES=()
UNIT_INSTALLED=0
SUPERVISOR_STARTED=0
COMPOSE_UP_DONE=0

set +e
bounded_rollback >"${TEMP_DIR}/rb-empty.stdout" 2>&1
RC=$?
set -e

if [[ ${RC} -eq 0 ]]; then
    assert_pass "bounded_rollback with nothing tracked returns 0"
else
    assert_fail "bounded_rollback with nothing tracked should return 0 (rc=${RC})"
fi
if [[ ! -s "${HADA_MOCK_SSH_LOG}" ]]; then
    assert_pass "bounded_rollback with nothing tracked issues ZERO remote commands"
else
    assert_fail "bounded_rollback with nothing tracked issued $(wc -l < "${HADA_MOCK_SSH_LOG}") remote commands"
fi

# ---------------------------------------------------------------------------
# Test 4: bounded_rollback rolls back ONLY tracked resources
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"
CREATED_CONTAINERS=("hada-m1-postgres-1" "hada-m1-valkey-1")
CREATED_VOLUMES=("hada-m1_postgres-data")
CREATED_NETWORKS=("hada-m1_control")
CREATED_IMAGES=("hada-orchestrator:0.2.0")
UNIT_INSTALLED=1
SUPERVISOR_STARTED=1
COMPOSE_UP_DONE=1
COMPOSE_UP_ATTEMPTED=1
ORCH_BUILT_BY_RUN=1

bounded_rollback >"${TEMP_DIR}/rb-tracked.stdout" 2>&1 || true

DECODED="$(decode_log)"
if grep -q 'systemctl stop hada-supervisor.service' <<<"${DECODED}"; then
    assert_pass "tracked supervisor start -> supervisor stopped in rollback"
else
    assert_fail "rollback must stop the supervisor this run started"
fi
if grep -q 'down --remove-orphans' <<<"${DECODED}" && ! grep -Eq 'down -v|down --volumes' <<<"${DECODED}"; then
    assert_pass "tracked compose up -> compose down WITHOUT -v in rollback"
else
    assert_fail "rollback must compose down without -v for the stack this run started"
fi
if grep -q 'rm -f /etc/systemd/system/hada-supervisor.service' <<<"${DECODED}"; then
    assert_pass "tracked unit install -> unit removed in rollback"
else
    assert_fail "rollback must remove the unit this run installed"
fi
if grep -Eq 'rm -rf /var/lib/hada|rm -rf /opt/hada' <<<"${DECODED}"; then
    assert_fail "rollback must NEVER delete /var/lib/hada or /opt/hada"
else
    assert_pass "rollback never deletes /var/lib/hada or /opt/hada"
fi

# ---------------------------------------------------------------------------
# Test 5: rollback after Gate-2-only progress (temp dir created, nothing
# else) touches no compose/service/unit
# ---------------------------------------------------------------------------
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
REMOTE_DIR_CREATED=1

bounded_rollback >"${TEMP_DIR}/rb-gate2.stdout" 2>&1 || true

DECODED="$(decode_log)"
if grep -Eq 'compose .*down|systemctl (stop|disable)|rm -f /etc/systemd' <<<"${DECODED}"; then
    assert_fail "after Gate-2-only progress, rollback must not touch compose/services/units"
else
    assert_pass "after Gate-2-only progress, rollback touches no compose/service/unit"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Stage-aware rollback mocked test results"
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
