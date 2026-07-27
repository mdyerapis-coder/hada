#!/usr/bin/env bash
set -euo pipefail
mkdir -p .ci-evidence-package
archive=.ci-evidence-package/hada-evidence-${GITHUB_RUN_ID:-local}.tar.gz
tar -czf "$archive" .ci-evidence
sha256sum "$archive" > "$archive.sha256"
