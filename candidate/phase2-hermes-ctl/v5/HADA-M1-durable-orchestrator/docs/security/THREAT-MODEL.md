# HADA M1 Threat Model

## Protected assets

- governance scope and gate decisions;
- audit-chain continuity and signing keys;
- evidence objects and manifests;
- Hermesctl source workspaces;
- database credentials and service secrets;
- task ownership, queue messages and leases;
- host, GPU and control-plane availability.

## Adversaries

1. A compromised or hallucinating Party 1 agent.
2. A malicious repository, test fixture or dependency.
3. A compromised Party 2 process attempting to mutate implementation output.
4. An external network actor reaching exposed services.
5. An operator mistake, service crash or partial infrastructure failure.
6. A local attacker able to alter state files but not the offline reviewer public key.

## Principal controls

### Governance integrity

Database constraints reject self-approval, evidence-free approval, Party 3 internal decisions and non-Party-3 external approval. Gate and policy records are protected by update/delete rejection triggers.

### Audit integrity

Each event commits with the related state mutation in the same PostgreSQL transaction. A database trigger serialises insertions, rejects an incorrect previous hash and assigns the next gapless sequence. Sequence continuity, previous hashes, event hashes and Ed25519 signatures are independently verifiable.

### Workspace isolation

Repository origins are restricted to approved hosts. Credentials in HTTPS URLs are rejected. Workspaces are detached at a recorded commit and stored under validated identifiers. Tool policy is scoped to one exact workspace, not the entire workspace root.

### Command execution

No agent shell is available. Agent environment injection is closed. Git helper/configuration override switches are rejected. Executables must resolve beneath trusted roots. Networkless commands require Bubblewrap. Output is bounded and secret-like values are redacted before persistence.

### Queue and lease safety

Valkey uses append-only persistence and `noeviction`. Queue messages remain pending until acknowledged, stale messages can be reclaimed and exhausted messages are dead-lettered. Streams are not length-trimmed because trimming can remove pending work. Lease renew/release operations compare a random ownership token atomically.

### Network exposure

PostgreSQL, Valkey, orchestrator, Prometheus, Loki and node-exporter use an internal Compose network. Only Caddy publishes host ports. Grafana is reachable through Caddy and does not allow public signup. Grafana Alloy reads Docker JSON log files through a read-only mount and is not given the Docker socket.

## Residual risks

- The host `hada` account belongs to the Docker group, which is root-equivalent. The supervisor requires Docker control; replacing this with a narrower privileged helper is deferred.
- Bubblewrap depends on unprivileged user namespaces and the host kernel configuration.
- A permitted interpreter can execute arbitrary code inside its sandbox. The network and filesystem boundaries, not source inspection, are the primary controls.
- The appliance signing key is stored on the same host as the orchestrator. A full host compromise can forge future records. Offline Party 3 retention of prior public keys and evidence bundles limits retrospective tampering but does not solve active host compromise.
- PostgreSQL and named service volumes require tested backups and restore drills, deferred to M6.
- Container image tags are pinned but not yet signed or verified by digest.

## Required M1 external-review tests

- mutate an audit payload and verify chain failure;
- delete or reorder an audit record and verify sequence failure;
- attempt self-approval and evidence-free approval;
- attempt Party 1 completion of its own task;
- attempt a workspace path escape and a Git `-c` override;
- stop Valkey during a committed outbox event and verify eventual publication;
- crash a queue consumer and verify stale reclaim;
- alter an evidence object and verify digest failure;
- attempt database update/delete against immutable tables;
- verify only Caddy exposes host ports.
