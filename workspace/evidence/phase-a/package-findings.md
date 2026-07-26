# HADA M1 Phase A — Package Findings (Revised)

Generated: 2026-07-25T03:42:00Z
Revised: 2026-07-25 (human correction pass)

## 1. Archive integrity

- Archive: `HADA-M1-durable-orchestrator.zip` (141540 bytes)
- SHA-256: `51cbf075ff1fd5da481b6bec400a760e722aa4d1131c568dd79f8c070c3f4647`
- Files: 125 entries, 316577 bytes uncompressed
- Extraction was performed into a clean inspection directory only.
- No source files were modified during inspection.
- SHA256SUMS verification must be run from:
  `/home/bobthabuilda/hada-deployment/evidence/phase-a/`

## 2. Package assumptions and dependencies

### 2.1 Python runtime

- **Python 3.12** required (`requires-python = ">=3.12"` in pyproject.toml).
- The Dockerfile uses `python:3.12-slim-bookworm`.
- The host bootstrap (`scripts/bootstrap-ubuntu.sh`) installs `python3` and
  `python3-venv` from Ubuntu 24.04 repos (which provides Python 3.12).
- **Finding**: No version mismatch. Python 3.12 is available on Ubuntu 24.04 LTS.

### 2.2 Python dependencies (pyproject.toml)

| Package | Version constraint | Notes |
|---|---|---|
| cryptography | >=44,<47 | Ed25519 signing/verification |
| pydantic | >=2.10,<3 | Data models, validation |
| PyYAML | >=6.0,<7 | Config parsing |
| typer | >=0.15,<1 | CLI framework |
| rich | >=13.9,<15 | Console output |
| psycopg[binary] | >=3.2,<4 | PostgreSQL driver |
| redis | >=5.2,<7 | Valkey/Redis client |
| httpx | >=0.28,<1 | HTTP client |
| prometheus-client | >=0.21,<1 | Metrics exposition |

Dev dependencies: pytest>=8.3, pytest-cov>=6, ruff>=0.9, mypy>=1.14, types-PyYAML>=6.0.

**Finding**: All constraints are reasonable. The `psycopg[binary]` package bundles
libpq, so no system PostgreSQL client library is required.

### 2.3 Docker images (compose.yaml)

| Service | Image | Pinned? |
|---|---|---|
| postgres | postgres:17-alpine | Major version tag (not digest) |
| valkey | valkey/valkey:8-alpine | Major version tag |
| orchestrator | hada-orchestrator:0.2.0 | Built from local Dockerfile |
| prometheus | prom/prometheus:v3.2.1 | Exact version tag |
| loki | grafana/loki:3.4.2 | Exact version tag |
| alloy | grafana/alloy:v1.12.0 | Exact version tag |
| grafana | grafana/grafana:11.5.2 | Exact version tag |
| caddy | caddy:2.10-alpine | Minor version tag |
| node-exporter | prom/node-exporter:v1.9.0 | Exact version tag |

**Finding (F-001)**: Images use tags, not SHA-256 digests. The M1 exclusions list
in ARCHITECTURE.md explicitly excludes image digest pinning. This is an accepted
M1 limitation but should be tracked for M2.

### 2.4 System packages (bootstrap-ubuntu.sh)

The bootstrap script installs: `bubblewrap ca-certificates curl git gnupg jq
python3 python3-pip python3-venv rsync uidmap unattended-upgrades`.

Docker is installed from Docker's official apt repository (noble suite).

**Finding**: `bubblewrap` (bwrap) is critical for the execution sandbox.
The validate-host.sh script checks for its presence. If bwrap is unavailable,
the tool policy broker will deny all execution (fail-closed).

### 2.5 Service account

- UID/GID: 10001 (fixed, hardcoded in Dockerfile, bootstrap script, and
  validate-host.sh).
- Home directory: `/var/lib/hada`
- Shell: `/usr/sbin/nologin`
- The bootstrap script adds the `hada` user to the `docker` group.
- The systemd supervisor runs as `hada` with `SupplementaryGroups=docker`.

**Finding**: The fixed UID/GID 10001 must not conflict with any existing user
on the VM. The bootstrap script checks for this and exits if an existing
`hada` account has a different UID/GID.

## 3. Persistent state analysis (Phase A step 15)

### 3.1 Current /var/lib/hada mount

- `/var/lib/hada` is correctly mounted from `/dev/sdb` (100 GB data disk).
- UUID `a1574097-cdf9-4d0a-ace0-adac63038e56` matches the HADA-TAKEOVER.md spec.
- fstab entry: `/dev/disk/by-id/google-hada-data /var/lib/hada ext4 defaults,noatime 0 2`
- The data disk is essentially empty (76K used of 98G available).
- `autoDelete: false` on the data disk — it will survive VM deletion.

### 3.2 Docker persistent state — CRITICAL FINDING (F-002)

The compose.yaml uses **Docker named volumes** for all stateful services:

| Volume name | Service | Container path | Default host location |
|---|---|---|---|
| postgres-data | postgres | /var/lib/postgresql/data | /var/lib/docker/volumes/hada_postgres-data/_data |
| valkey-data | valkey | /data | /var/lib/docker/volumes/hada_valkey-data/_data |
| prometheus-data | prometheus | /prometheus | /var/lib/docker/volumes/hada_prometheus-data/_data |
| loki-data | loki | /loki | /var/lib/docker/volumes/hada_loki-data/_data |
| alloy-data | alloy | /var/lib/alloy/data | /var/lib/docker/volumes/hada_alloy-data/_data |
| grafana-data | grafana | /var/lib/grafana | /var/lib/docker/volumes/hada_grafana-data/_data |
| caddy-data | caddy | /data | /var/lib/docker/volumes/hada_caddy-data/_data |
| caddy-config | caddy | /config | /var/lib/docker/volumes/hada_caddy-config/_data |

**Problem**: Docker named volumes default to `/var/lib/docker/volumes/` which
is on the **30 GB boot disk** (`/dev/sda1`, mounted at `/`), NOT on the 100 GB
data disk (`/dev/sdb`, mounted at `/var/lib/hada`).

The HADA-TAKEOVER.md mandates: "All persistent HADA application state must reside
beneath /var/lib/hada/. Docker stateful service data must not be left on the
30 GB boot disk."

**Human decision applied (F-002)**: Use Docker named volumes with driver_opts
bind mounts beneath `/var/lib/hada/docker-volumes/`. Docker's global data-root
is NOT relocated. A production override file
`deploy/compose/compose.gcp.yaml` is created that defines each named volume
with `driver_opts: {type: none, o: bind, device: /var/lib/hada/docker-volumes/<name>}`.
This override is used together with the base `deploy/compose/compose.yaml`:

```bash
docker compose -f deploy/compose/compose.yaml -f deploy/compose/compose.gcp.yaml ...
```

### 3.3 Orchestrator state

The orchestrator container mounts `${HADA_STATE_DIR:-/var/lib/hada}:/var/lib/hada`.
This correctly places orchestrator state (evidence, keys, workspaces,
repositories, logs) on the data disk. The hada.yaml config confirms:
- `workspace_root: /var/lib/hada/workspaces`
- `evidence.root: /var/lib/hada/evidence`
- `evidence.signing_private_key: /var/lib/hada/keys/audit-signing-key.pem`
- `evidence.signing_public_key: /var/lib/hada/keys/audit-signing-key.pub.pem`

### 3.4 Directory structure under /var/lib/hada (from bootstrap-ubuntu.sh)

```
/var/lib/hada/
  evidence/          (content-addressed evidence store)
  keys/              (Ed25519 signing keys)
  repositories/      (bare Git mirrors)
  workspaces/        (Git worktrees per milestone/task)
  workspace-metadata/ (workspace metadata files)
  git-home/          (isolated HOME for git operations)
  logs/              (via tmpfs in container, /var/log/hada on host)
  docker-volumes/    (PROPOSED — for Phase B bind-mount backed named volumes)
```

### 3.5 Loki and Alloy container log path

The Alloy config reads from `/var/lib/docker/containers/*/*-json.log` (read-only
host mount in compose.yaml). This is Docker's default container log directory on
the boot disk. Since Docker's data-root is NOT being relocated (F-002 decision),
this path remains correct and the Alloy config + mount need no changes.

**Finding (F-003)**: RESOLVED. The decision not to relocate Docker's data-root
(remediation for F-002 uses driver_opts bind mounts, not data-root relocation)
means the Alloy log path `/var/lib/docker/containers` is correct and needs
no changes.

## 4. Network exposure analysis (Phase A step 16)

### 4.1 Compose network topology

```
ingress network (external)
  └── Caddy (bound to 127.0.0.1:80 via compose.gcp.yaml override)
      └── Grafana (3000 internal)

control network (internal, no external access)
  ├── PostgreSQL (5432)
  ├── Valkey (6379)
  ├── Prometheus (9090)
  ├── Loki (3100)
  ├── Alloy (12345)
  ├── Orchestrator (9108)
  └── Node Exporter (9100)
```

### 4.2 Published ports (after compose.gcp.yaml override)

Only Caddy publishes a host port: `127.0.0.1:80:80` (localhost-only). Port 443
is NOT published. All other services are on the internal `control` network with
no published ports. The orchestrator monitoring listener remains on
`0.0.0.0:9108` inside the container (per hada.yaml `monitoring.listen_host:
0.0.0.0`) but port 9108 is NOT published to the host — it is accessible only
on the internal Docker `control` network. Prometheus scrapes it at
`orchestrator:9108`.

### 4.3 Existing GCP firewall rules — CRITICAL FINDING (F-004)

The project has several **existing public firewall rules** that expose ports
80, 443, and 7000 to 0.0.0.0/0:

| Rule | Source | Ports | Status |
|---|---|---|---|
| allow-odysseus-http | 0.0.0.0/0 | TCP 80, 443 | Active |
| allow-odysseus-7000 | 0.0.0.0/0 | TCP 7000 | Active |
| default-allow-http | 0.0.0.0/0 | TCP 80 | Active |
| default-allow-https | 0.0.0.0/0 | TCP 443 | Active |

These rules have **no target tags**, so they apply to **all instances** in the
project, including hada-control.

**Impact**: If Caddy published `0.0.0.0:80`, that port would be publicly
accessible. However, with the `compose.gcp.yaml` override binding Caddy to
`127.0.0.1:80` only, Caddy is NOT publicly accessible despite these firewall
rules. Port 443 is not published at all.

**Human decision applied (F-004)**: Bind Caddy to `127.0.0.1` only. Use
localhost-only HTTP through IAP port forwarding. Disable public ACME
certificate issuance. Do NOT publish host port 443 unless a complete private
TLS design is documented. Administrative access uses:

```bash
gcloud compute ssh hada-control \
  --project=api-intergrations-501314 \
  --zone=australia-southeast1-b \
  --tunnel-through-iap \
  -- -L 8080:localhost:80
```

Then access `http://localhost:8080/grafana/` in the local browser.

### 4.4 Orchestrator health endpoint

The orchestrator listens on `0.0.0.0:9108` (from hada.yaml:
`monitoring.listen_host: 0.0.0.0`). Port 9108 is NOT published in
compose.yaml or compose.gcp.yaml — it is only accessible within the `control`
Docker network. Prometheus scrapes it at `orchestrator:9108`.

**Finding (F-005)**: The orchestrator's `listen_host: 0.0.0.0` is kept as-is
per the human decision. The listener stays on 0.0.0.0 inside the container.
Port 9108 remains unpublished and accessible only on the internal Docker
network. No action needed.

## 5. Docker data-root and disk capacity

### 5.1 Boot disk (30 GB)

- Currently 3.1G used of 29G (11% usage).
- Docker images, container layers, and logs would accumulate here by default.
- Estimated image pull sizes: PostgreSQL (~400MB), Valkey (~40MB),
  Prometheus (~200MB), Loki (~300MB), Alloy (~300MB), Grafana (~400MB),
  Caddy (~50MB), Node Exporter (~30MB), orchestrator (~300MB) = ~2GB total.
- Docker's global data-root is NOT relocated (per human decision). Docker
  images, container layers, and container logs remain on the boot disk, which
  has ~25GB free — sufficient for images and ephemeral layers.
- All stateful service data (PostgreSQL, Valkey, Prometheus, Loki, Alloy,
  Grafana, Caddy) is redirected to the data disk via driver_opts bind mounts.

### 5.2 Data disk (100 GB)

- Currently 76K used of 98G (0% usage).
- More than sufficient for all HADA persistent state.

## 6. Security observations

### 6.1 Secret handling

- `.env` is in `.gitignore` (line 1).
- `*.pem` is in `.gitignore` (line 13), with an exception for the public
  evidence-signing key.
- The `.env.example` contains placeholder values (`CHANGE_ME_*`), not real
  secrets.
- The compose.yaml reads secrets from environment variables, not from files
  committed to the repository.
- **Finding**: No secrets are stored in source files. Good.

**Human decision applied**: The incomplete sed-based secret provisioning
proposal is replaced with an atomic script
(`/home/bobthabuilda/hada-deployment/scripts/provision-secrets.sh`) that:
- generates each secret exactly once using `openssl rand -hex 32`;
- reuses each secret in its corresponding PASSWORD and DSN/URL;
- writes `/opt/hada/.env` atomically (temp file + mv);
- assigns root:hada ownership and mode 0640;
- never displays secrets;
- fails if any CHANGE_ME placeholder remains.

### 6.2 Container security

- All services use `no-new-privileges: true` and `cap_drop: [ALL]`.
- Stateful services add back only necessary capabilities (CHOWN, DAC_OVERRIDE,
  FOWNER, SETGID, SETUID).
- The orchestrator is `read_only: true` with tmpfs for `/tmp` and logs.
- Caddy adds only `NET_BIND_SERVICE` capability.
- Node Exporter uses `pid: host` and mounts `/` read-only — necessary for
  host metrics collection.

### 6.3 Valkey authentication

- Valkey runs with `--requirepass` and the healthcheck uses
  `valkey-cli -a ${VALKEY_PASSWORD} ping`.
- The HADA_VALKEY_URL in .env includes the password in the URL.
- **Finding (F-006)**: The Valkey password is passed via command line in
  compose.yaml, which is visible in `docker inspect`. This is a known Docker
  limitation. For M1, this is acceptable. M2 could use Docker secrets or
  a Valkey config file.

### 6.4 PostgreSQL authentication

- PostgreSQL uses environment variables for POSTGRES_PASSWORD.
- The HADA_DATABASE_DSN includes the password.
- No TLS is configured for PostgreSQL (internal network only).

### 6.5 Audit chain integrity

- The audit_events table uses a PostgreSQL trigger to enforce hash-chain
  continuity (migration 0002).
- Immutable tables (audit_events, evidence_artifacts, gate_decisions,
  policy_decisions, processed_messages) have `BEFORE UPDATE OR DELETE`
  triggers that reject mutations (migration 0002).
- The audit chain uses Ed25519 signatures verified against the appliance
  signing key.
- **Finding**: The audit and evidence design is sound. No defects found.

### 6.6 Governance enforcement

- Migration 0004 adds database-level enforcement of gate decision ordering:
  - Internal gates cannot be recorded while a milestone is stopped.
  - External review requires `external_review_required` stop state and
    all 5 internal gates approved.
  - Gate rejections/blocks set `human_input_required` stop reason.
- Self-approval is prevented by:
  `CHECK (status <> 'approved' OR reviewer_party <> subject_party)`.
- **Finding**: Governance is enforced at both the Python and PostgreSQL
  levels. Defense-in-depth is correctly implemented.

## 7. Container UID/GID requirements (human decision #7)

Each stateful container was inspected via `skopeo inspect --config` to
determine its effective UID/GID. Docker volumes backed by bind mounts must
have correct host directory ownership to avoid permission errors.

| Service | Container user | UID | GID | Host directory ownership | Mode |
|---|---|---|---|---|---|
| PostgreSQL | postgres | 70 | 70 | 70:70 | 0750 |
| Valkey | valkey | 999 | 1000 | 999:1000 | 0770 |
| Prometheus | nobody | 65534 | 65534 | 65534:65534 | 0755 |
| Loki | loki | 10001 | 10001 | 10001:10001 | 0750 |
| Alloy | alloy | 473 | 473 | 473:473 | 0770 |
| Grafana | grafana | 472 | 0 | 472:0 | 0750 |
| Caddy | root | 0 | 0 | 0:0 | 0755 |
| Orchestrator | hada | 10001 | 10001 | (bind mount /var/lib/hada, owned by hada) | 0750 |

**Finding (F-007)**: The original deployment plan proposed assigning all
volume directories to `hada:hada` (UID 10001:10001). This is INCORRECT for
PostgreSQL (needs 70:70), Valkey (needs 999:1000), Prometheus (needs
65534:65534), Alloy (needs 473:473), Grafana (needs 472:0), and Caddy (needs
0:0). Only Loki (10001:10001) and the orchestrator (10001:10001) match
`hada:hada`. Phase B must create each directory with the correct per-service
ownership. The deployment plan has been corrected with explicit
`install -d -o <uid> -g <gid> -m <mode>` commands for each volume.

## 8. Hermesctl repository accessibility (human decision #9)

Repository URL: https://github.com/mdyerapis-coder/hermesctl.git
Target branch: main

Three access verification points are required:

### 8.1 Local Fedora workstation — VERIFIED (Phase A)

```
$ git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main
da6d80bd9217600b8b15b862605ba87376d66604	refs/heads/main
```

Repository is reachable from this Fedora workstation. main branch resolves to
commit da6d80bd9217600b8b15b862605ba87376d66604.

### 8.2 hada-control (as hada service account) — MANDATORY PHASE B GATE

Phase B must verify:
```
gcloud compute ssh hada-control --tunnel-through-iap -- \
  'sudo -u hada git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main'
```

If credentials are required for HTTPS authentication to GitHub, report the
exact requirement without exposing credentials. The hada service account
shell is `/usr/sbin/nologin`; Phase B must use `sudo -u hada` or a wrapper
that does not require interactive login.

### 8.3 Orchestrator container — MANDATORY PHASE B GATE

Phase B must verify:
```
docker exec hada-orchestrator-1 git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main
```

The hada.yaml config lists `allowed_egress_hosts: github.com,
api.github.com, objects.githubusercontent.com` — these are sufficient for
git clone/fetch operations. The RepositoryPolicy in workspaces/manager.py
validates the repository URL host is in the allowlist before any clone occurs.

## 9. Deployment validation gaps (Phase B requirements)

The following Phase B validation items have corresponding source support:

| Validation item | Source support | Status |
|---|---|---|
| Persistent disk mounting | fstab entry verified | Ready |
| Docker Compose config | compose.yaml + compose.gcp.yaml + .env | Ready |
| PostgreSQL health/migrations | pg_isready healthcheck + migrate.py | Ready |
| Governance constraints | migrations 0001-0004 | Ready |
| Authenticated Valkey | --requirepass + healthcheck | Ready |
| Orchestrator liveness/readiness | /healthz + /readyz endpoints | Ready |
| Immutable audit records | hada_reject_mutation trigger | Ready |
| Audit signing/chain verification | Ed25519 + SHA-256 chain | Ready |
| Bounded workspace creation | WorkspaceManager with path validation | Ready |
| Hermesctl repo accessibility (local) | git ls-remote verified | Ready |
| Hermesctl repo accessibility (remote) | Phase B gate (hada-control + container) | Pending |
| Watchdog recovery behaviour | supervisor.sh bounded restart | Ready |
| Service recovery following reboot | systemd hada-supervisor.service | Ready |
| Absence of public listeners | Caddy bound to 127.0.0.1 via override | Ready |
| Persistence after reboot | Data disk + systemd | Ready |

## 10. Summary of findings

| ID | Severity | Description | Status |
|---|---|---|---|
| F-001 | Low | Docker images use tags, not digests. Accepted M1 exclusion. | Accepted |
| F-002 | Critical | Docker named volumes default to boot disk. Remediated via driver_opts bind mounts in compose.gcp.yaml. | Remediated |
| F-003 | Medium | Alloy log path depends on Docker data-root location. Resolved (data-root not relocated). | Resolved |
| F-004 | Critical | Existing public firewall rules expose ports 80/443/7000. Caddy bound to 127.0.0.1, port 443 unpublished. | Remediated |
| F-005 | Low | Orchestrator listens on 0.0.0.0 (not published). Kept as-is per human decision. | Accepted |
| F-006 | Low | Valkey password visible in docker inspect. Accepted for M1. | Accepted |
| F-007 | Medium | Volume directories need per-service UID/GID, not uniform hada:hada. Corrected in deployment plan. | Remediated |
