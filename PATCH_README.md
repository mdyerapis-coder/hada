# HADA GitHub Pipeline Patch

This patch adds a governed GitHub Actions foundation to the existing `mdyerapis-coder/hada` repository without modifying immutable release artifacts or executing production deployment.

## Included

- repository verification
- operator-local path rejection
- checksum-manifest validation
- clean-room E2E execution and evidence upload
- manual release-evidence build
- non-mutating deployment authority gate
- CODEOWNERS and pull-request controls
- governance policy, deployment policy, ADR, and runbook
- bootstrap regression tests

## Apply

Extract this archive into the repository root on a dedicated branch, run:

```bash
chmod +x scripts/ci/*.sh tests/ci/*.sh
bash tests/ci/test_pipeline_scripts.sh
```

Then commit and open a draft pull request.

The first substantive correction remains removal of the operator-local Phase B0 evidence dependency from the v4 clean-room E2E path. Candidate v4 must remain byte-identical.
