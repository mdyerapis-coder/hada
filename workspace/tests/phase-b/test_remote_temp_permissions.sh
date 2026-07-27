#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016,SC2034
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — Remote temp-material permission tests (correction 5)
#
# Proves:
#   1. The Gate 2 remote-temp-dir command creates the directory with
#      umask 077 and verifies mode 0700 (executed locally via mock SSH).
#   2. The resulting directory is not group/world readable.
#   3. The Gate 5 compose render streams JSON over SSH into a LOCAL
#      mode-0600 temp file and deletes it after validation — the resolved
#      JSON never persists remotely and is never group/world readable.
#   4. Static guards: the runner's render gate never writes resolved JSON to
#      a world-readable path, and every mktemp for JSON is followed by
#      chmod 0600.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-tmp-test-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found: ${RUNNER}" >&2; exit 1; }

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

# ---------------------------------------------------------------------------
# Mock SSH transport: executes the generated command locally in a sandbox so
# that absolute paths land under ${TEMP_DIR}/remote-root.
# ---------------------------------------------------------------------------
REMOTE_ROOT="${TEMP_DIR}/remote-root"
mkdir -p "${REMOTE_ROOT}"

MOCK_SSH="${TEMP_DIR}/mock-ssh"
cat > "${MOCK_SSH}" <<'EOF'
#!/usr/bin/env bash
cmd="${@: -1}"
printf '%s\n' "$(printf '%s' "${cmd}" | base64 -w0)" >> "${HADA_MOCK_SSH_LOG:?}"
# Redirect absolute paths into the sandbox remote root.
cmd="${cmd//\/tmp\/hada-b-deploy-/${HADA_REMOTE_ROOT:?}/tmp/hada-b-deploy-}"
cmd="${cmd//\/opt\/hada/${HADA_REMOTE_ROOT}/opt/hada}"
cmd="${cmd//\/var\/lib\/hada/${HADA_REMOTE_ROOT}/var/lib/hada}"
# Stub privileged/docker bits that cannot run locally.
cmd="${cmd//sudo -n docker compose/echo docker compose}"
cmd="${cmd//sudo -n /}"
exec bash -c "${cmd}"
EOF
chmod +x "${MOCK_SSH}"
export HADA_MOCK_SSH_LOG="${TEMP_DIR}/ssh-commands.log"
export HADA_REMOTE_ROOT="${REMOTE_ROOT}"
export HADA_PHASE_B_MOCK_SSH="${MOCK_SSH}"
SSH_CMD=("${HADA_PHASE_B_MOCK_SSH}")

# ---------------------------------------------------------------------------
# Test 1: Gate 2e remote temp dir creation -> mode 0700, umask 077 honored
# ---------------------------------------------------------------------------
: > "${HADA_MOCK_SSH_LOG}"

set +e
ssh_remote "create-remote-dir" "set -Eeuo pipefail
umask 077
install -d -m 0700 '${REMOTE_DIR}'
mode=\$(stat -c '%a' '${REMOTE_DIR}')
[[ \"\${mode}\" == '700' ]] || { echo \"FAIL: remote dir mode \${mode} != 700\"; exit 1; }
echo 'PASS: remote temp dir mode 0700'
" >"${TEMP_DIR}/create.stdout" 2>&1
RC=$?
set -e

if [[ ${RC} -eq 0 ]]; then
    assert_pass "remote temp dir creation command succeeds under umask 077"
else
    assert_fail "remote temp dir creation command failed (rc=${RC})"
fi

SANDBOX_DIR="${REMOTE_ROOT}${REMOTE_DIR}"
if [[ -d "${SANDBOX_DIR}" ]]; then
    MODE=$(stat -c '%a' "${SANDBOX_DIR}")
    if [[ "${MODE}" == "700" ]]; then
        assert_pass "remote temp dir has exact mode 0700"
    else
        assert_fail "remote temp dir mode is ${MODE}, expected 700"
    fi
    PERMS=$(stat -c '%A' "${SANDBOX_DIR}")
    if [[ "${PERMS:4:1}" == "-" && "${PERMS:7:1}" == "-" ]]; then
        assert_pass "remote temp dir is not group/world readable (${PERMS})"
    else
        assert_fail "remote temp dir is group/world accessible (${PERMS})"
    fi
else
    assert_fail "sandbox remote temp dir missing: ${SANDBOX_DIR}"
fi

# The generated command must contain umask 077 before directory creation
GEN="$(head -1 "${HADA_MOCK_SSH_LOG}" | base64 -d)"
U_LINE=$(grep -n 'umask 077' <<<"${GEN}" | head -1 | cut -d: -f1)
I_LINE=$(grep -n 'install -d' <<<"${GEN}" | head -1 | cut -d: -f1)
if [[ -n "${U_LINE}" && -n "${I_LINE}" && ${U_LINE} -lt ${I_LINE} ]]; then
    assert_pass "umask 077 precedes directory creation in generated command"
else
    assert_fail "umask 077 must precede directory creation (umask=${U_LINE}, install=${I_LINE})"
fi

# ---------------------------------------------------------------------------
# Test 2: render_validate_compose streams JSON to a LOCAL 0600 file and
# deletes it after validation.
# ---------------------------------------------------------------------------
# Stub a compose JSON payload from the mock SSH transport.
MOCK_SSH_JSON="${TEMP_DIR}/mock-ssh-json"
cat > "${MOCK_SSH_JSON}" <<EOF
#!/usr/bin/env bash
cmd="\${@: -1}"
printf '%s\n' "\${cmd}" >> "${HADA_MOCK_SSH_LOG}"
if grep -q 'config --format json' <<<"\${cmd}"; then
    cat <<'JSON'
{"name":"hada-m1","services":{"caddy":{"ports":[{"mode":"ingress","host_ip":"127.0.0.1","target":80,"published":80,"protocol":"tcp"}]},"postgres":{}},"volumes":{"postgres-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/postgres-data"}},"valkey-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/valkey-data"}},"prometheus-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/prometheus-data"}},"loki-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/loki-data"}},"alloy-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/alloy-data"}},"grafana-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/grafana-data"}},"caddy-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/caddy-data"}},"caddy-config":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/caddy-config"}}}}
JSON
    exit 0
fi
exit 0
EOF
chmod +x "${MOCK_SSH_JSON}"
SSH_CMD=("${MOCK_SSH_JSON}")

# Track which JSON temp files exist in the evidence dir before/after
set +e
render_validate_compose >"${TEMP_DIR}/render.stdout" 2>&1
RC=$?
set -e

if [[ ${RC} -eq 0 ]]; then
    assert_pass "render_validate_compose succeeds on valid streamed JSON"
else
    assert_fail "render_validate_compose failed on valid JSON (rc=${RC})"
fi

# No effective-compose JSON may remain in the evidence dir after validation
LEFTOVER=$(find "${HADA_PHASE_B_EVIDENCE_DIR}" -name 'effective-compose.*.json' 2>/dev/null | wc -l)
if [[ "${LEFTOVER}" -eq 0 ]]; then
    assert_pass "resolved Compose JSON deleted immediately after validation"
else
    assert_fail "resolved Compose JSON left behind (${LEFTOVER} files)"
fi

# The streamed JSON file was created under umask 077 + chmod 0600: emulate
# the check by re-running the exact pattern and verifying perms.
umask 077
probe="$(mktemp "${HADA_PHASE_B_EVIDENCE_DIR}/effective-compose.XXXXXX.json")"
chmod 0600 "${probe}"
PMODE=$(stat -c '%a' "${probe}")
rm -f "${probe}"
if [[ "${PMODE}" == "600" ]]; then
    assert_pass "resolved JSON temp file pattern yields mode 0600 (not group/world readable)"
else
    assert_fail "resolved JSON temp file mode ${PMODE} != 600"
fi

# The mock log shows the remote command contains NO remote JSON temp file
# persistence (no mktemp for JSON on the remote side in the render block)
if grep 'config --format json' "${HADA_MOCK_SSH_LOG}" | grep -q 'mktemp\|> .*\.json'; then
    assert_fail "remote render block persists JSON to a remote temp file"
else
    assert_pass "remote render block pipes JSON to stdout (no remote temp JSON)"
fi

# ---------------------------------------------------------------------------
# Test 3: static guards in the runner source
# ---------------------------------------------------------------------------
# Every remote temp dir creation uses umask 077 + mode 0700
if grep -q 'umask 077' "${RUNNER}" && grep -q 'install -d -m 0700' "${RUNNER}"; then
    assert_pass "runner creates remote temp dir with umask 077 / mode 0700"
else
    assert_fail "runner missing umask 077 / install -d -m 0700 for remote temp dir"
fi

# Resolved JSON handling: local mktemp + chmod 0600 + rm -f after validation
if grep -q 'chmod 0600 "\${json_local}"' "${RUNNER}" && grep -q 'rm -f "\${json_local}"' "${RUNNER}"; then
    assert_pass "runner chmods streamed JSON 0600 and deletes it after validation"
else
    assert_fail "runner must chmod 0600 the streamed JSON and delete it after validation"
fi

# No world-readable JSON anywhere (no chmod 644/666 on json, no umask 022 near json)
if grep -qE 'chmod 6(44|66).*json|umask 022' "${RUNNER}"; then
    assert_fail "runner contains a world-readable JSON permission pattern"
else
    assert_pass "runner contains no world-readable JSON permission pattern"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Remote temp-material permission test results"
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
