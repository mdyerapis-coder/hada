#!/usr/bin/env bash
set -euo pipefail
[[ ${EVIDENCE_SHA256:-} =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid evidence SHA-256.' >&2; exit 1; }
[[ -n ${AUTHORIZATION_REFERENCE:-} ]] || { echo 'Authorization reference is required.' >&2; exit 1; }
case ${TARGET_ENVIRONMENT:-} in staging|production) ;; *) echo 'Invalid environment.' >&2; exit 1;; esac
printf 'environment=%s\nevidence_sha256=%s\nauthorization_reference=%s\n' \
  "$TARGET_ENVIRONMENT" "$EVIDENCE_SHA256" "$AUTHORIZATION_REFERENCE"
