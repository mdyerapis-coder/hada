#!/usr/bin/env bash
# LOCAL-ONLY mocked proof that a post-contact v4 failure still captures AFTER
# state, comparisons, a FAIL summary, and guarded cleanup evidence.
set -Euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMPX="$(mktemp -d /tmp/hada-b0-failure-v4-XXXXXX)"
trap 'rm -rf "${TMPX}"' EXIT
mkdir -p "${TMPX}/root/deploy-v4" "${TMPX}/evidence"
cp "${ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip" "${TMPX}/root/deploy-v4/"
cp "${ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256" "${TMPX}/root/deploy-v4/"
cp "${ROOT}/deploy-v4/candidate-manifest-v4.txt" "${TMPX}/root/deploy-v4/"

cat >"${TMPX}/effective.json" <<'JSON'
{"services":{"caddy":{"ports":[{"host_ip":"127.0.0.1","published":80,"target":80,"protocol":"tcp"}]}},"volumes":{"postgres-data":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/postgres-data"}},"prometheus-data":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/prometheus-data"}},"loki-data":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/loki-data"}},"alloy-data":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/alloy-data"}},"grafana-data":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/grafana-data"}},"caddy-data":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/caddy-data"}},"caddy-config":{"driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/caddy-config"}}}}
JSON

cat >"${TMPX}/mock-ssh" <<'SH'
#!/usr/bin/env bash
cmd="$*"
case "${cmd}" in
  *"docker compose version --short"*) echo "5.3.1" ;;
  *"sudo -n docker ps -aq"*) echo "container-before" ;;
  *"sudo -n docker images -q"*) echo "image-before" ;;
  *"docker compose"*"config --format json"*) cat "${MOCK_EFFECTIVE_JSON}" ;;
  *"mkdir -p /tmp/hada-b0-preflight-"*) echo "mock remote temp created" ;;
  *"synthetic .env created"*) echo "synthetic .env created" ;;
  *"rm -rf"*) if [[ "${MOCK_CLEANUP_FAIL:-0}" == "1" ]]; then exit 23; else echo "mock guarded cleanup complete"; fi ;;
  *) : ;;
esac
SH
cat >"${TMPX}/mock-scp" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${TMPX}/mock-ssh" "${TMPX}/mock-scp"

MOCK_EFFECTIVE_JSON="${TMPX}/effective.json" \
HADA_PHASE_B0_DEPLOY_DIR="${TMPX}/root" \
HADA_PHASE_B0_EVIDENCE_DIR="${TMPX}/evidence" \
HADA_PHASE_B0_TIMESTAMP="44444444444444" \
HADA_PHASE_B0_SSH_CMD="${TMPX}/mock-ssh" \
HADA_PHASE_B0_SCP_CMD="${TMPX}/mock-scp" \
bash "${ROOT}/scripts/run-phase-b0-v4-preflight.sh" >"${TMPX}/runner.log" 2>&1
rc=$?
[[ ${rc} -ne 0 ]] || { echo "FAIL: mocked seven-volume run unexpectedly passed"; cat "${TMPX}/runner.log"; exit 1; }

RUN="${TMPX}/evidence/preflight-run-44444444444444"
SUMMARY="${RUN}/preflight-summary.txt"
grep -qxF "overall-result: FAIL" "${SUMMARY}"
grep -qxF "failed-gate: volume-assertion" "${SUMMARY}"
grep -qxF "candidate-sha256: d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac" "${SUMMARY}"
grep -qxF "project: api-intergrations-501314" "${SUMMARY}"
grep -qxF "zone: australia-southeast1-b" "${SUMMARY}"
grep -qxF "vm: hada-control" "${SUMMARY}"
grep -qxF "after-state-capture-succeeded: YES" "${SUMMARY}"
grep -qxF "container-state-changed: NO" "${SUMMARY}"
grep -qxF "image-state-changed: NO" "${SUMMARY}"
grep -qxF "remote-cleanup-result: PASS" "${SUMMARY}"
grep -qxF "0" "${RUN}/docker-ps-after.rc"
grep -qxF "0" "${RUN}/docker-images-after.rc"
echo "PASS: mocked v4 assertion failure preserves complete fail-closed AFTER-state and cleanup evidence"

# A cleanup failure must force overall FAIL even when every functional gate passes.
python3 - "${TMPX}/effective.json" "${TMPX}/effective-pass.json" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["volumes"]["valkey-data"] = {"driver_opts": {"type": "none", "o": "bind", "device": "/var/lib/hada/docker-volumes/valkey-data"}}
json.dump(cfg, open(sys.argv[2], "w"))
PY
set +e
MOCK_CLEANUP_FAIL=1 MOCK_EFFECTIVE_JSON="${TMPX}/effective-pass.json" \
HADA_PHASE_B0_DEPLOY_DIR="${TMPX}/root" HADA_PHASE_B0_EVIDENCE_DIR="${TMPX}/evidence" \
HADA_PHASE_B0_TIMESTAMP="55555555555555" HADA_PHASE_B0_SSH_CMD="${TMPX}/mock-ssh" \
HADA_PHASE_B0_SCP_CMD="${TMPX}/mock-scp" bash "${ROOT}/scripts/run-phase-b0-v4-preflight.sh" \
  >"${TMPX}/cleanup-fail.log" 2>&1
cleanup_rc=$?
set -e
[[ ${cleanup_rc} -ne 0 ]]
CLEANUP_SUMMARY="${TMPX}/evidence/preflight-run-55555555555555/preflight-summary.txt"
grep -qxF "overall-result: FAIL" "${CLEANUP_SUMMARY}"
grep -qxF "remote-cleanup-result: FAIL(rc=23)" "${CLEANUP_SUMMARY}"
echo "PASS: cleanup failure cannot convert or retain an overall PASS"
