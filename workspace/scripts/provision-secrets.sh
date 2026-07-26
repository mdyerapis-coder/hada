#!/usr/bin/env bash
#
# HADA M1 Phase B — Atomic Secret Provisioning Script
#
# This script must be run on hada-control after the bootstrap script
# has completed and /opt/hada exists. It is NOT executed during Phase A.
#
# Requirements met:
#   - Each secret is generated exactly once.
#   - URL-safe values via openssl rand -hex 32.
#   - Each secret is reused in its PASSWORD and DSN/URL.
#   - /opt/hada/.env is written atomically (temp file + mv).
#   - root:hada ownership, mode 0640.
#   - Secrets are never displayed (stdout is suppressed).
#   - Fails if any CHANGE_ME placeholder remains.
#
set -Eeuo pipefail

ENV_PATH="/opt/hada/.env"
ENV_DIR="$(dirname "$ENV_PATH")"

# Fail fast if openssl is unavailable
command -v openssl >/dev/null 2>&1 || {
  echo "ERROR: openssl is required but not found" >&2
  exit 1
}

# Ensure /opt/hada exists (bootstrap should have created it)
if [[ ! -d "$ENV_DIR" ]]; then
  echo "ERROR: $ENV_DIR does not exist; run bootstrap-ubuntu.sh first" >&2
  exit 1
fi

# Generate each secret exactly once, URL-safe hex (64 hex chars = 32 bytes)
POSTGRES_PASSWORD="$(openssl rand -hex 32)"
VALKEY_PASSWORD="$(openssl rand -hex 32)"
GRAFANA_ADMIN_PASSWORD="$(openssl rand -hex 32)"

# Reuse each secret in its DSN / URL (must embed the real password — never a redacted placeholder)
POSTGRES_USER="hada"
POSTGRES_DB="hada"
HADA_DATABASE_DSN="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
HADA_VALKEY_URL="redis://:${VALKEY_PASSWORD}@valkey:6379/0"

# Write to a temporary file in the same directory (atomic via mv)
TMP_FILE="$(mktemp "${ENV_PATH}.XXXXXX")"
if [[ ! -f "$TMP_FILE" ]]; then
  echo "ERROR: failed to create temporary file" >&2
  exit 1
fi

# Ensure cleanup on error
trap 'rm -f "$TMP_FILE"' EXIT

cat > "$TMP_FILE" <<EOF
HADA_ENV=production
HADA_DOMAIN=localhost
HADA_ACME_EMAIL=
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
VALKEY_PASSWORD=${VALKEY_PASSWORD}
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
HADA_CONFIG=/opt/hada/config/hada.yaml
HADA_STATE_DIR=/var/lib/hada
HADA_LOG_DIR=/var/log/hada
HADA_DATABASE_DSN=${HADA_DATABASE_DSN}
HADA_VALKEY_URL=${HADA_VALKEY_URL}
HADA_TARGET_REPO_URL=https://github.com/mdyerapis-coder/hermesctl.git
HADA_TARGET_REPO_REF=main
HADA_EXTERNAL_REVIEW_MODE=manual
HADA_IMPLEMENTATION_MODEL=
HADA_ADVERSARIAL_MODEL=
HADA_INFERENCE_BACKEND=vllm
HADA_INFERENCE_MODEL_PATH=
EOF

# Fail if any CHANGE_ME placeholder remains
if grep -q 'CHANGE_ME' "$TMP_FILE"; then
  echo "ERROR: CHANGE_ME placeholder found in generated .env" >&2
  rm -f "$TMP_FILE"
  exit 1
fi

# Set ownership and permissions before atomic move
chown root:hada "$TMP_FILE"
chmod 0640 "$TMP_FILE"

# Atomic move into place
mv -f "$TMP_FILE" "$ENV_PATH"

# Clear the trap since cleanup is no longer needed
trap - EXIT

echo "Secret provisioning complete: ${ENV_PATH} written (root:hada, mode 0640)"
echo "No secrets displayed."
