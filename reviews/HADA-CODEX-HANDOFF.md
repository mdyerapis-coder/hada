# HADA M1 — Codex Handoff

## Status

The v3 candidate and local test suite are complete and appear ready for the final Phase B0 runner review. Execution remains on hold pending reviewer confirmation.

Do **not** contact `hada-control`, run Phase B0, or execute Phase B until that review is closed.

## Objective

Finish the remaining v3 Phase B0 checksum, manifest, and evidence-binding work without changing the locked v3 candidate.

After the local corrections and tests pass, produce the final review bundle and stop. The next operational step will be a separately authorised bounded Phase B0 run.

## Working directory

```text
/home/bobthabuilda/hada-deployment
```

## Locked infrastructure target

```text
Project: api-intergrations-501314
Zone:    australia-southeast1-b
VM:      hada-control
State:   /var/lib/hada
```

Do not touch:

```text
hermes-clean
home-hub
```

## Locked candidate

```text
deploy-v3/HADA-M1-gcp-candidate-v3.zip
```

Expected SHA-256:

```text
7d969ee44874837a584dcd3363dd4c72c0816fc46d3054300a896d0a37686204
```

The candidate must remain byte-for-byte unchanged. Do not create v4.

## Current local state

The supplied v3 review reports:

- v1, v2, and v3 audit history preserved.
- The Phase B deployment runner defaults to v3.
- Valkey uses a protected configuration file rather than password-bearing process arguments.
- Grafana uses the documented HTTP tunnel origin.
- The complete mocked Phase B suite passes locally.
- Phase B0 has not been run against v3.
- The VM has not been contacted.

## Remaining review findings

### 1. Make the v3 B0 checksum gate path-independent

The v3 SHA file names the archive without its `deploy-v3/` directory. Running `sha256sum -c` from the deployment root can therefore resolve the wrong path.

Update `scripts/run-phase-b0-v3-preflight.sh` to:

1. Hash `CANDIDATE_ARCHIVE` directly.
2. Read the first hash field from `CANDIDATE_SHA256_FILE`.
3. Require both values to equal the hardcoded v3 SHA-256.
4. Fail before any SSH or SCP action on every mismatch.

Add an executable test that runs the exact checksum gate from the deployment root.

### 2. Add a versioned v3 candidate manifest

Create:

```text
deploy-v3/candidate-manifest-v3.txt
```

Generate it from the checksum-locked v3 archive and include hashes for the complete extracted candidate tree.

The v3 B0 runner must use only this manifest. It must not depend on:

```text
evidence/phase-b0/candidate-manifest.txt
```

Tests must prove:

- untouched v3 extraction passes;
- a modified file fails;
- the old v1 manifest fails;
- a missing manifest fails before remote contact.

### 3. Bind successful B0 evidence to candidate v3 and the exact target

A successful v3 B0 run must create non-secret evidence files:

```text
candidate-sha256.txt
target-identity.txt
preflight-summary.txt
```

Required contents:

```text
candidate-sha256.txt:
7d969ee44874837a584dcd3363dd4c72c0816fc46d3054300a896d0a37686204
```

```text
target-identity.txt:
project=api-intergrations-501314
zone=australia-southeast1-b
vm=hada-control
```

`preflight-summary.txt` must record PASS for:

- candidate checksum;
- candidate manifest;
- Compose version;
- Compose JSON rendering;
- port assertion;
- volume assertion;
- unchanged container state;
- unchanged image state.

Do not include resolved environment values or secrets.

### 4. Strengthen Phase B Gate 0f

The Phase B runner must reject any B0 evidence directory unless all of these match the locked v3 deployment:

- exact candidate SHA;
- exact project, zone, and VM;
- Compose version PASS;
- Compose render PASS;
- port assertion PASS;
- volume assertion PASS;
- Docker state PASS;
- complete v3 preflight summary PASS.

A stale v1 B0 evidence directory must fail even though its `state-check.txt` contains PASS.

### 5. Add local acceptance tests

Add tests proving:

- correct v3 checksum passes from the deployment root;
- a wrong archive hash fails before SSH;
- a wrong SHA file fails before SSH;
- missing or changed v3 manifest fails before SSH;
- stale v1 B0 evidence is rejected;
- complete synthetic v3 evidence is accepted locally;
- `DEPLOY_EXECUTE=0` performs no remote action.

## Operational restrictions

This task is **local-only**.

Do not:

- run SSH or SCP;
- contact `hada-control`;
- run Phase B0;
- deploy;
- pull or build images;
- create or start containers;
- create real secrets;
- modify the v3 candidate;
- modify GCP resources;
- change the persistent disk;
- modify `hermes-clean` or `home-hub`.

## Required deliverables

Create:

```text
/home/bobthabuilda/Downloads/HADA-V3-B0-FINAL-GATE-REVIEW.txt
/home/bobthabuilda/Downloads/HADA-V3-B0-FINAL-GATE-BUNDLE.tar.gz
```

The bundle must contain:

- unchanged v3 candidate and SHA file;
- `candidate-manifest-v3.txt`;
- corrected v3 B0 runner;
- corrected Phase B runner;
- supporting scripts;
- complete local tests;
- no credentials or real secrets.

Extract the finished bundle into an unrelated temporary directory and run the complete suite there as a non-root user.

## Completion condition

Stop after producing the local review artefacts.

Finish with:

```text
HADA_V3_B0_RUNNER_READY_NOT_EXECUTED
```

## Review gate

This handoff does not authorise Phase B0 or production deployment. The project is at the final review gate, and execution should remain paused until the corrected bundle has been independently checked.
