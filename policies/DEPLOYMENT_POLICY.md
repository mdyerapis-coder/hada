# Deployment Policy

## Target

The documented production target is:

- Project: `api-intergrations-501314`
- Zone: `australia-southeast1-b`
- Host: `hada-control`

## Controls

- GitHub `production` environment must require manual approval.
- The workflow must receive an accepted evidence SHA-256 and immutable authorization reference.
- Cloud credentials must use short-lived workload identity; static service-account keys are prohibited.
- The executor must verify candidate, release, evidence, and authorization hashes before any mutation.
- Preflight, apply, health, acceptance, and rollback evidence must be captured independently.
- Failed acceptance must result in rollback or a declared degraded state; it must never be reported as success.

## Bootstrap limitation

The initial `deploy.yml` intentionally performs authority validation only. It does not mutate GCP. This prevents the CI bootstrap itself from bypassing the established deployment gate.
