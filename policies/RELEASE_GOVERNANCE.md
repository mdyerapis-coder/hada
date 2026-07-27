# HADA Release Governance

## Release states

1. `WORKING` — mutable implementation under `workspace/`.
2. `CANDIDATE` — content-addressed candidate under `releases/`.
3. `VERIFIED` — manifests and clean-room E2E pass.
4. `REVIEWED` — an independent review records scope, hashes, and findings.
5. `AUTHORIZED` — an immutable authorization references the exact verified evidence.
6. `DEPLOYED` — the approved executor ran against the declared target.
7. `ACCEPTED` — post-deployment tests passed and durable evidence was captured.

A later state must never be inferred merely because an earlier state passed.

## Mandatory gates

- Candidate bytes are immutable after review begins.
- Every release archive carries a manifest and checksum inventory.
- E2E must run from an unrelated extraction directory with no dependency on an operator home directory.
- Test-only evidence must be cryptographically distinct and rejected by production execution paths.
- Production deployment requires an environment approval and an immutable authorization reference.
- Deployment success requires accepted post-deployment evidence; a successful command exit alone is insufficient.

## Current v4 authority

- Candidate SHA-256: `d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac`
- Phase B0 inventory SHA-256: `2fff3266ee4117497cb1cd933328e243a9a36bd6157f2fcc30ceea005cd78e74`
- Examined release archive SHA-256: `942205447f9913b9aca6642f6dfea41e183ba99857cb598c5e9994c568e695bb`

These values document the examined chain; they do not constitute deployment evidence.
