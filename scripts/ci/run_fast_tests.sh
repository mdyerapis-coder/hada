#!/usr/bin/env bash
set -euo pipefail
mkdir -p .ci-evidence
if [[ -x tests/fresh-deploy/test_reg_release_archive_v4.sh ]]; then
  tests/fresh-deploy/test_reg_release_archive_v4.sh | tee .ci-evidence/fast-tests.txt
elif [[ -x workspace/tests/fresh-deploy/test_reg_release_archive_v4.sh ]]; then
  workspace/tests/fresh-deploy/test_reg_release_archive_v4.sh | tee .ci-evidence/fast-tests.txt
else
  bash tests/ci/test_pipeline_scripts.sh | tee .ci-evidence/fast-tests.txt
fi
