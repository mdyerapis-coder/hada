# PostgreSQL and Audit Recovery Runbook

## Principles

PostgreSQL is the authoritative state store. Recovery must preserve audit sequence, hashes, signatures, immutable decisions and migration history.

## Before recovery

1. Stop the HADA supervisor and orchestrator publisher.
2. Snapshot the PostgreSQL volume or disk.
3. Export the appliance public signing key.
4. Record the incident start time and observed final audit sequence.
5. Do not rotate the signing key or edit migration files.

## Integrity checks

```bash
hada audit verify --config /opt/hada/config/hada.yaml
```

Inspect migration checksums:

```sql
SELECT version, checksum, applied_at
FROM schema_migrations
ORDER BY version;
```

Inspect audit continuity:

```sql
SELECT sequence, event_id, previous_hash, event_hash, signer_key_id
FROM audit_events
ORDER BY sequence;
```

## Restore requirements

A valid restore must include:

- the complete PostgreSQL database;
- `/var/lib/hada/evidence` objects and manifests;
- the public key used to verify existing records;
- the private key only when continued operation on the same trust identity is authorised;
- workspace metadata and repository mirror references as required by the active milestone.

After restore, run migrations, verify the entire audit chain, verify every evidence manifest referenced by an approved gate, then start Valkey and the orchestrator. Pending outbox rows will republish with stable IDs.

## Prohibited recovery actions

- deleting an audit row to remove a verification error;
- updating immutable decision or evidence rows;
- changing an applied migration checksum;
- marking outbox rows published without queue evidence;
- importing a private key of unknown provenance;
- approving a milestone solely because service health has recovered.
