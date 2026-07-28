#!/usr/bin/env bash
#
# HADA M1 Production host validation script for Google Cloud (hada-control VM)
#
# This is the GCP production version of validate-host.sh. It uses BOTH compose
# files (the base compose.yaml and the production override compose.gcp.yaml).
# It does NOT rely on sed patching during deployment.
#
# Install this as /opt/hada/scripts/validate-host.sh on the VM (replacing the
# shipped version).
#
set -Eeuo pipefail

failures=0
check() {
  local description=$1
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS  %s\n' "$description"
  else
    printf 'FAIL  %s\n' "$description" >&2
    failures=$((failures + 1))
  fi
}

check "Ubuntu 24.04" bash -c 'source /etc/os-release; [[ $ID == ubuntu && $VERSION_ID == 24.04 ]]'
check "Docker daemon" docker info
check "Docker Compose" docker compose version
check "Git" git --version
check "Bubblewrap" bwrap --version
check "Unprivileged user namespaces" bash -c '[[ $(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || echo 1) == 1 ]]'
check "HADA service account" bash -c '[[ $(id -u hada) == 10001 && $(id -g hada) == 10001 ]]'
check "Private signing key permissions" bash -c '[[ $(stat -c %a /var/lib/hada/keys/audit-signing-key.pem) == 600 ]]'
check "Public signing key" test -r /var/lib/hada/keys/audit-signing-key.pub.pem
check "Configuration" /opt/hada/.venv/bin/hada validate-config --config /opt/hada/config/hada.yaml
check "Compose rendering" docker compose \
  -f /opt/hada/deploy/compose/compose.yaml \
  -f /opt/hada/deploy/compose/compose.gcp.yaml \
  --env-file /opt/hada/.env config

if (( failures > 0 )); then
  printf '%d validation checks failed\n' "$failures" >&2
  exit 1
fi
printf 'Host validation passed\n'
