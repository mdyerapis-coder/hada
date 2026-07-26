#!/usr/bin/env bash
# LOCAL-ONLY: extract the locked v4 archive and run its structural durability proof.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMPX="$(mktemp -d /tmp/hada-valkey-v4-XXXXXX)"
trap 'rm -rf "${TMPX}"' EXIT
unzip -q "${ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip" -d "${TMPX}"
python3 "${ROOT}/tests/phase-b/test_valkey_durability_v4.py" "${TMPX}/HADA-M1-durable-orchestrator"
