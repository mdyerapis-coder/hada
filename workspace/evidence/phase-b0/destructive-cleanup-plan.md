# HADA M1 — Destructive Cleanup Plan

Generated: 2026-07-25
Status: REQUIRES EXPLICIT HUMAN APPROVAL BEFORE EXECUTION

## WARNING

The operations in this document are DESTRUCTIVE and IRREVERSIBLE. They will
permanently delete data, signing keys, evidence, workspaces, repositories,
and Docker volume directories. They may also remove Docker packages.

These operations have been REMOVED from the automatic rollback plan
(rollback-plan.md). They must NOT be executed automatically or as part of
a routine rollback.

A new, explicit human approval is REQUIRED before any operation in this
document is executed. The operator must:

1. Read this document in full.
2. Confirm in writing that data loss is acceptable.
3. Obtain explicit approval from the human decision-maker.
4. Execute each step individually, confirming the result before proceeding.

## Prerequisites for approval

Before approving destructive cleanup, verify:

1. The deployment has been rolled back using the non-destructive rollback
   plan (rollback-plan.md Steps R1–R7).

2. Post-rollback verification (rollback-plan.md) confirms the VM is in a
   safe state.

3. Any data that needs to be preserved has been backed up.

4. The human decision-maker understands that the following will be
   permanently destroyed:
   - All signing keys (audit signature keys)
   - All evidence artifacts
   - All workspace data
   - All repository clones
   - All Docker volume data (PostgreSQL, Valkey, Prometheus, Loki, Alloy,
     Grafana, Caddy data, Caddy config)
   - All stopped/unused Docker containers

## Destructive cleanup steps

### Step DC1: Remove Docker container data (if any)

This removes all stopped containers, not just HADA containers. Exercise
caution if the VM hosts non-HADA containers.

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='docker container prune -f 2>/dev/null; true'
```

### Step DC2: Remove HADA Docker volume directories

This permanently deletes all persistent service data stored on the data
disk: PostgreSQL databases, Valkey data, Prometheus metrics, Loki logs,
Alloy data, Grafana dashboards, Caddy data and config.

Do NOT delete the /var/lib/hada mount point itself — it is the mount for
/dev/sdb and must not be removed.

```bash
# ONLY AFTER EXPLICIT HUMAN APPROVAL — DATA LOSS IS IRREVERSIBLE
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo rm -rf /var/lib/hada/docker-volumes'
```

Note: This removes Docker volume data that was created on the data disk
during deployment. The /var/lib/hada mount point itself is preserved.
Do NOT reformat /dev/sdb. Do NOT run mkfs against any device.

### Step DC3: Remove signing keys, evidence, workspaces, and repositories

This permanently deletes:
- /var/lib/hada/keys (Ed25519 signing keys)
- /var/lib/hada/evidence (signed evidence artifacts)
- /var/lib/hada/workspaces (agent workspaces)
- /var/lib/hada/repositories (cloned repositories)
- /var/lib/hada/workspace-metadata
- /var/lib/hada/git-home

```bash
# ONLY AFTER EXPLICIT HUMAN APPROVAL — KEYS AND EVIDENCE ARE IRREVERSIBLE
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo rm -rf /var/lib/hada/keys /var/lib/hada/evidence /var/lib/hada/workspaces /var/lib/hada/repositories /var/lib/hada/workspace-metadata /var/lib/hada/git-home'
```

### Step DC4: Uninstall Docker packages (optional)

Only if Docker was not present before the deployment and should be removed:

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo apt-get remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null; true'
```

This step is OPTIONAL. Docker itself is not harmful to leave installed.

## Post-cleanup verification

After destructive cleanup, verify:

1. /var/lib/hada/docker-volumes no longer exists:
   `ls -la /var/lib/hada/` (should not show docker-volumes)

2. /var/lib/hada/keys no longer exists:
   `ls -la /var/lib/hada/` (should not show keys)

3. /var/lib/hada mount point still exists and /dev/sdb is still mounted:
   `findmnt /var/lib/hada` (must still show /dev/sdb)

4. /dev/sdb UUID is unchanged:
   `blkid /dev/sdb` (must still be a1574097-cdf9-4d0a-ace0-adac63038e56)

5. If Docker packages were removed, `docker --version` should fail.

## Prohibited

- Do NOT reformat /dev/sdb.
- Do NOT run mkfs against any device.
- Do NOT delete, detach, resize, or recreate disks.
- Do NOT delete or recreate hada-control.
- Do NOT delete or replace the hada-iap-ssh firewall rule.
- Do NOT run `docker compose down -v` (this is not a cleanup tool; it
  destroys named volumes during operation).
