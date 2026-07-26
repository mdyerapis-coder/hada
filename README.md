# HADA — Hermes Autonomous Development Appliance

This directory separates active development files from immutable releases,
evidence, reviews, and historical archives.

## Layout

- `workspace/` — active source tree, deployment runners, tests, and working evidence.
- `releases/v1/` through `releases/v4/` — immutable candidate archives, checksum files, and manifests.
- `evidence/phase-b0/` — preserved Phase B0 evidence, including the two v3 failed runs.
- `evidence/v4-local-gate/` — successful local V4 verification output.
- `evidence/historical-logs/` — older standalone HADA audit logs.
- `reviews/` — review reports, handoffs, and execution-gate documents.
- `archives/` — historical bundles and source archives.
- `archives/packages/` — complete verified package snapshots.
- `archives/legacy-project-package/` — package retained from the earlier backup-style layout.

## Current release

The current candidate is `releases/v4/HADA-M1-gcp-candidate-v4.zip`.

SHA-256:

`d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac`

Candidate v3 remains preserved with SHA-256:

`7d969ee44874837a584dcd3363dd4c72c0816fc46d3054300a896d0a37686204`

## Local development

Run local tests from `workspace/`:

```bash
cd workspace
bash tests/phase-b/run_all.sh
shellcheck -S error scripts/*.sh tests/phase-b/*.sh tests/static/*.sh
```

The production runners retain fail-closed defaults. When deliberately using
this relocated working copy, explicitly set `HADA_PHASE_B0_DEPLOY_DIR` or
`HADA_PHASE_B_DEPLOY_DIR` to the absolute `workspace/` path. Phase B0 and
Phase B deployment still require separate explicit authorization.

## Status

`HADA_V4_LOCAL_GATE_PASS_AWAITING_PHASE_B0`
