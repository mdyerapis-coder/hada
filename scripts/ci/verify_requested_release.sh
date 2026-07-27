#!/usr/bin/env bash
set -euo pipefail
: "${HADA_RELEASE_PATH:?HADA_RELEASE_PATH is required}"
[[ -e "$HADA_RELEASE_PATH" ]] || { echo "Release not found: $HADA_RELEASE_PATH" >&2; exit 1; }
mkdir -p .ci-evidence
if [[ -f "$HADA_RELEASE_PATH" ]]; then
  sha256sum "$HADA_RELEASE_PATH" | tee .ci-evidence/requested-release.sha256
else
  find "$HADA_RELEASE_PATH" -type f -print0 | sort -z | xargs -0 sha256sum | tee .ci-evidence/requested-release-files.sha256
fi
