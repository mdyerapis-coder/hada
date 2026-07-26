#!/usr/bin/env bash
# LOCAL-ONLY proof that DEPLOY_EXECUTE=0 reaches review-only completion without transport.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMPX="$(mktemp -d /tmp/hada-deploy-zero-v4-XXXXXX)"
trap 'rm -rf "${TMPX}"' EXIT
mkdir -p "${TMPX}/fakebin" "${TMPX}/b0" "${TMPX}/evidence"
cat >"${TMPX}/fakebin/gcloud" <<'SH'
#!/usr/bin/env bash
echo "$*" >>"${REMOTE_LOG}"
exit 97
SH
chmod +x "${TMPX}/fakebin/gcloud"
HASH="$(awk 'NR==1{print $1}' "${ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256")"
printf '%s\n' "${HASH}" >"${TMPX}/b0/candidate-sha256.txt"
printf '%s\n' 'project=api-intergrations-501314' 'zone=australia-southeast1-b' 'vm=hada-control' >"${TMPX}/b0/target-identity.txt"
printf '%s\n' 'PASS: Compose version requirement: PASS' >"${TMPX}/b0/compose-version-check.txt"
printf '%s\n' 'PASS: Compose JSON render: PASS' >"${TMPX}/b0/compose-render-check.txt"
printf '%s\n' 'PASS: Port assertion: PASS' >"${TMPX}/b0/port-assertion-check.txt"
printf '%s\n' 'PASS: Volume assertion: PASS' >"${TMPX}/b0/volume-assertion-check.txt"
printf '%s\n' 'PASS: Docker state unchanged during preflight' >"${TMPX}/b0/state-check.txt"
printf '%s\n' \
  'overall-result: PASS' 'failed-gate: none' \
  "candidate-sha256: ${HASH}" \
  'project: api-intergrations-501314' 'zone: australia-southeast1-b' 'vm: hada-control' \
  'after-state-capture-succeeded: YES' 'container-state-changed: NO' 'image-state-changed: NO' \
  'remote-cleanup-result: PASS' 'candidate-checksum: PASS' 'candidate-manifest: PASS' \
  'compose-version: PASS' 'compose-render: PASS' 'port-assertion: PASS' 'volume-assertion: PASS' \
  'container-state-unchanged: PASS' 'image-state-unchanged: PASS' >"${TMPX}/b0/preflight-summary.txt"

set +e
REMOTE_LOG="${TMPX}/remote.log" PATH="${TMPX}/fakebin:${PATH}" DEPLOY_EXECUTE=0 \
HADA_PHASE_B_DEPLOY_DIR="${ROOT}" HADA_PHASE_B0_EVIDENCE_DIR="${TMPX}/b0" \
HADA_PHASE_B_EVIDENCE_DIR="${TMPX}/evidence" \
bash "${ROOT}/scripts/run-phase-b-deploy.sh" >"${TMPX}/output.log" 2>&1
rc=$?
set -e
[[ ${rc} -eq 0 ]] || { echo "FAIL: DEPLOY_EXECUTE=0 local review failed rc=${rc}"; tail -40 "${TMPX}/output.log"; exit 1; }
[[ ! -s "${TMPX}/remote.log" ]] || { echo "FAIL: DEPLOY_EXECUTE=0 contacted transport"; exit 1; }
grep -q "No SSH/SCP/deploy actions were performed" "${TMPX}/output.log"
echo "PASS: DEPLOY_EXECUTE=0 completed local review with zero remote transport calls"
