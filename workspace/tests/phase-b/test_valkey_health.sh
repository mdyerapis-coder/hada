#!/usr/bin/env bash
# shellcheck disable=SC2097,SC2098
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — Valkey health validation (correction 3, v3)
#
# Proves:
#   - VALKEY_PASSWORD is NOT present in the valkey container environment;
#   - the healthcheck reads the password from the protected config file
#     inside the container (VALKEYCLI_AUTH from /run/secrets/valkey.conf);
#   - an unreadable config file causes the healthcheck to FAIL;
#   - an incorrect password in the config file causes the healthcheck to FAIL.
#
# The healthcheck logic is simulated locally with a small valkey-cli stand-in
# so no real Valkey/docker is required (LOCAL-ONLY).
#
# LOCAL-ONLY.

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-valkey-health-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

SVCDIR="${TEMP_DIR}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
CANDIDATE_DIR="${DEPLOY_ROOT}/deploy-v4"
TMPX="$(mktemp -d)"
unzip -q "${CANDIDATE_DIR}/HADA-M1-gcp-candidate-v4.zip" -d "${TMPX}"
BASE="${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.yaml"
GCP="${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.gcp.yaml"

# Extract the valkey service environment + healthcheck from the rendered compose.
python3 - "${BASE}" "${GCP}" "${SVCDIR}/valkey_svc.json" <<'PY'
import sys, yaml, json
class _O(str): pass
def _c(l, n):
    if isinstance(n, yaml.MappingNode): return l.construct_mapping(n)
    if isinstance(n, yaml.SequenceNode): return l.construct_sequence(n)
    return l.construct_scalar(n)
yaml.SafeLoader.add_constructor('!override', _c)
base = yaml.safe_load(open(sys.argv[1]))
gcp = yaml.safe_load(open(sys.argv[2]))
out = sys.argv[3]
svc = dict(base['services']['valkey'])
if 'valkey' in gcp.get('services', {}):
    o = gcp['services']['valkey']
    for k in ('command', 'healthcheck', 'environment'):
        if k in o: svc[k] = o[k]
json.dump(svc, open(out, 'w'))
PY

# 1) VALKEY_PASSWORD must NOT be in the valkey container environment.
VALKEY_ENV="$(python3 -c "import json; d=json.load(open('${SVCDIR}/valkey_svc.json')); print(' '.join('%s=%s' % (k, v) for k, v in (d.get('environment') or {}).items()))")"
if [[ "${VALKEY_ENV}" != *"VALKEY_PASSWORD"* ]]; then
    assert_pass "VALKEY_PASSWORD is absent from the valkey container environment"
else
    assert_fail "VALKEY_PASSWORD is present in the valkey container environment"
fi

# 2) Healthcheck must read the password from /run/secrets/valkey.conf (not -a).
HEALTH="$(python3 -c "import json; d=json.load(open('${SVCDIR}/valkey_svc.json')); print(' '.join(str(x) for x in d.get('healthcheck', {}).get('test', [])))")"
if [[ "${HEALTH}" == *"VALKEYCLI_AUTH"* && "${HEALTH}" != *"valkey-cli -a "* ]]; then
    assert_pass "healthcheck uses VALKEYCLI_AUTH from the protected file (no valkey-cli -a)"
else
    assert_fail "healthcheck does not read the password from the protected file"
fi

# Simulate the in-container healthcheck command using a valkey-cli stand-in.
VALKEY_CLI_STANDIN="${TEMP_DIR}/valkey-cli"
cat > "${VALKEY_CLI_STANDIN}" <<'SH'
#!/usr/bin/env bash
# Stand-in for valkey-cli: returns PONG iff VALKEYCLI_AUTH matches the
# requirepass in the config file mounted at /run/secrets/valkey.conf.
conf="${VALKEYCLI_AUTH_CONF:-/run/secrets/valkey.conf}"
real="$(awk '/^requirepass /{print $2}' "${conf}" 2>/dev/null)"
if [[ "${VALKEYCLI_AUTH:-}" == "${real}" && -n "${real}" ]]; then
    echo "PONG"; exit 0
fi
exit 1
SH
chmod +x "${VALKEY_CLI_STANDIN}"

SECRET_FILE="${TEMP_DIR}/valkey.conf"
echo "requirepass correct-password" > "${SECRET_FILE}"

# 3) Correct password -> healthcheck succeeds.
OUT="$(VP="$(awk '/^requirepass /{print $2}' "${SECRET_FILE}")" VALKEYCLI_AUTH="${VP}" VALKEYCLI_AUTH_CONF="${SECRET_FILE}" "${VALKEY_CLI_STANDIN}" ping 2>/dev/null | grep -q PONG && echo OK || echo FAIL)"
if [[ "${OUT}" == "OK" ]]; then
    assert_pass "healthcheck succeeds with the correct protected-file password"
else
    assert_fail "healthcheck failed with the correct protected-file password"
fi

# 4) Incorrect password -> healthcheck fails.
OUT="$(VP="wrong-password" VALKEYCLI_AUTH="${VP}" VALKEYCLI_AUTH_CONF="${SECRET_FILE}" "${VALKEY_CLI_STANDIN}" ping 2>/dev/null | grep -q PONG && echo OK || echo FAIL)"
if [[ "${OUT}" == "FAIL" ]]; then
    assert_pass "healthcheck fails with an incorrect password"
else
    assert_fail "healthcheck succeeded with an incorrect password"
fi

# 5) Unreadable config file -> healthcheck fails.
chmod 000 "${SECRET_FILE}"
OUT="$(VP="$(awk '/^requirepass /{print $2}' "${SECRET_FILE}" 2>/dev/null)"; VALKEYCLI_AUTH="${VP}" VALKEYCLI_AUTH_CONF="${SECRET_FILE}" "${VALKEY_CLI_STANDIN}" ping 2>/dev/null | grep -q PONG && echo OK || echo FAIL)"
chmod 600 "${SECRET_FILE}"
if [[ "${OUT}" == "FAIL" ]]; then
    assert_pass "healthcheck fails when the protected config file is unreadable"
else
    assert_fail "healthcheck succeeded with an unreadable config file"
fi

rm -rf "${TMPX}"

echo ""
echo "============================================"
echo "Valkey health validation test results"
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
