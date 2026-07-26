# M1 Milestone Report — Durable Orchestrator

## Milestone status

**Implementation candidate complete; not approved.**

This report records Party 1 implementation evidence only. It does not represent Party 2 or Party 3 approval. M1 remains stopped at the independent-review boundary.

## Scope completed

- ordered, checksummed PostgreSQL migration runner;
- durable milestone, task, workspace, evidence, gate, policy, outbox, processed-message and audit schemas;
- database-enforced party separation, gate sequencing, stop-state transitions and immutable decision records;
- database-enforced gapless audit sequence and previous-hash continuity;
- optimistic task lifecycle with Party 2 review-outcome enforcement and milestone-stop checks;
- Ed25519 key generation, loading, signing and verification;
- canonical JSON, SHA-256 evidence addressing and signed manifests;
- globally ordered signed audit hash chain;
- Valkey Streams queues with consumer groups, stale reclaim and durable dead-letter handling;
- no length trimming of unacknowledged or dead-letter queue records;
- token-bound renewable leases;
- transactional outbox and stable queue message IDs;
- approved-origin Git mirrors and detached, commit-pinned task worktrees;
- fail-closed policy engine and Bubblewrap executor;
- orchestrator readiness, liveness and Prometheus metrics;
- non-root orchestrator image and segmented Compose networks;
- Prometheus alerts, Grafana dashboard, Loki and Grafana Alloy log shipping;
- bounded supervisor recovery that systemd does not restart after exhaustion;
- bootstrap, validation, recovery and security documentation;
- unit and optional live-service integration tests;
- signed M1 evidence bundle and offline verification script.

## Scope deliberately excluded

- local inference deployment;
- Party 1 coding-agent prompts and autonomous patch loop;
- Party 2 adversarial-agent prompts and review loop;
- Party 3 decision import and milestone closure;
- Hermesctl modification;
- backup automation and restore drills;
- container image signing, digest pinning and SBOM;
- automatic signing-key rotation.

## Validation performed in the construction environment

- Python compilation: passed.
- Shell syntax validation: passed.
- HADA configuration model validation: passed.
- YAML, TOML and Grafana dashboard JSON parsing: passed.
- Unit and offline tests: 48 passed.
- Live-service integration tests: 2 correctly skipped because PostgreSQL and Valkey were unavailable.
- Non-integration coverage: 77%, above the 70% gate.
- Python wheel build without build isolation: passed.
- Git workspace creation from a local repository and pinned commit: passed.
- Sandboxed-executor code path without Bubblewrap wrapping: passed using `shell=False` and resource limits.
- Source-tree SHA-256 inventory and signed evidence index: generated and locally verified.

## Validation configured but not executable in the construction environment

The construction environment did not provide Ruff, mypy, Docker, PostgreSQL, Valkey or Bubblewrap. Therefore the following could not be executed locally:

- Ruff formatting and linting;
- strict mypy checking;
- live PostgreSQL migration, trigger and immutability tests;
- live Valkey Streams integration;
- Docker Compose semantic rendering;
- Docker image build and container-health validation;
- Grafana Alloy native configuration validation;
- Bubblewrap namespace execution on Ubuntu 24.04;
- fresh Vast.ai Ubuntu 24.04 provisioning.

GitHub Actions is configured to run Ruff, mypy, unit and integration tests against PostgreSQL 17 and Valkey 8, coverage, Compose rendering, Alloy validation and image build on Ubuntu 24.04. These results and a live Vast.ai validation are mandatory evidence before Party 3 may approve M1.

## Security and reliability findings corrected during implementation

1. Immutable-trigger identifiers were initially assembled incorrectly. Trigger names are now fully quoted PostgreSQL identifiers.
2. Tool policy initially bounded commands to the overall workspace root. It now validates and binds one exact task workspace.
3. Policy audit records were initially duplicated. The PostgreSQL store now records policy decision and audit atomically; the broker records only the execution result separately.
4. Approval evidence references are restricted to `sha256:<64 lowercase hexadecimal characters>` in both the model and database.
5. Governance decisions are immutable, internal gates require Party 2, external review requires Party 3, and PostgreSQL blocks early external review or internal progress after a stop.
6. Audit continuity was initially guarded only by application locking. PostgreSQL now independently serialises insertions, verifies the prior hash and assigns the next sequence.
7. Existing evidence-digest conflicts no longer silently accept inconsistent metadata or paths.
8. Embedded SSH passwords and option-like Git refs are rejected before Git execution.
9. Queue length trimming was removed because Redis stream trimming can delete pending work or forensic dead-letter records.
10. The supervisor's Compose health parser was corrected for JSON-array output and empty service sets.
11. Recovery exhaustion is protected with `RestartPreventExitStatus`, preventing systemd from resetting the bounded-recovery stop condition.
12. PostgreSQL and Valkey retain only the Linux capabilities their official entrypoints require to initialise volumes and drop privileges.
13. Promtail was replaced with Grafana Alloy, using a read-only Docker log-file mount and no Docker socket.

## Residual risks

- Docker-group membership remains root-equivalent for the host supervisor account.
- The appliance signing key resides on the same host as the orchestrator.
- Outbox delivery is at-least-once and downstream workers must deduplicate stable message IDs.
- Bubblewrap availability and kernel namespace policy require live Vast.ai validation.
- Docker JSON log access exposes all container stdout/stderr to Alloy; secret redaction must remain effective.
- Container images are version-tagged but not digest-pinned or signed.
- The supplied evidence public key must be authenticated out of band; a public key bundled with its own evidence is tamper-evident only after the reviewer records its fingerprint independently.
- Backup and restore procedures are documented but not yet automated or drilled.

## Governance outcome

M1 must enter `EXTERNAL_REVIEW_REQUIRED` after all five internal gates have valid, content-addressed evidence. It must not be marked complete until Party 3 independently verifies the source and evidence bundle and returns a signed decision.

The next milestone is **M2 — Local Inference Plane**, but its activation requires M1 approval plus human selection of the Vast.ai GPU and storage baseline, approved model profiles, model licences and the vLLM/SGLang deployment policy.
