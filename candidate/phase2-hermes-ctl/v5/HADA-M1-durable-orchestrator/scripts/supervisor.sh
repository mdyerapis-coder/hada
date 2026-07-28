#!/usr/bin/env bash
#
# HADA M1 Production supervisor script for Google Cloud (hada-control VM)
#
# This is the GCP production version of supervisor.sh. It uses the EXPLICIT
# Compose project name hada-m1 and BOTH compose files (the base compose.yaml
# and the production override compose.gcp.yaml) plus the explicit .env file.
# It does NOT rely on a venv (the orchestrator runs in-container) and does NOT
# start or manage a second project named "hada". Recovery is bounded by the
# maximum_recovery_attempts and recovery_backoff_seconds values from
# config/hada.yaml.
#
# Install this as /opt/hada/scripts/supervisor.sh on the VM. The systemd
# unit hada-supervisor.service calls this script.
#
# HADA_ROOT may be overridden (for local/CI testing) and defaults to /opt/hada.

set -Eeuo pipefail

HADA_ROOT="${HADA_ROOT:-/opt/hada}"
cd "${HADA_ROOT}"

if [[ ! -r .env ]]; then
  logger -p daemon.crit -t hada-supervisor "missing ${HADA_ROOT}/.env"
  exit 78
fi

# Explicit, fixed project name. NEVER use a bare "hada" project.
COMPOSE_PROJECT="hada-m1"
BASE_COMPOSE="${HADA_ROOT}/deploy/compose/compose.yaml"
GCP_COMPOSE="${HADA_ROOT}/deploy/compose/compose.gcp.yaml"
ENV_FILE="${HADA_ROOT}/.env"

compose=(
  docker compose
    -p "${COMPOSE_PROJECT}"
    -f "${BASE_COMPOSE}"
    -f "${GCP_COMPOSE}"
    --env-file "${ENV_FILE}"
)

# Bounded recovery parameters from the locked configuration (no venv needed:
# config/hada.yaml is plain YAML read by the orchestrator; here we parse it
# with a tiny POSIX-safe awk to avoid any python/venv dependency).
config_get() { awk -v sec="$1" -v key="$2" '
  /^[^[:space:]#]/ { cur="" }
  $0 ~ "^"sec":" { cur=sec; next }
  cur==sec && $0 ~ "^[[:space:]]*"key":" {
    sub("^[[:space:]]*"key":[[:space:]]*","");
    gsub(/[[:space:]]*$/,"");
    print;
    exit
  }' "${HADA_ROOT}/config/hada.yaml"; }

max_attempts="$(config_get governance maximum_recovery_attempts)"
backoff="$(config_get infrastructure recovery_backoff_seconds)"
max_attempts="${max_attempts:-5}"
backoff="${backoff:-10}"

attempt=0
while true; do
  unhealthy=0
  if ! "${compose[@]}" up -d --remove-orphans; then
    unhealthy=1
  elif "${compose[@]}" ps --all --format json \
    | jq -e 'length == 0 or any(.[]; .State != "running" or (.Health != "" and .Health != "healthy"))' \
      >/dev/null; then
    unhealthy=1
  fi

  if (( unhealthy == 1 )); then
    if (( attempt >= max_attempts )); then
      logger -p daemon.crit -t hada-supervisor "recovery attempts exhausted"
      exit 70
    fi
    attempt=$((attempt + 1))
    logger -p daemon.warning -t hada-supervisor \
      "control plane unhealthy; bounded recovery attempt ${attempt}/${max_attempts}"
    "${compose[@]}" restart || true
  else
    attempt=0
  fi

  sleep "${backoff}"
done
