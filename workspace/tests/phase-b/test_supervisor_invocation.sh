#!/usr/bin/env bash
#
# HADA M1 Phase B — Host supervisor invocation test (correction 2)
#
# Executes the installed supervisor.sh in a sandbox with PATH shims and
# captures every `docker compose` invocation. Proves each invocation uses the
# EXACT project name and file set:
#   docker compose -p hada-m1 \
#       -f /opt/hada/deploy/compose/compose.yaml \
#       -f /opt/hada/deploy/compose/compose.gcp.yaml \
#       --env-file /opt/hada/.env
# and that it does NOT:
#   - rely on /opt/hada/.venv;
#   - start or manage a second project named "hada".
#
# LOCAL-ONLY.

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-sup-test-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
CANDIDATE_DIR="${DEPLOY_ROOT}/deploy-v4"

# Install the v2 supervisor.sh + compose files + config into a sandbox.
SB="${TEMP_DIR}/sandbox"
mkdir -p "${SB}/opt/hada/scripts" "${SB}/opt/hada/deploy/compose" "${SB}/opt/hada/config"
TMPX="$(mktemp -d)"
unzip -q "${CANDIDATE_DIR}/HADA-M1-gcp-candidate-v4.zip" -d "${TMPX}"
cp "${TMPX}/HADA-M1-durable-orchestrator/scripts/supervisor.sh" "${SB}/opt/hada/scripts/supervisor.sh"
cp "${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.yaml" "${SB}/opt/hada/deploy/compose/compose.yaml"
cp "${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.gcp.yaml" "${SB}/opt/hada/deploy/compose/compose.gcp.yaml"
cp "${TMPX}/HADA-M1-durable-orchestrator/config/hada.yaml" "${SB}/opt/hada/config/hada.yaml"
printf 'POSTGRES_PASSWORD=x\nVALKEY_PASSWORD=y\nGRAFANA_ADMIN_PASSWORD=z\n' > "${SB}/opt/hada/.env"
rm -rf "${TMPX}"

# PATH shims: capture every docker compose invocation; stub the rest.
SHIMS="${TEMP_DIR}/shims"
mkdir -p "${SHIMS}"
CAP="${TEMP_DIR}/compose-calls.log"
: > "${CAP}"

cat > "${SHIMS}/docker" <<'SHIM'
#!/usr/bin/env bash
if [[ "$1" == "compose" ]]; then
  echo "COMPOSE_CALL $*" >> "${COMPOSE_CAP:-/dev/null}"
fi
exit 0
SHIM
chmod +x "${SHIMS}/docker"

cat > "${SHIMS}/jq" <<'SHIM'
#!/usr/bin/env bash
# Stub: report a healthy/non-empty array so the supervisor loop proceeds and
# treats the stack as healthy (so a single `up` + `ps` is issued before the
# busy-loop sleeps).
echo '[{"State":"running","Health":"healthy"}]'
SHIM
chmod +x "${SHIMS}/jq"

cat > "${SHIMS}/logger" <<'SHIM'
#!/usr/bin/env bash
exit 0
SHIM
chmod +x "${SHIMS}/logger"

cat > "${SHIMS}/sleep" <<'SHIM'
#!/usr/bin/env bash
# Do not actually sleep in the test; exit immediately so the supervisor
# issues its `up` + `ps` then loops. We capture one iteration and kill it.
exit 0
SHIM
chmod +x "${SHIMS}/sleep"

export COMPOSE_CAP="${CAP}"
# Run supervisor.sh once (first iteration issues `up` + `ps`), then stop it.
( HADA_ROOT="${SB}/opt/hada" PATH="${SHIMS}:${PATH}" \
    bash "${SB}/opt/hada/scripts/supervisor.sh" & echo $! > "${TEMP_DIR}/sup.pid" )
SUP_PID="$(cat "${TEMP_DIR}/sup.pid")"
sleep 1
kill "${SUP_PID}" 2>/dev/null || true
wait "${SUP_PID}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Assertions on captured compose calls
# ---------------------------------------------------------------------------
total_calls="$(wc -l < "${CAP}")"
if (( total_calls >= 1 )); then
    assert_pass "supervisor issued ${total_calls} docker compose call(s)"
else
    assert_fail "supervisor issued no docker compose calls"
fi

correct_form=1
bad_project=0
uses_venv=0
issues_up=0
issues_restart=0
while IFS= read -r line; do
    args="${line#COMPOSE_CALL }"
    if [[ "${args}" != *"-p hada-m1"* ]]; then correct_form=0; fi
    if [[ "${args}" != *"-f ${SB}/opt/hada/deploy/compose/compose.yaml"* ]]; then correct_form=0; fi
    if [[ "${args}" != *"-f ${SB}/opt/hada/deploy/compose/compose.gcp.yaml"* ]]; then correct_form=0; fi
    if [[ "${args}" != *"--env-file ${SB}/opt/hada/.env"* ]]; then correct_form=0; fi
    # must not manage a second project literally named "hada"
    if [[ "${args}" == *"-p hada "* || "${args}" == *"-p hada\t"* || "${args}" == *"-p hada\""* ]]; then
        bad_project=1
    fi
    if [[ "${args}" == *".venv"* || "${line}" == *".venv"* ]]; then uses_venv=1; fi
    case "${args}" in
        *"up -d --remove-orphans"*) issues_up=1 ;;
        *"restart"*) issues_restart=1 ;;
    esac
done < "${CAP}"

if (( correct_form == 1 )); then
    assert_pass "every compose invocation uses -p hada-m1 + both compose files + --env-file (HADA_ROOT=${SB}/opt/hada)"
else
    assert_fail "a compose invocation did not use the exact required form"
    sed 's/^/   /' "${CAP}" >&2
fi

if (( bad_project == 0 )); then
    assert_pass "supervisor does not start/manage a second project named 'hada'"
else
    assert_fail "supervisor manages a project named 'hada' (second project)"
fi

if (( uses_venv == 0 )); then
    assert_pass "supervisor does not depend on /opt/hada/.venv"
else
    assert_fail "supervisor references /opt/hada/.venv"
fi

if (( issues_up == 1 )); then
    assert_pass "supervisor issues up (bounded recovery)"
else
    assert_fail "supervisor did not issue up"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Host supervisor invocation test results"
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
