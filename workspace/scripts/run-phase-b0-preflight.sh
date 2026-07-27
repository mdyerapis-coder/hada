#!/usr/bin/env bash
#
# HADA M1 Phase B0 — Bounded Preflight Script (Final corrected version)
#
# This script runs a bounded preflight on hada-control that:
#   - verifies the local candidate archive checksum (sha256sum -c);
#   - extracts the candidate into a unique local mktemp directory;
#   - obtains compose.yaml, compose.gcp.yaml and Caddyfile.gcp from that
#     extracted candidate tree (never from the older inspection directory);
#   - creates a uniquely named remote temporary directory;
#   - uploads only the required preflight files;
#   - uses a synthetic non-production .env;
#   - renders effective-compose.json via docker compose config --format json;
#   - enforces Docker Compose >= 2.24.4 (strips optional leading v, fails closed);
#   - runs structured assertions on ports and volumes;
#   - captures before/after container/image state and fails closed on any diff;
#   - captures diagnostic SSH/SCP stderr without exposing secrets;
#   - retrieves evidence into evidence/phase-b0/preflight-run-<timestamp>/;
#   - safely removes only its remote temporary directory via a guarded cleanup
#     function (trap on EXIT, INT, TERM);
#   - never runs up, build, pull, create, start, restart or reboot.
#
# Usage:
#   ./scripts/run-phase-b0-preflight.sh
#
# Prerequisites:
#   - gcloud CLI authenticated with IAP tunneling access to hada-control
#   - Docker Compose >= 2.24.4 on hada-control
#   - The candidate archive and production files exist locally
#
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT="api-intergrations-501314"
ZONE="australia-southeast1-b"
VM="hada-control"
SSH_CMD="gcloud compute ssh ${VM} --project=${PROJECT} --zone=${ZONE} --tunnel-through-iap"
SCP_CMD="gcloud compute scp --project=${PROJECT} --zone=${ZONE} --tunnel-through-iap"

DEPLOY_DIR="${HADA_PHASE_B0_DEPLOY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EVIDENCE_DIR="${DEPLOY_DIR}/evidence/phase-b0"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"
RUN_DIR="${EVIDENCE_DIR}/preflight-run-${TIMESTAMP}"
PREFLIGHT_PREFIX="hada-b0-preflight-${TIMESTAMP}"
REMOTE_DIR="/tmp/${PREFLIGHT_PREFIX}"

CANDIDATE_ARCHIVE="${DEPLOY_DIR}/HADA-M1-gcp-candidate.zip"
CANDIDATE_SHA256="${DEPLOY_DIR}/HADA-M1-gcp-candidate.zip.sha256"

# Track whether the remote directory was created, so the cleanup trap only
# attempts SSH cleanup when it was.  This prevents contacting hada-control
# if a failure occurs during local checksum, extraction, manifest, or
# required-file validation (before any remote mkdir).
REMOTE_DIR_CREATED=0

# These will be set after extracting the candidate archive
CANDIDATE_EXTRACT_DIR=""
BASE_COMPOSE=""
GCP_COMPOSE=""
CADDYFILE_GCP=""

mkdir -p "${RUN_DIR}"

# Track the original exit status so the cleanup trap preserves it
EXIT_STATUS=0

# ---------------------------------------------------------------------------
# Cleanup function
# ---------------------------------------------------------------------------

# shellcheck disable=SC2329  # invoked indirectly via trap below
cleanup() {
  local rc=$?
  # If invoked by the trap (EXIT), use EXIT_STATUS; if invoked by signal
  # handler, capture the signal context.
  if (( EXIT_STATUS == 0 )); then
    EXIT_STATUS=$rc
  fi

  # Remove the local mktemp directory (if created and non-empty)
  if [[ -n "${CANDIDATE_EXTRACT_DIR}" && -d "${CANDIDATE_EXTRACT_DIR}" ]]; then
    rm -rf "${CANDIDATE_EXTRACT_DIR}"
    echo "[cleanup] removed local extract dir: ${CANDIDATE_EXTRACT_DIR}"
  fi

  # Remove the remote directory ONLY if it was actually created during
  # this run (REMOTE_DIR_CREATED=1) and it matches the strict pattern
  # ^/tmp/hada-b0-preflight-[0-9]+$
  if [[ "${REMOTE_DIR_CREATED}" == "1" && -n "${REMOTE_DIR}" ]]; then
    if [[ -z "${REMOTE_DIR}" ]]; then
      echo "[cleanup] REFUSED: empty remote path"
    elif [[ "${REMOTE_DIR}" == "/tmp" || "${REMOTE_DIR}" == "/tmp/" ]]; then
      echo "[cleanup] REFUSED: refusing to remove /tmp"
    elif [[ ! "${REMOTE_DIR}" =~ ^/tmp/hada-b0-preflight-[0-9]+$ ]]; then
      echo "[cleanup] REFUSED: path does not match ^/tmp/hada-b0-preflight-[0-9]+\$ : ${REMOTE_DIR}"
    else
      ${SSH_CMD} --command="
DIR='${REMOTE_DIR}'
if [[ -z \"\${DIR}\" ]]; then
  echo 'REFUSED: empty path'
  exit 1
elif [[ \"\${DIR}\" == \"/tmp\" || \"\${DIR}\" == \"/tmp/\" ]]; then
  echo 'REFUSED: refusing to remove /tmp'
  exit 1
elif [[ ! \"\${DIR}\" =~ ^/tmp/hada-b0-preflight-[0-9]+\$ ]]; then
  echo \"REFUSED: path does not match ^/tmp/hada-b0-preflight-[0-9]+\$ : \${DIR}\"
  exit 1
else
  rm -rf \"\${DIR}\"
  echo \"removed: \${DIR}\"
fi" 2>>"${RUN_DIR}/cleanup-stderr.log" || true
      echo "[cleanup] remote cleanup attempted: ${REMOTE_DIR}"
    fi
  fi

  exit "${EXIT_STATUS}"
}

trap cleanup EXIT
trap 'EXIT_STATUS=$((130)); cleanup' INT
trap 'EXIT_STATUS=$((143)); cleanup' TERM

echo "============================================"
echo "HADA M1 Phase B0 — Bounded Preflight"
echo "Timestamp: ${TIMESTAMP}"
echo "Remote dir: ${REMOTE_DIR}"
echo "Evidence dir: ${RUN_DIR}"
echo "Candidate archive: ${CANDIDATE_ARCHIVE}"
echo "============================================"

# ---------------------------------------------------------------------------
# Step 0: Verify the candidate archive checksum locally
# ---------------------------------------------------------------------------

echo ""
echo "[0/8] Verifying candidate archive checksum locally..."

if [[ ! -f "${CANDIDATE_ARCHIVE}" ]]; then
  echo "FAIL: candidate archive not found: ${CANDIDATE_ARCHIVE}"
  EXIT_STATUS=1
  exit 1
fi

if [[ ! -f "${CANDIDATE_SHA256}" ]]; then
  echo "FAIL: candidate SHA-256 file not found: ${CANDIDATE_SHA256}"
  EXIT_STATUS=1
  exit 1
fi

# Run sha256sum -c on the archive's own .sha256 file
# The .sha256 file contains: <hash>  HADA-M1-gcp-candidate.zip
sha256sum -c "${CANDIDATE_SHA256}" 2>&1 | tee "${RUN_DIR}/archive-checksum-verify.txt"
ARCHIVE_VERIFY_RC=${PIPESTATUS[0]}
echo "  -> archive checksum rc=${ARCHIVE_VERIFY_RC}"

if [[ "${ARCHIVE_VERIFY_RC}" -ne 0 ]]; then
  echo "FAIL: candidate archive checksum verification failed"
  EXIT_STATUS=1
  exit 1
fi
echo "PASS: candidate archive checksum verified"

# ---------------------------------------------------------------------------
# Step 0b: Extract the candidate into a unique local mktemp directory
# ---------------------------------------------------------------------------

echo ""
echo "[0b/8] Extracting candidate archive into local mktemp directory..."

CANDIDATE_EXTRACT_DIR="$(mktemp -d -t hada-b0-extract-XXXXXXXXXX)"
echo "  -> local extract dir: ${CANDIDATE_EXTRACT_DIR}"

# Extract the candidate archive
( cd "${CANDIDATE_EXTRACT_DIR}" && unzip -q "${CANDIDATE_ARCHIVE}" )
EXTRACT_RC=$?
if [[ "${EXTRACT_RC}" -ne 0 ]]; then
  echo "FAIL: candidate archive extraction failed (rc=${EXTRACT_RC})"
  EXIT_STATUS=1
  exit 1
fi

# The archive extracts to HADA-M1-durable-orchestrator/
CANDIDATE_ROOT="${CANDIDATE_EXTRACT_DIR}/HADA-M1-durable-orchestrator"
if [[ ! -d "${CANDIDATE_ROOT}" ]]; then
  echo "FAIL: extracted candidate root not found: ${CANDIDATE_ROOT}"
  EXIT_STATUS=1
  exit 1
fi

# Obtain compose.yaml, compose.gcp.yaml, and Caddyfile.gcp from the extracted
# candidate tree.  NEVER use the older inspection directory as the Compose source.
BASE_COMPOSE="${CANDIDATE_ROOT}/deploy/compose/compose.yaml"
GCP_COMPOSE="${CANDIDATE_ROOT}/deploy/compose/compose.gcp.yaml"
CADDYFILE_GCP="${CANDIDATE_ROOT}/deploy/caddy/Caddyfile.gcp"

for f in "${BASE_COMPOSE}" "${GCP_COMPOSE}" "${CADDYFILE_GCP}"; do
  if [[ ! -f "${f}" ]]; then
    echo "FAIL: required file not found in extracted candidate: ${f}"
    EXIT_STATUS=1
    exit 1
  fi
done
echo "PASS: compose.yaml, compose.gcp.yaml, Caddyfile.gcp obtained from extracted candidate"
echo "  -> ${BASE_COMPOSE}"
echo "  -> ${GCP_COMPOSE}"
echo "  -> ${CADDYFILE_GCP}"

# Verify the candidate manifest from the extracted candidate root
echo ""
echo "  Verifying candidate manifest from extracted root..."
MANIFEST_FILE="${DEPLOY_DIR}/evidence/phase-b0/candidate-manifest.txt"
if [[ ! -f "${MANIFEST_FILE}" ]]; then
  echo "FAIL: candidate manifest not found: ${MANIFEST_FILE}"
  EXIT_STATUS=1
  exit 1
fi

( cd "${CANDIDATE_ROOT}" && sha256sum -c "${MANIFEST_FILE}" ) > "${RUN_DIR}/manifest-verify.txt" 2>&1
MANIFEST_RC=$?
cat "${RUN_DIR}/manifest-verify.txt" | tail -5
if [[ "${MANIFEST_RC}" -ne 0 ]]; then
  echo "FAIL: candidate manifest verification failed"
  EXIT_STATUS=1
  exit 1
fi
echo "PASS: candidate manifest verified from extracted root"

# ---------------------------------------------------------------------------
# Step 1: Capture Docker Compose version and enforce >= 2.24.4
# ---------------------------------------------------------------------------

echo ""
echo "[1/8] Capturing and enforcing Docker Compose version..."

${SSH_CMD} --command='docker compose version --short' 2>>"${RUN_DIR}/ssh-stderr.log" \
  | tee "${RUN_DIR}/compose-version.txt" > /dev/null
COMPOSE_VERSION_RAW="$(cat "${RUN_DIR}/compose-version.txt")"
echo "  -> raw version: ${COMPOSE_VERSION_RAW}"

# Strip an optional leading v
COMPOSE_VERSION="${COMPOSE_VERSION_RAW#v}"
echo "  -> stripped version: ${COMPOSE_VERSION}"

# Enforce >= 2.24.4 using sort -V
REQUIRED_VERSION="2.24.4"
if [[ "$(printf '%s\n%s\n' "${REQUIRED_VERSION}" "${COMPOSE_VERSION}" | sort -V | head -1)" != "${REQUIRED_VERSION}" ]]; then
  echo "FAIL: Docker Compose version ${COMPOSE_VERSION} is older than required ${REQUIRED_VERSION}"
  echo "FAIL: Compose version requirement: FAIL" | tee "${RUN_DIR}/compose-version-check.txt"
  EXIT_STATUS=1
  exit 1
fi
echo "PASS: Compose version ${COMPOSE_VERSION} >= ${REQUIRED_VERSION}"
echo "PASS: Compose version requirement: PASS" | tee "${RUN_DIR}/compose-version-check.txt"

# ---------------------------------------------------------------------------
# Step 2: Capture BEFORE state (containers and images)
# ---------------------------------------------------------------------------

echo ""
echo "[2/8] Capturing BEFORE state..."

# Capture container IDs with sudo -n. Do not pipeline inside the command
# substitution (that masks docker/sudo exit status). Fail closed on error —
# never convert a failed query into NONE. Local set -o pipefail preserves the
# SSH nonzero status through tee so cleanup can run.
# shellcheck disable=SC2016  # ${raw}/${rc} expand on remote shell, not locally
${SSH_CMD} --command='raw="$(sudo -n docker ps -aq)" || { rc=$?; echo "FAIL: sudo -n docker ps -aq failed with rc=${rc}" >&2; exit "${rc}"; }; if [[ -n "${raw}" ]]; then printf "%s\n" "${raw}" | sort; else printf "NONE\n"; fi' \
  2>>"${RUN_DIR}/ssh-stderr.log" \
  | tee "${RUN_DIR}/docker-ps-before.txt" > /dev/null
echo "  -> sudo -n docker ps -aq -> ${RUN_DIR}/docker-ps-before.txt"

# shellcheck disable=SC2016  # ${raw}/${rc} expand on remote shell, not locally
${SSH_CMD} --command='raw="$(sudo -n docker images -q)" || { rc=$?; echo "FAIL: sudo -n docker images -q failed with rc=${rc}" >&2; exit "${rc}"; }; if [[ -n "${raw}" ]]; then printf "%s\n" "${raw}" | sort -u; else printf "NONE\n"; fi' \
  2>>"${RUN_DIR}/ssh-stderr.log" \
  | tee "${RUN_DIR}/docker-images-before.txt" > /dev/null
echo "  -> sudo -n docker images -q -> ${RUN_DIR}/docker-images-before.txt"

# ---------------------------------------------------------------------------
# Step 3: Create remote temporary directory
# ---------------------------------------------------------------------------

echo ""
echo "[3/8] Creating remote temporary directory..."

${SSH_CMD} --command="mkdir -p ${REMOTE_DIR}/deploy/compose ${REMOTE_DIR}/deploy/caddy && echo ${REMOTE_DIR}" \
  2>>"${RUN_DIR}/ssh-stderr.log"
echo "  -> ${REMOTE_DIR}"

# Mark that the remote directory was created so the cleanup trap knows
# it is safe to attempt remote SSH cleanup.
REMOTE_DIR_CREATED=1

# ---------------------------------------------------------------------------
# Step 4: Upload preflight files (from the extracted candidate tree)
# ---------------------------------------------------------------------------

echo ""
echo "[4/8] Uploading preflight files from extracted candidate tree..."

# Upload compose.yaml (base) from the extracted candidate
${SCP_CMD} "${BASE_COMPOSE}" "${VM}:${REMOTE_DIR}/deploy/compose/compose.yaml" \
  2>>"${RUN_DIR}/scp-stderr.log"
echo "  -> compose.yaml (from candidate)"

# Upload compose.gcp.yaml from the extracted candidate
${SCP_CMD} "${GCP_COMPOSE}" "${VM}:${REMOTE_DIR}/deploy/compose/compose.gcp.yaml" \
  2>>"${RUN_DIR}/scp-stderr.log"
echo "  -> compose.gcp.yaml (from candidate)"

# Upload Caddyfile.gcp from the extracted candidate
${SCP_CMD} "${CADDYFILE_GCP}" "${VM}:${REMOTE_DIR}/deploy/caddy/Caddyfile.gcp" \
  2>>"${RUN_DIR}/scp-stderr.log"
echo "  -> Caddyfile.gcp (from candidate)"

# Upload the candidate SHA256 for reference
${SCP_CMD} "${CANDIDATE_SHA256}" "${VM}:${REMOTE_DIR}/candidate.sha256" \
  2>>"${RUN_DIR}/scp-stderr.log"
echo "  -> candidate.sha256"

# ---------------------------------------------------------------------------
# Step 5: Create synthetic non-production .env
# ---------------------------------------------------------------------------

echo ""
echo "[5/8] Creating synthetic .env..."

${SSH_CMD} --command="cat > ${REMOTE_DIR}/.env <<'ENVEOF'
HADA_ENV=preflight
HADA_DOMAIN=localhost
HADA_ACME_EMAIL=
POSTGRES_DB=hada
POSTGRES_USER=hada
POSTGRES_PASSWORD=synthetic-not-a-real-secret
VALKEY_PASSWORD=synthetic-not-a-real-secret
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=synthetic-not-a-real-secret
HADA_CONFIG=/opt/hada/config/hada.yaml
HADA_STATE_DIR=/var/lib/hada
HADA_LOG_DIR=/var/log/hada
HADA_DATABASE_DSN=postgresql://hada:***@postgres:5432/hada
HADA_VALKEY_URL=redis://:synthetic-not-a-real-secret@valkey:6379/0
HADA_TARGET_REPO_URL=https://github.com/mdyerapis-coder/hermesctl.git
HADA_TARGET_REPO_REF=main
HADA_EXTERNAL_REVIEW_MODE=manual
HADA_IMPLEMENTATION_MODEL=
HADA_ADVERSARIAL_MODEL=
HADA_INFERENCE_BACKEND=vllm
HADA_INFERENCE_MODEL_PATH=
ENVEOF
echo 'synthetic .env created'" 2>>"${RUN_DIR}/ssh-stderr.log"
echo "  -> .env (synthetic, non-production)"

# ---------------------------------------------------------------------------
# Step 6: Render effective configuration as JSON and run structured assertions
# ---------------------------------------------------------------------------

echo ""
echo "[6/8] Rendering effective-compose.json and running assertions..."

COMPOSE_RENDER_RC=0
${SSH_CMD} --command="cd ${REMOTE_DIR} && \
  docker compose \
    -f deploy/compose/compose.yaml \
    -f deploy/compose/compose.gcp.yaml \
    --env-file .env config --format json" 2>>"${RUN_DIR}/ssh-stderr.log" \
  | tee "${RUN_DIR}/effective-compose.json" > /dev/null
COMPOSE_RENDER_RC=${PIPESTATUS[0]}
echo "  -> effective-compose.json saved (rc=${COMPOSE_RENDER_RC})"

if [[ "${COMPOSE_RENDER_RC}" -ne 0 ]]; then
  echo "FAIL: docker compose config --format json failed (rc=${COMPOSE_RENDER_RC})"
  echo "FAIL: Compose JSON render: FAIL" | tee "${RUN_DIR}/compose-render-check.txt"
  EXIT_STATUS=1
  exit 1
fi
echo "PASS: Compose JSON render: PASS" | tee "${RUN_DIR}/compose-render-check.txt"

# Validate published ports from structured JSON
echo ""
echo "  [6a] Validating published ports..."
${SSH_CMD} --command="cd ${REMOTE_DIR} && \
  docker compose \
    -f deploy/compose/compose.yaml \
    -f deploy/compose/compose.gcp.yaml \
    --env-file .env config --format json" 2>>"${RUN_DIR}/ssh-stderr.log" \
  | python3 -c '
import json, sys

cfg = json.load(sys.stdin)
services = cfg.get("services", {})

# Collect all published ports from structured fields
published_ports = []
for svc_name, svc_def in services.items():
    ports = svc_def.get("ports", [])
    for p in ports:
        entry = {
            "service": svc_name,
            "host_ip": str(p.get("host_ip", "0.0.0.0")),
            "published": p.get("published"),
            "target": p.get("target"),
            "protocol": str(p.get("protocol", "tcp")),
            "mode": str(p.get("mode", "host")),
        }
        published_ports.append(entry)

print("Published ports found:")
for pp in published_ports:
    service = pp["service"]
    host_ip = pp["host_ip"]
    published = pp["published"]
    target = pp["target"]
    protocol = pp["protocol"]
    print(
        f"  service={service} host_ip={host_ip} "
        f"published={published} target={target} protocol={protocol}"
    )

errors = []

if len(published_ports) != 1:
    errors.append(
        f"FAIL: expected exactly 1 published port, found {len(published_ports)}"
    )

if published_ports:
    pp = published_ports[0]
    service = pp["service"]
    host_ip = pp["host_ip"]
    published = pp["published"]
    target = pp["target"]
    protocol = pp["protocol"]

    if service != "caddy":
        errors.append(f"FAIL: expected service=caddy, got {service}")

    if host_ip != "127.0.0.1":
        errors.append(
            f"FAIL: expected host_ip=127.0.0.1, got {host_ip}"
        )

    if published != 80 and published != "80":
        errors.append(
            f"FAIL: expected published=80, got {published}"
        )

    if target != 80 and target != "80":
        errors.append(
            f"FAIL: expected target=80, got {target}"
        )

    if protocol != "tcp":
        errors.append(
            f"FAIL: expected protocol=tcp, got {protocol}"
        )

    for p2 in published_ports:
        p2_service = p2["service"]
        p2_published = p2["published"]
        p2_target = p2["target"]
        if (
            p2_published == 443
            or p2_published == "443"
            or p2_target == 443
            or p2_target == "443"
        ):
            errors.append(
                f"FAIL: port 443 found: service={p2_service} "
                f"published={p2_published} target={p2_target}"
            )

if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("PASS: exactly one published port - caddy, 127.0.0.1:80:80/tcp, "
          "no 443")
' 2>&1 | tee "${RUN_DIR}/port-assertion.txt"
PORT_RC=${PIPESTATUS[0]}
echo "  -> port-assertion.txt (rc=${PORT_RC})"

if [[ "${PORT_RC}" -ne 0 ]]; then
  echo "FAIL: Port assertion: FAIL" | tee "${RUN_DIR}/port-assertion-check.txt"
else
  echo "PASS: Port assertion: PASS" | tee "${RUN_DIR}/port-assertion-check.txt"
fi

# Validate eight top-level volumes from structured JSON
echo ""
echo "  [6b] Validating stateful volumes..."
${SSH_CMD} --command="cd ${REMOTE_DIR} && \
  docker compose \
    -f deploy/compose/compose.yaml \
    -f deploy/compose/compose.gcp.yaml \
    --env-file .env config --format json" 2>>"${RUN_DIR}/ssh-stderr.log" \
  | python3 -c '
import json, sys

cfg = json.load(sys.stdin)
volumes = cfg.get("volumes", {})

expected = {
    "postgres-data":     "/var/lib/hada/docker-volumes/postgres-data",
    "valkey-data":       "/var/lib/hada/docker-volumes/valkey-data",
    "prometheus-data":   "/var/lib/hada/docker-volumes/prometheus-data",
    "loki-data":         "/var/lib/hada/docker-volumes/loki-data",
    "alloy-data":        "/var/lib/hada/docker-volumes/alloy-data",
    "grafana-data":      "/var/lib/hada/docker-volumes/grafana-data",
    "caddy-data":        "/var/lib/hada/docker-volumes/caddy-data",
    "caddy-config":      "/var/lib/hada/docker-volumes/caddy-config",
}

errors = []
print("Volumes found:")
for name in sorted(volumes.keys()):
    vol = volumes[name]
    driver_opts = vol.get("driver_opts", {})
    t = str(driver_opts.get("type", "NOT SET"))
    o = str(driver_opts.get("o", "NOT SET"))
    device = str(driver_opts.get("device", "NOT SET"))
    print(f"  {name}: type={t} o={o} device={device}")

    if name not in expected:
        errors.append(f"FAIL: unexpected volume: {name}")
        continue

    if t != "none":
        errors.append(f"FAIL: {name} type={t} expected=none")
    if o != "bind":
        errors.append(f"FAIL: {name} o={o} expected=bind")
    if device != expected[name]:
        errors.append(
            f"FAIL: {name} device={device} expected={expected[name]}"
        )
    if not device.startswith("/var/lib/hada/docker-volumes/"):
        errors.append(
            f"FAIL: {name} device not beneath "
            f"/var/lib/hada/docker-volumes/: {device}"
        )

for name in sorted(expected.keys()):
    if name not in volumes:
        errors.append(f"FAIL: missing volume: {name}")

if len(volumes) != len(expected):
    errors.append(
        f"FAIL: expected {len(expected)} volumes, got {len(volumes)}"
    )

if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print(f"PASS: all {len(expected)} volumes have type=none, o=bind, "
          f"device beneath /var/lib/hada/docker-volumes/")
' 2>&1 | tee "${RUN_DIR}/volume-assertion.txt"
VOL_RC=${PIPESTATUS[0]}
echo "  -> volume-assertion.txt (rc=${VOL_RC})"

if [[ "${VOL_RC}" -ne 0 ]]; then
  echo "FAIL: Volume assertion: FAIL" | tee "${RUN_DIR}/volume-assertion-check.txt"
else
  echo "PASS: Volume assertion: PASS" | tee "${RUN_DIR}/volume-assertion-check.txt"
fi

# ---------------------------------------------------------------------------
# Step 7: Capture AFTER state (containers and images) — fail closed
# ---------------------------------------------------------------------------

echo ""
echo "[7/8] Capturing AFTER state..."

# Same fail-closed sudo -n capture as BEFORE (no pipeline inside $(...)).
# shellcheck disable=SC2016  # ${raw}/${rc} expand on remote shell, not locally
${SSH_CMD} --command='raw="$(sudo -n docker ps -aq)" || { rc=$?; echo "FAIL: sudo -n docker ps -aq failed with rc=${rc}" >&2; exit "${rc}"; }; if [[ -n "${raw}" ]]; then printf "%s\n" "${raw}" | sort; else printf "NONE\n"; fi' \
  2>>"${RUN_DIR}/ssh-stderr.log" \
  | tee "${RUN_DIR}/docker-ps-after.txt" > /dev/null
echo "  -> sudo -n docker ps -aq -> ${RUN_DIR}/docker-ps-after.txt"

# shellcheck disable=SC2016  # ${raw}/${rc} expand on remote shell, not locally
${SSH_CMD} --command='raw="$(sudo -n docker images -q)" || { rc=$?; echo "FAIL: sudo -n docker images -q failed with rc=${rc}" >&2; exit "${rc}"; }; if [[ -n "${raw}" ]]; then printf "%s\n" "${raw}" | sort -u; else printf "NONE\n"; fi' \
  2>>"${RUN_DIR}/ssh-stderr.log" \
  | tee "${RUN_DIR}/docker-images-after.txt" > /dev/null
echo "  -> sudo -n docker images -q -> ${RUN_DIR}/docker-images-after.txt"

# Compare before and after — fail closed (write diff into evidence)
echo ""
echo "  Comparing before/after state..."

CONTAINER_DIFF_RC=0
IMAGE_DIFF_RC=0

if diff "${RUN_DIR}/docker-ps-before.txt" "${RUN_DIR}/docker-ps-after.txt" \
    > "${RUN_DIR}/container-diff.txt" 2>&1; then
  echo "PASS: container list unchanged (no containers started)"
  echo "PASS: container list unchanged" >> "${RUN_DIR}/container-diff.txt"
else
  echo "FAIL: container list changed"
  CONTAINER_DIFF_RC=1
fi

if diff "${RUN_DIR}/docker-images-before.txt" "${RUN_DIR}/docker-images-after.txt" \
    > "${RUN_DIR}/image-diff.txt" 2>&1; then
  echo "PASS: image list unchanged (no images pulled or created)"
  echo "PASS: image list unchanged" >> "${RUN_DIR}/image-diff.txt"
else
  echo "FAIL: image list changed"
  IMAGE_DIFF_RC=1
fi

# Write combined before/after diff report
{
  echo "=== Container diff ==="
  cat "${RUN_DIR}/container-diff.txt"
  echo ""
  echo "=== Image diff ==="
  cat "${RUN_DIR}/image-diff.txt"
} > "${RUN_DIR}/before-after-diff.txt"

if [[ "${CONTAINER_DIFF_RC}" -ne 0 || "${IMAGE_DIFF_RC}" -ne 0 ]]; then
  echo "FAIL: Docker state changed during preflight" | tee "${RUN_DIR}/state-check.txt"
  EXIT_STATUS=1
else
  echo "PASS: Docker state unchanged during preflight" | tee "${RUN_DIR}/state-check.txt"
fi

# ---------------------------------------------------------------------------
# Step 8: Cleanup is handled by the trap
# ---------------------------------------------------------------------------

echo ""
echo "[8/8] Cleanup handled by trap on EXIT/INT/TERM"

# ---------------------------------------------------------------------------
# Final preflight result — fail unless ALL checks pass
# ---------------------------------------------------------------------------

echo ""
echo "============================================"
echo "Phase B0 Preflight Final Result"
echo "============================================"

FINAL_PASS=1

# Check 1: Compose version requirement passed
if [[ -f "${RUN_DIR}/compose-version-check.txt" ]] && \
   grep -q "PASS" "${RUN_DIR}/compose-version-check.txt"; then
  echo "PASS: Compose version requirement"
else
  echo "FAIL: Compose version requirement"
  FINAL_PASS=0
fi

# Check 2: effective Compose JSON rendered successfully
if [[ -f "${RUN_DIR}/compose-render-check.txt" ]] && \
   grep -q "PASS" "${RUN_DIR}/compose-render-check.txt" && \
   [[ -s "${RUN_DIR}/effective-compose.json" ]]; then
  echo "PASS: Compose JSON rendered"
else
  echo "FAIL: Compose JSON rendered"
  FINAL_PASS=0
fi

# Check 3: port assertion passed
if [[ -f "${RUN_DIR}/port-assertion-check.txt" ]] && \
   grep -q "PASS" "${RUN_DIR}/port-assertion-check.txt"; then
  echo "PASS: Port assertion"
else
  echo "FAIL: Port assertion"
  FINAL_PASS=0
fi

# Check 4: volume assertion passed
if [[ -f "${RUN_DIR}/volume-assertion-check.txt" ]] && \
   grep -q "PASS" "${RUN_DIR}/volume-assertion-check.txt"; then
  echo "PASS: Volume assertion"
else
  echo "FAIL: Volume assertion"
  FINAL_PASS=0
fi

# Check 5: container list remained identical
if [[ -f "${RUN_DIR}/state-check.txt" ]] && \
   grep -q "PASS" "${RUN_DIR}/state-check.txt"; then
  echo "PASS: Container list identical"
else
  echo "FAIL: Container list changed"
  FINAL_PASS=0
fi

# Check 6: image list remained identical
# (covered by state-check.txt which requires both container and image unchanged)
if [[ -f "${RUN_DIR}/state-check.txt" ]] && \
   grep -q "PASS" "${RUN_DIR}/state-check.txt"; then
  echo "PASS: Image list identical"
else
  echo "FAIL: Image list changed"
  FINAL_PASS=0
fi

# Check 7: all expected evidence files exist and are non-empty
EVIDENCE_FILES=(
  "compose-version.txt"
  "compose-version-check.txt"
  "docker-ps-before.txt"
  "docker-images-before.txt"
  "effective-compose.json"
  "port-assertion.txt"
  "port-assertion-check.txt"
  "volume-assertion.txt"
  "volume-assertion-check.txt"
  "docker-ps-after.txt"
  "docker-images-after.txt"
  "container-diff.txt"
  "image-diff.txt"
  "before-after-diff.txt"
  "state-check.txt"
  "archive-checksum-verify.txt"
  "manifest-verify.txt"
)

EVIDENCE_PASS=1
for ef in "${EVIDENCE_FILES[@]}"; do
  fpath="${RUN_DIR}/${ef}"
  if [[ ! -f "${fpath}" ]]; then
    echo "FAIL: evidence file missing: ${ef}"
    EVIDENCE_PASS=0
  elif [[ ! -s "${fpath}" ]]; then
    echo "FAIL: evidence file empty: ${ef}"
    EVIDENCE_PASS=0
  fi
done

if [[ "${EVIDENCE_PASS}" -eq 1 ]]; then
  echo "PASS: All evidence files exist and non-empty"
else
  echo "FAIL: Some evidence files missing or empty"
  FINAL_PASS=0
fi

echo ""
echo "Evidence dir: ${RUN_DIR}"
echo ""
echo "Files in evidence dir:"
ls -1 "${RUN_DIR}/"
echo ""

if [[ "${FINAL_PASS}" -ne 1 ]]; then
  echo "PREFLIGHT RESULT: FAIL"
  EXIT_STATUS=1
  exit 1
else
  echo "PREFLIGHT RESULT: PASS"
  EXIT_STATUS=0
  exit 0
fi
