#!/usr/bin/env bash
set -euo pipefail
mkdir -p .ci-evidence
# Match per-release checksum files (e.g. HADA-M1-*-candidate.zip.sha256),
# not a single repo-wide manifest name.
mapfile -t manifests < <(find releases -type f -name '*.sha256' 2>/dev/null | sort)
if ((${#manifests[@]} == 0)); then
  echo 'FAIL: no checksum manifests found under releases/.' >&2
  exit 1
fi
: > .ci-evidence/manifest-verification.txt
for manifest in "${manifests[@]}"; do
  dir=$(dirname "$manifest")
  name=$(basename "$manifest")
  echo "== $manifest ==" | tee -a .ci-evidence/manifest-verification.txt
  (cd "$dir" && sha256sum -c "$name") | tee -a .ci-evidence/manifest-verification.txt
done
