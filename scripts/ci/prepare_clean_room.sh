#!/usr/bin/env bash
set -euo pipefail
rm -rf .ci-clean-room .ci-evidence
mkdir -p .ci-clean-room .ci-evidence
printf '%s\n' "source_sha=${GITHUB_SHA:-local}" "created_at=$(date -u +%FT%TZ)" > .ci-evidence/context.txt
