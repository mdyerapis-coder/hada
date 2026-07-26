# HADA M1 Phase A — Rollback Plan (Revised B0)

Generated: 2026-07-25T03:42:00Z
Revised: 2026-07-25 (human correction pass)
Revised: 2026-07-25 (B0 artifact correction pass)

## Overview

If the HADA M1 deployment fails validation or produces unexpected results,
the following rollback procedure restores the VM to a safe state.

Destructive cleanup operations have been REMOVED from this plan. They are
now in a separate document (destructive-cleanup-plan.md) that requires a
new, explicit human approval before any destructive action is taken.

## Rollback principles

1. Do NOT delete or recreate hada-control.
2. Do NOT delete, detach, resize, or recreate its disks.
3. Do NOT format /dev/sdb.
4. Do NOT delete or replace the hada-iap-ssh firewall rule.
5. Do NOT run `docker compose down -v` — this would delete named volumes
   and destroy persistent data (human decision #13).
6. Do NOT delete or reformat the persistent data disk.
7. Do NOT delete existing GCP resources.
8. Evidence files produced during Phase A are preserved.
9. Do NOT delete signing keys, evidence, workspaces, repositories, or
   Docker volume directories during automatic rollback.
10. Do NOT remove Docker packages during automatic rollback.
11. Do NOT run `docker container prune` during automatic rollback.

## Rollback steps (non-destructive)

All compose commands use BOTH files:
- `deploy/compose/compose.yaml`
- `deploy/compose/compose.gcp.yaml`

All container exec commands use `docker compose exec -T <service>` (not
hardcoded container names).

### Step R1: Stop the supervisor

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo systemctl stop hada-supervisor.service && \
    sudo systemctl disable hada-supervisor.service 2>/dev/null; true'
```

### Step R2: Stop and remove containers (WITHOUT removing volumes)

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='cd /opt/hada && \
    docker compose \
      -f deploy/compose/compose.yaml \
      -f deploy/compose/compose.gcp.yaml \
      --env-file .env down --remove-orphans 2>/dev/null; true'
```

CRITICAL: `docker compose down` is used WITHOUT the `-v` flag. The `-v` flag
would delete named volumes (including the driver_opts bind-mounted directories)
and is explicitly prohibited (HADA-TAKEOVER.md and human decision #13). The
`down` command without `-v` stops and removes containers but preserves all
volume data.

### Step R3: Remove the systemd service file

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo rm -f /etc/systemd/system/hada-supervisor.service && \
    sudo systemctl daemon-reload'
```

### Step R4: Remove /opt/hada directory

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo rm -rf /opt/hada'
```

### Step R5: Remove the hada service account (if needed)

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo userdel hada 2>/dev/null; sudo groupdel hada 2>/dev/null; true'
```

### Step R6: Docker data-root

Docker's global data-root was NOT relocated during deployment (human decision
#2). No /etc/docker/daemon.json was created. No Docker daemon restart is
needed for rollback. This step is a no-op.

### Step R7: Remove uploaded archive and staging directory from VM

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='rm -f /tmp/HADA-M1-durable-orchestrator.zip && \
    rm -rf /tmp/hada-staging /tmp/HADA-M1-durable-orchestrator'
```

## Operations REMOVED from automatic rollback

The following destructive operations were previously in the automatic
rollback plan. They have been REMOVED and moved to
destructive-cleanup-plan.md, which requires a new, explicit human approval.

- docker container prune (was Step R7)
- Deletion of signing keys (was Step R9)
- Deletion of evidence
- Deletion of workspaces
- Deletion of repositories
- Deletion of Docker volume directories (was Step R8)
- Docker package removal (was Step R11)

These are NOT performed during automatic rollback. The operator must not
perform them without reading destructive-cleanup-plan.md and obtaining
explicit human approval.

## Post-rollback verification

After rollback, verify the VM is in a clean state:

1. Confirm hada-control is still RUNNING:
   `gcloud compute instances describe hada-control ...`

2. Confirm /var/lib/hada is still mounted from /dev/sdb with correct UUID:
   `findmnt /var/lib/hada` and `blkid /dev/sdb`

3. Confirm /etc/fstab is unchanged (the data disk entry should remain).

4. Confirm the hada-iap-ssh firewall rule exists.

5. Confirm no HADA containers are running:
   `docker ps` (should show no HADA containers).

6. Confirm the systemd service is removed:
   `systemctl status hada-supervisor.service` (should fail).

7. Confirm /dev/sdb was NOT reformatted:
   `blkid /dev/sdb` (UUID must remain
   a1574097-cdf9-4d0a-ace0-adac63038e56).

## Prohibited rollback operations

Per HADA-TAKEOVER.md and human decision #13:

- Do NOT run `docker compose down -v` (deletes volumes).
- Do NOT delete or reformat the persistent data disk (/dev/sdb).
- Do NOT run mkfs against any device.
- Do NOT delete, detach, resize, or recreate disks.
- Do NOT delete or recreate hada-control.
- Do NOT run `docker container prune` (moved to destructive-cleanup-plan.md).
- Do NOT delete signing keys (moved to destructive-cleanup-plan.md).
- Do NOT delete evidence (moved to destructive-cleanup-plan.md).
- Do NOT delete workspaces (moved to destructive-cleanup-plan.md).
- Do NOT delete repositories (moved to destructive-cleanup-plan.md).
- Do NOT delete Docker volume directories (moved to destructive-cleanup-plan.md).
- Do NOT remove Docker packages (moved to destructive-cleanup-plan.md).

## Rollback decision authority

Per HADA-TAKEOVER.md governance:
- Hermes (the operator) may perform rollback if validation fails.
- The failure status is FAILED_VALIDATION or BLOCKED_REQUIRES_HUMAN_INPUT.
- Hermes must report the failure and await human direction.
- The only valid successful deployment status is
  IMPLEMENTATION_CANDIDATE_AWAITING_PARTY_3.
