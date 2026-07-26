# HADA M1 Phase A — Production Deployment Plan (Revised)

Generated: 2026-07-25T03:42:00Z
Revised: 2026-07-25 (human correction pass)

## Overview

This plan deploys the HADA M1 Durable Orchestrator onto the existing
hada-control VM (project api-intergrations-501314, zone australia-southeast1-b)
using the archive HADA-M1-durable-orchestrator.zip.

All persistent state will reside beneath /var/lib/hada/ on the 100 GB data
disk. No services will be publicly exposed. Administrative access uses IAP SSH.

## Compose file structure (human decision #4)

The deployment uses TWO compose files together:

1. `deploy/compose/compose.yaml` — the base file shipped in the archive.
2. `deploy/compose/compose.gcp.yaml` — the production override created in
   Phase A at `/home/bobthabuilda/hada-deployment/deploy/compose/compose.gcp.yaml`.

The override (compose.gcp.yaml) applies:
- Docker named volumes with driver_opts bind mounts beneath
  /var/lib/hada/docker-volumes/ (F-002 remediation, human decision #1).
- Caddy bound to 127.0.0.1:80 only (F-004 remediation, human decision #6).
- A production Caddyfile (Caddyfile.gcp) with ACME disabled and HTTP-only.

All commands that reference compose must use both files:

```bash
docker compose -f deploy/compose/compose.yaml -f deploy/compose/compose.gcp.yaml --env-file .env ...
```

Docker's global data-root is NOT relocated (human decision #2). Docker images,
container layers, and container logs remain on the boot disk. Only stateful
service data is redirected to the data disk via driver_opts bind mounts.

## Prerequisites (verified in Phase A)

1. hada-control VM is RUNNING with Ubuntu 24.04.4 LTS.
2. Data disk /dev/sdb (100 GB) is mounted at /var/lib/hada with correct UUID.
3. /etc/fstab has persistent mount entry for the data disk.
4. IAP SSH access is functional via gcloud compute ssh --tunnel-through-iap.
5. Docker is installed but not yet configured for HADA.
6. The hada service account (UID/GID 10001) does not yet exist on the VM.
7. Hermesctl repository is reachable from the local Fedora workstation.
   Remote checks (hada-control + orchestrator container) are mandatory
   Phase B gates.

## Phase B deployment steps

### Step B1: Transfer candidate archive to VM and verify integrity

Upload the GCP candidate archive (HADA-M1-gcp-candidate.zip) to hada-control
via IAP SSH. This archive contains the original source tree with all reviewed
production changes overlaid — no ad-hoc source-code patching is performed
after bootstrap.

```bash
gcloud compute scp HADA-M1-gcp-candidate.zip hada-control:/tmp/ \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

# Verify archive integrity on the remote host before extraction
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='cd /tmp && \
    sha256sum HADA-M1-gcp-candidate.zip && \
    echo "Expected: f73887bd198ff158c32b3b90f8984d015fff526ba41c5de3a3ce9b6cdeded30f"'
```

The SHA-256 must match:
`9da95a53eac87d6b2f2860f2b3944d39d66f85882848f9a69b88f06909c14371`

### Step B2: Extract into a clean staging directory and run bootstrap

Extract into a clean staging directory (human decision #11), verify paths,
then invoke the reviewed bootstrap script from that directory.

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='cd /tmp && \
    rm -rf /tmp/hada-staging && \
    mkdir -p /tmp/hada-staging && \
    cd /tmp/hada-staging && \
    unzip -o /tmp/HADA-M1-gcp-candidate.zip && \
    ls -la HADA-M1-durable-orchestrator/scripts/bootstrap-ubuntu.sh && \
    sudo bash HADA-M1-durable-orchestrator/scripts/bootstrap-ubuntu.sh'
```

The bootstrap script (scripts/bootstrap-ubuntu.sh) will:
- Install system packages (bubblewrap, git, jq, etc.)
- Install Docker CE from Docker's official apt repository
- Create the hada service account (UID/GID 10001)
- Create /opt/hada directory structure
- rsync source files to /opt/hada
- Create Python venv and install hada package
- Generate Ed25519 signing keys if none exist
- Install systemd supervisor service
- Enable docker.service

Docker's global data-root is NOT modified. No /etc/docker/daemon.json is
created or modified (human decision #2).

### Step B3: Create Docker volume directories with per-service UID/GID

Create the bind-mount directories under /var/lib/hada/docker-volumes/ with
correct per-service ownership (human decisions #1 and #7). Each directory
must match the effective UID/GID of the container that writes to it.

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo install -d -o 70   -g 70   -m 0750 /var/lib/hada/docker-volumes/postgres-data && \
    sudo install -d -o 999  -g 1000 -m 0770 /var/lib/hada/docker-volumes/valkey-data && \
    sudo install -d -o 65534 -g 65534 -m 0755 /var/lib/hada/docker-volumes/prometheus-data && \
    sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/hada/docker-volumes/loki-data && \
    sudo install -d -o 473  -g 473  -m 0770 /var/lib/hada/docker-volumes/alloy-data && \
    sudo install -d -o 472  -g 0    -m 0750 /var/lib/hada/docker-volumes/grafana-data && \
    sudo install -d -o 0    -g 0    -m 0755 /var/lib/hada/docker-volumes/caddy-data && \
    sudo install -d -o 0    -g 0    -m 0755 /var/lib/hada/docker-volumes/caddy-config'
```

Container UID/GID requirements (verified via skopeo inspect):

| Service | UID | GID | Directory ownership | Mode |
|---|---|---|---|---|
| PostgreSQL | 70 | 70 | 70:70 | 0750 |
| Valkey | 999 | 1000 | 999:1000 | 0770 |
| Prometheus | 65534 | 65534 | 65534:65534 | 0755 |
| Loki | 10001 | 10001 | 10001:10001 | 0750 |
| Alloy | 473 | 473 | 473:473 | 0770 |
| Grafana | 472 | 0 | 472:0 | 0750 |
| Caddy | 0 | 0 | 0:0 | 0755 |

### Step B4: Copy compose.gcp.yaml, Caddyfile.gcp, and production scripts to VM

The candidate archive already contains all production overlays (compose.gcp.yaml,
Caddyfile.gcp, supervisor.sh, validate-host.sh, provision-secrets.sh, updated
models.py, health.py, hada.yaml, and test_compose_files.py). If the archive was
extracted and the bootstrap rsync installed the files to /opt/hada, these
files are already in place and no separate copy is needed.

If the bootstrap did not install the overlay files (e.g., the bootstrap only
copies the base archive), then copy the overlay files separately:

```bash
gcloud compute scp \
  /home/bobthabuilda/hada-deployment/deploy/compose/compose.gcp.yaml \
  hada-control:/tmp/compose.gcp.yaml \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

gcloud compute scp \
  /home/bobthabuilda/hada-deployment/deploy/caddy/Caddyfile.gcp \
  hada-control:/tmp/Caddyfile.gcp \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

gcloud compute scp \
  /home/bobthabuilda/hada-deployment/scripts/supervisor.gcp.sh \
  hada-control:/tmp/supervisor.gcp.sh \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

gcloud compute scp \
  /home/bobthabuilda/hada-deployment/scripts/validate-host.gcp.sh \
  hada-control:/tmp/validate-host.gcp.sh \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo install -m 0644 -o root -g hada /tmp/compose.gcp.yaml /opt/hada/deploy/compose/compose.gcp.yaml && \
    sudo install -m 0644 -o root -g hada /tmp/Caddyfile.gcp /opt/hada/deploy/caddy/Caddyfile.gcp && \
    sudo install -m 0755 -o root -g hada /tmp/supervisor.gcp.sh /opt/hada/scripts/supervisor.sh && \
    sudo install -m 0755 -o root -g hada /tmp/validate-host.gcp.sh /opt/hada/scripts/validate-host.sh'
```

### Step B5: Provision secrets atomically

Copy and run the atomic secret provisioning script (human decision #8).

```bash
gcloud compute scp \
  /home/bobthabuilda/hada-deployment/scripts/provision-secrets.sh \
  hada-control:/tmp/provision-secrets.sh \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap

gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo bash /tmp/provision-secrets.sh'
```

The script (scripts/provision-secrets.sh):
- generates each secret exactly once using `openssl rand -hex 32`;
- reuses each secret in its corresponding PASSWORD and DSN/URL;
- writes /opt/hada/.env atomically (temp file + mv);
- assigns root:hada ownership and mode 0640;
- never displays secrets;
- fails if any CHANGE_ME placeholder remains.

### Step B6: Configure hada.yaml

Update /opt/hada/config/hada.yaml:
- Set project.target_repository to the Hermesctl URL.
- The compose_files list is already in the shipped config (code change:
  compose_file -> compose_files list[Path] with backward-compatible
  validator; see evidence/phase-b0/code-change-compose-files.md).
- Keep monitoring.listen_host as 0.0.0.0 (human decision #5: orchestrator
  monitoring listener stays on 0.0.0.0 inside the container; port 9108
  remains unpublished and accessible only on the internal Docker network).
- No sed patching of compose_file — the config uses compose_files list
  natively.

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo sed -i \
    -e "s|target_repository: \"\"|target_repository: \"https://github.com/mdyerapis-coder/hermesctl.git\"|" \
    /opt/hada/config/hada.yaml'
```

Note: The updated hada.yaml already contains:
  infrastructure:
    compose_files:
      - /opt/hada/deploy/compose/compose.yaml
      - /opt/hada/deploy/compose/compose.gcp.yaml
This is a native list, not a shell argument string.

### Step B7: Run validate-host.sh (with both compose files)

The host validator must use both compose files (human decision #4). The
production validate-host.gcp.sh (installed as /opt/hada/scripts/validate-host.sh
in Step B4) uses BOTH compose files natively.

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo /opt/hada/scripts/validate-host.sh'
```

The production validate-host.gcp.sh (installed as
/opt/hada/scripts/validate-host.sh) uses BOTH compose files natively.
No sed patching is required — the production script replaces the shipped
version entirely (see Step B4).

### Step B8: Build and start services (with both compose files)

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='cd /opt/hada && \
    docker compose \
      -f deploy/compose/compose.yaml \
      -f deploy/compose/compose.gcp.yaml \
      --env-file .env up -d'
```

### Step B9: Run database migrations

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo -u hada /opt/hada/.venv/bin/hada db migrate \
    --config /opt/hada/config/hada.yaml'
```

Or rely on the container-entrypoint.sh which runs migrations automatically
on orchestrator startup.

### Step B10: Enable and start the systemd supervisor (with both compose files)

The production supervisor.gcp.sh (installed as /opt/hada/scripts/supervisor.sh
in Step B4) uses BOTH compose files natively.

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  --command='sudo systemctl enable --now hada-supervisor.service'
```

The supervisor will:
- Start docker compose (with both files) if not running.
- Monitor container health.
- Perform bounded recovery (max 3 attempts).
- Exit with code 70 if recovery is exhausted.
- systemd will restart the supervisor on failure.

### Step B11: Validation suite

Run all Phase B validation checks (see proposed-commands.sh):
1. Verify /var/lib/hada is still mounted from /dev/sdb
2. Verify docker compose config is valid (with both files)
3. Verify PostgreSQL is healthy and migrations applied
4. Verify governance constraints (self-approval rejected)
5. Verify Valkey requires authentication
6. Verify orchestrator /healthz and /readyz respond (via container exec)
7. Verify audit records are immutable (UPDATE/DELETE rejected)
8. Verify audit chain signing and hash continuity
9. Verify bounded workspace creation works with Hermesctl repo
10. Verify Hermesctl repo is accessible from the orchestrator container
    (MANDATORY Phase B gate)
11. Verify Hermesctl repo is accessible from hada-control as the hada
    service account (MANDATORY Phase B gate)
12. Verify supervisor recovery behaviour
13. Verify no unexpected public listeners (ss/netstat)
14. Verify state persistence after reboot

## Mandatory Phase B design requirements compliance

### Persistent data
- All Docker volumes use driver_opts bind mounts to
  /var/lib/hada/docker-volumes/ (via compose.gcp.yaml).
- PostgreSQL, Valkey, Prometheus, Loki, Alloy, Grafana, Caddy data, and
  Caddy config will reside on the 100 GB data disk.
- Orchestrator state (evidence, keys, workspaces, repositories) already
  uses /var/lib/hada/ via the compose volume mount.
- Docker's global data-root is NOT relocated.

### Network exposure
- No new public firewall rules will be created.
- Caddy ports are bound to 127.0.0.1 only (via compose.gcp.yaml).
- Port 443 is NOT published.
- ACME certificate issuance is disabled (Caddyfile.gcp).
- Administrative access uses IAP SSH port forwarding.
- Orchestrator port 9108 is NOT published; listener stays on 0.0.0.0
  inside the container, accessible only on the internal Docker network.
- PostgreSQL, Valkey, Prometheus, Loki, Alloy, Grafana, Docker daemon,
  and internal health endpoints will not be publicly exposed.

### Deployment validation
All 14 validation items from HADA-TAKEOVER.md will be tested (Step B11).
