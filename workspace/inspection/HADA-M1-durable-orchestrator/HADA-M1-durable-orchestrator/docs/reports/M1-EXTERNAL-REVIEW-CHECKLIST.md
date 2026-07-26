# M1 Independent External Review Checklist

Party 3 must review this milestone outside the HADA runtime. Party 3 should receive the source archive, public signing key, signed evidence manifest, test outputs, coverage report and deployment configuration. The private signing key must not be included.

## Architecture

- [ ] PostgreSQL is the sole durable source of truth.
- [ ] Valkey loss cannot erase governance state.
- [ ] Transactional outbox semantics and duplicate-delivery consequences are acceptable.
- [ ] Task and milestone state machines match the approved governance workflow.
- [ ] M1 contains no Hermesctl implementation or inference-plane scope expansion.

## Security

- [ ] Database constraints enforce reviewer separation and evidence-bearing approval.
- [ ] Immutable tables reject update and delete operations.
- [ ] PostgreSQL rejects audit insertion with a non-contiguous previous hash.
- [ ] PostgreSQL rejects external review before all five internal gates pass.
- [ ] Audit deletion, reordering and payload mutation are detected.
- [ ] Evidence mutation is detected.
- [ ] Repository URL policy rejects credentials and unapproved hosts.
- [ ] Tool execution is scoped to one exact workspace.
- [ ] Shells, sudo, Git helper overrides and agent environment variables are denied.
- [ ] Sandbox absence causes denial rather than unsandboxed fallback.
- [ ] Only Caddy publishes host ports.
- [ ] Alloy has read-only log-file access and no Docker socket access.
- [ ] Recovery exhaustion is not automatically restarted by systemd.

## Reliability

- [ ] Queue consumer crashes result in stale-message reclaim.
- [ ] Exhausted messages reach the dead-letter stream.
- [ ] Queue retention cannot trim unacknowledged messages.
- [ ] Lease renewal and release require the original random token.
- [ ] Valkey outage leaves outbox records pending in PostgreSQL.
- [ ] Runtime dependency failure causes readiness failure and bounded restart.
- [ ] Supervisor recovery cannot alter governance state.

## Tests and evidence

- [ ] Unit tests pass.
- [ ] PostgreSQL/Valkey integration tests pass on Ubuntu 24.04 or CI.
- [ ] Coverage meets the configured 70% floor.
- [ ] Ruff formatting and lint checks pass.
- [ ] Strict mypy checks pass.
- [ ] Docker Compose renders from the documented environment file.
- [ ] Grafana Alloy configuration validates with the deployed Alloy image.
- [ ] The orchestrator image builds successfully.
- [ ] The supplied evidence-manifest signature verifies with the supplied public key.

## Decision

Party 3 must produce one of:

- `APPROVED` — all mandatory findings resolved;
- `REJECTED` — material architecture, security, test or documentation defects;
- `BLOCKED` — evidence or environment is insufficient to reach a decision.

The decision must identify the reviewer, evidence digests, findings and any required remediation. HADA must not synthesize or infer this decision.
