#!/usr/bin/env bash
#
# HADA M1 Phase B — Valkey secret-absence in rendered Compose (correction 3, v3)
#
# Renders the v4 Compose (base + gcp override) with a KNOWN SENTINEL Valkey
# password injected via environment, then proves the sentinel does NOT occur
# in the valkey service command array or healthcheck field — the TRUTHFUL
# scope. (The orchestrator's environment legitimately carries HADA_VALKEY_URL
# with the password; we do not claim otherwise, per the v4 correction.)
#
# Equivalent to the runner's Gate 5e (truthful scope) but executed locally with
# pyyaml. The production runner uses `docker compose config` for the same check.
#
# LOCAL-ONLY.

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-valkey-test-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
CANDIDATE_DIR="${DEPLOY_ROOT}/deploy-v4"

SENTINEL="__SENTINEL_VALKEY_PW__"
TMPX="$(mktemp -d)"
unzip -q "${CANDIDATE_DIR}/HADA-M1-gcp-candidate-v4.zip" -d "${TMPX}"
BASE="${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.yaml"
GCP="${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.gcp.yaml"

# Render with pyyaml: merge override onto base (compose override semantics
# for command/healthcheck/environment), then substitute the sentinel into the
# Valkey password variable.
python3 - "${BASE}" "${GCP}" "${SENTINEL}" <<'PY' > "${TEMP_DIR}/rendered.json"
import sys, yaml, json
class _Override(str):
    pass
def _override_constructor(loader, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)
yaml.SafeLoader.add_constructor('!override', _override_constructor)

base = yaml.safe_load(open(sys.argv[1]))
gcp = yaml.safe_load(open(sys.argv[2]))
sentinel = sys.argv[3]

services = {}
names = set(base.get('services', {})) | set(gcp.get('services', {}))
for name in names:
    s = dict(base.get('services', {}).get(name, {}))
    if name in gcp.get('services', {}):
        o = gcp['services'][name]
        for k in ('command', 'healthcheck', 'environment'):
            if k in o:
                s[k] = o[k]
        for k in ('ports', 'volumes'):
            if k in o:
                s[k] = o[k]
        for k, v in o.items():
            if k not in ('command', 'healthcheck', 'environment', 'ports', 'volumes'):
                s.setdefault(k, v)
    services[name] = s

def inject(obj):
    if isinstance(obj, str):
        return obj.replace('${VALKEY_PASSWORD}', sentinel).replace('$$VALKEY_PASSWORD', sentinel)
    if isinstance(obj, list):
        return [inject(x) for x in obj]
    if isinstance(obj, dict):
        return {k: inject(v) for k, v in obj.items()}
    return obj

for name, s in services.items():
    services[name] = inject(s)

out = {'services': services,
       'secrets': base.get('secrets', {}),
       'volumes': {**base.get('volumes', {}), **gcp.get('volumes', {})}}
json.dump(out, sys.stdout)
PY

# Scan rendered output for the sentinel ONLY in the valkey command and
# valkey healthcheck (truthful scope: the orchestrator environment still
# carries HADA_VALKEY_URL, which is not part of this assertion).
python3 - "${TEMP_DIR}/rendered.json" "${SENTINEL}" <<'PY'
import sys, json
cfg = json.load(open(sys.argv[1]))
sentinel = sys.argv[2]
errs = []
def scan(obj, path):
    if isinstance(obj, dict):
        for k, v in obj.items():
            scan(v, path + '.' + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scan(v, path + '[%d]' % i)
    elif isinstance(obj, str):
        if sentinel in obj:
            errs.append('sentinel found at %s: %r' % (path, obj))
valkey = cfg.get('services', {}).get('valkey', {})
scan(valkey.get('command'), 'valkey.command')
hc = valkey.get('healthcheck')
if hc is not None:
    scan(hc.get('test'), 'valkey.healthcheck.test')
if errs:
    print('FAIL')
    for e in errs:
        print(e)
    sys.exit(1)
print('PASS')
PY
rc=$?
if (( rc == 0 )); then
    assert_pass "rendered Compose contains no sentinel Valkey password in valkey command or healthcheck"
else
    assert_fail "rendered Compose leaks the Valkey password into valkey command/healthcheck"
fi

# Specific checks on the valkey service (v4 config-file design).
if python3 - "${TEMP_DIR}/rendered.json" <<'PY'
import sys, json
cfg = json.load(open(sys.argv[1]))
valkey = cfg['services']['valkey']
errs = []
cmd = valkey.get('command', [])
hc = valkey.get('healthcheck', {}).get('test', [])
# valkey 8 has no --requirepass-file; it must be started with the supported
# configuration-file form: valkey-server /run/secrets/valkey.conf
if any('--requirepass-file' in str(c) for c in cmd):
    errs.append('valkey command still uses unsupported --requirepass-file')
if not any(str(c) == '/run/secrets/valkey.conf' for c in cmd):
    errs.append('valkey command does not start from /run/secrets/valkey.conf')
# No inline --requirepass <value>
if any('--requirepass' in str(c) and 'file' not in str(c) for c in cmd):
    errs.append('valkey command uses --requirepass with an inline value')
# healthcheck must not use valkey-cli -a
hcfull = ' '.join(str(x) for x in hc)
if 'valkey-cli' in hcfull and '-a ' in hcfull:
    errs.append('valkey healthcheck uses valkey-cli -a (secret in args)')
if 'VALKEYCLI_AUTH' not in hcfull:
    errs.append('valkey healthcheck does not use VALKEYCLI_AUTH')
if errs:
    print('FAIL')
    for e in errs: print(e)
    sys.exit(1)
PY
then
    assert_pass "valkey uses valkey-server /run/secrets/valkey.conf (no --requirepass-file, no inline password); healthcheck uses VALKEYCLI_AUTH (no valkey-cli -a)"
else
    assert_fail "valkey command/healthcheck still embeds or misuses the password"
fi

rm -rf "${TMPX}"

echo ""
echo "============================================"
echo "Valkey secret-absence (rendered Compose) test results"
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
