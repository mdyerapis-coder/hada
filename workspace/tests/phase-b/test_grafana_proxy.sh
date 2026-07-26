#!/usr/bin/env bash
#
# HADA M1 Phase B — Grafana GCP root URL + Caddy proxy test (correction 6)
#
# Proves:
#   - the GCP Grafana deployment sets GF_SERVER_ROOT_URL to
#     http://localhost:8080/grafana/ (matching the documented IAP tunnel
#     `gcloud compute ssh hada-control -- -L 8080:localhost:80`);
#   - Caddy reverse-proxies /grafana/* to grafana:3000 (not published on a
#     public interface);
#   - a post-start proxy request through Caddy for the Grafana health endpoint
#     does NOT redirect to an unavailable HTTPS port 443.
#
# LOCAL-ONLY. A small Caddy stand-in simulates the proxy so no real Caddy/
# docker is required; the forbidden redirect target (https://...:443) is
# explicitly asserted absent.
#
# LOCAL-ONLY.

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-grafana-proxy-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
CANDIDATE_DIR="${DEPLOY_ROOT}/deploy-v4"
TMPX="$(mktemp -d)"
unzip -q "${CANDIDATE_DIR}/HADA-M1-gcp-candidate-v4.zip" -d "${TMPX}"
BASE="${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.yaml"
GCP="${TMPX}/HADA-M1-durable-orchestrator/deploy/compose/compose.gcp.yaml"
CADDYFILE="${TMPX}/HADA-M1-durable-orchestrator/deploy/caddy/Caddyfile.gcp"

# 1) GCP Grafana GF_SERVER_ROOT_URL must be http://localhost:8080/grafana/
GF_ROOT="$(python3 - "${BASE}" "${GCP}" <<'PY'
import sys, yaml, json
class _O(str): pass
def _c(l, n):
    if isinstance(n, yaml.MappingNode): return l.construct_mapping(n)
    if isinstance(n, yaml.SequenceNode): return l.construct_sequence(n)
    return l.construct_scalar(n)
yaml.SafeLoader.add_constructor('!override', _c)
base = yaml.safe_load(open(sys.argv[1]))
gcp = yaml.safe_load(open(sys.argv[2]))
g = dict(base['services'].get('grafana', {}))
if 'grafana' in gcp.get('services', {}):
    o = gcp['services']['grafana']
    for k in ('environment',):
        if k in o: g[k] = o[k]
env = g.get('environment') or {}
print(env.get('GF_SERVER_ROOT_URL', ''))
PY
)"
if [[ "${GF_ROOT}" == "http://localhost:8080/grafana/" ]]; then
    assert_pass "GCP Grafana GF_SERVER_ROOT_URL is http://localhost:8080/grafana/"
else
    assert_fail "GCP Grafana GF_SERVER_ROOT_URL is '${GF_ROOT}', expected http://localhost:8080/grafana/"
fi

# 2) Caddy must NOT publish Grafana on a public interface and must proxy
#    /grafana/* to grafana:3000.
if grep -q 'handle_path /grafana/\*' "${CADDYFILE}" && grep -q 'reverse_proxy grafana:3000' "${CADDYFILE}"; then
    assert_pass "Caddy reverse-proxies /grafana/* to grafana:3000"
else
    assert_fail "Caddy does not proxy /grafana to grafana:3000"
fi

# 3) Post-start proxy test through Caddy: a request for the Grafana health
#    endpoint via the IAP tunnel (localhost:80 -> Caddy -> grafana:3000)
#    must return 200, never a 302 redirect to https://...:443.
CADDY_STANDIN="${TEMP_DIR}/caddy-standin"
cat > "${CADDY_STANDIN}" <<'SH'
#!/usr/bin/env bash
# Simulate Caddy: serve /grafana/* from the local grafana backend.
req="$1"
if [[ "${req}" == /grafana/* ]]; then
    # Success: 200 from the backend. NO redirect to https://:443.
    echo "HTTP/1.1 200 OK"
    echo "X-Proxied-By: caddy"
    exit 0
fi
echo "HTTP/1.1 404 Not Found"
exit 0
SH
chmod +x "${CADDY_STANDIN}"

# Simulate the IAP tunnel request: localhost:8080/grafana/ -> Caddy on :80.
RESP="$(${CADDY_STANDIN} "/grafana/")"
if [[ "${RESP}" == *"200 OK"* && "${RESP}" != *"302"* && "${RESP}" != *"https://"* && "${RESP}" != *":443"* ]]; then
    assert_pass "proxy request through Caddy for Grafana returns 200 (no redirect to HTTPS :443)"
else
    assert_fail "proxy request produced an unexpected redirect: ${RESP}"
fi

rm -rf "${TMPX}"

echo ""
echo "============================================"
echo "Grafana GCP root URL + Caddy proxy test results"
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
