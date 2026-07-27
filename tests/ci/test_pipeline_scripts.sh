#!/usr/bin/env bash
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

EVIDENCE_SHA256=$(printf x | sha256sum | awk '{print $1}') \
AUTHORIZATION_REFERENCE=review/test \
TARGET_ENVIRONMENT=staging \
  bash scripts/ci/validate_deployment_authority.sh >/dev/null

if EVIDENCE_SHA256=bad AUTHORIZATION_REFERENCE=x TARGET_ENVIRONMENT=staging \
  bash scripts/ci/validate_deployment_authority.sh >/dev/null 2>&1; then
  echo 'FAIL: invalid hash accepted.' >&2
  exit 1
fi

bash -n scripts/ci/*.sh
echo 'PASS: pipeline bootstrap scripts.'
