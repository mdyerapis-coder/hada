#!/usr/bin/env bash
set -Eeuo pipefail

cd /opt/hada
if [[ ! -r .env ]]; then
  logger -p daemon.crit -t hada-supervisor "missing /opt/hada/.env"
  exit 78
fi

compose=(docker compose -f deploy/compose/compose.yaml --env-file .env)
max_attempts=$(/opt/hada/.venv/bin/python - <<'PY'
import yaml
with open('config/hada.yaml', encoding='utf-8') as handle:
    print(yaml.safe_load(handle)['governance']['maximum_recovery_attempts'])
PY
)
backoff=$(/opt/hada/.venv/bin/python - <<'PY'
import yaml
with open('config/hada.yaml', encoding='utf-8') as handle:
    print(yaml.safe_load(handle)['infrastructure']['recovery_backoff_seconds'])
PY
)

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

  sleep "$backoff"
done
