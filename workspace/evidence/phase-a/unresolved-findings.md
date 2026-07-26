# HADA M1 Phase A — Unresolved Findings (Revised)

Generated: 2026-07-25T03:42:00Z
Revised: 2026-07-25 (human correction pass)

## Status

Phase A inspection is complete. All evidence files have been produced.
The human correction pass has been applied. The following findings
remain open and require Phase B action or human review.

## Findings resolved by human decisions

### F-002 (CRITICAL): Docker named volumes default to boot disk — RESOLVED

**Description**: The compose.yaml uses Docker named volumes for all stateful
services. By default, these are stored under /var/lib/docker/volumes/ on
the 30 GB boot disk, not on the 100 GB data disk at /var/lib/hada/.

**Human decision applied**: Use Docker named volumes with driver_opts bind
mounts beneath /var/lib/hada/docker-volumes/. Docker's global data-root is
NOT relocated. A production override file
`deploy/compose/compose.gcp.yaml` has been created defining each named
volume with `driver_opts: {type: none, o: bind,
device: /var/lib/hada/docker-volumes/<name>}`.

**Status**: RESOLVED. The override is ready for Phase B.

### F-003 (MEDIUM): Alloy log path depends on Docker data-root — RESOLVED

**Description**: The Alloy configuration reads Docker JSON logs from
/var/lib/docker/containers/*/*-json.log. If Docker's data-root is
relocated, this path changes.

**Resolution**: Docker's data-root is NOT being relocated (human decision #2).
The Alloy config path /var/lib/docker/containers is correct and needs no
changes.

**Status**: RESOLVED.

### F-004 (CRITICAL): Existing public firewall rules expose ports 80/443 — RESOLVED

**Description**: The GCP project has existing firewall rules that expose
ports 80, 443, and 7000 to 0.0.0.0/0 on ALL instances.

**Human decision applied**: Bind Caddy to localhost only. Use localhost-only
HTTP through IAP port forwarding. Disable public ACME certificate issuance.
Do NOT publish host port 443 unless a complete private TLS design is
documented. The compose.gcp.yaml override binds Caddy to 127.0.0.1:80 only.
Port 443 is not published. A production Caddyfile (Caddyfile.gcp) disables
ACME and uses HTTP-only.

**Status**: RESOLVED. No GCP firewall rules are modified.

### F-005 (LOW): Orchestrator listens on 0.0.0.0 — RESOLVED

**Description**: The orchestrator runtime listens on 0.0.0.0:9108.

**Human decision applied**: Keep the orchestrator monitoring listener on
0.0.0.0 inside the container. Port 9108 must remain unpublished and
accessible only on the internal Docker network.

**Status**: RESOLVED. No changes to hada.yaml monitoring.listen_host.
Port 9108 is not published in compose.yaml or compose.gcp.yaml.

### F-007 (MEDIUM): Volume directories need per-service UID/GID — RESOLVED

**Description**: The original deployment plan proposed assigning all volume
directories to hada:hada (UID 10001:10001). This is incorrect for
PostgreSQL (70:70), Valkey (999:1000), Prometheus (65534:65534),
Alloy (473:473), Grafana (472:0), and Caddy (0:0). Only Loki (10001:10001)
and the orchestrator (10001:10001) match hada:hada.

**Resolution**: The deployment plan has been corrected with explicit
per-service `install -d -o <uid> -g <gid> -m <mode>` commands for each
volume directory.

**Status**: RESOLVED.

## Findings accepted for M1 (no action required)

### F-001 (LOW): Docker images use tags, not digests

**Description**: All Docker images in compose.yaml use version tags rather
than SHA-256 digests.

**Resolution**: The M1 exclusions list in ARCHITECTURE.md explicitly excludes
image digest pinning. No action needed for M1. Track for M2.

**Status**: Accepted.

### F-006 (LOW): Valkey password visible in docker inspect

**Description**: The Valkey password is passed via command-line argument in
compose.yaml, visible in docker inspect output.

**Resolution**: Accepted for M1. M2 could use Docker secrets or a Valkey
config file.

**Status**: Accepted.

## Mandatory Phase B gates (human decision #9)

The following checks could not be completed during Phase A and are
mandatory Phase B gates:

### B-GATE-1: Hermesctl repository access from hada-control

**Requirement**: Verify `git ls-remote` succeeds when run on hada-control
as the hada service account (not just from the local Fedora workstation).

**Command**:
```
gcloud compute ssh hada-control --tunnel-through-iap -- \
  'sudo -u hada git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main'
```

**Credential requirement**: If HTTPS authentication to GitHub is required,
report the exact requirement without exposing credentials. The hada service
account shell is /usr/sbin/nologin; Phase B must use `sudo -u hada` or a
wrapper that does not require interactive login. If a GitHub personal access
token or deploy key is required, document the exact type and scope needed
without storing the secret in evidence files.

**Status**: PENDING — mandatory Phase B gate.

### B-GATE-2: Hermesctl repository access from the orchestrator container

**Requirement**: Verify `git ls-remote` succeeds when run inside the
orchestrator container.

**Command**:
```
docker exec hada-orchestrator-1 git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main
```

**Context**: The hada.yaml config lists allowed_egress_hosts: github.com,
api.github.com, objects.githubusercontent.com. The RepositoryPolicy in
workspaces/manager.py validates the repository URL host is in the allowlist.

**Status**: PENDING — mandatory Phase B gate.

## Phase B corrections to shipped scripts (RESOLVED in B0)

The following shipped scripts previously hardcoded a single compose file
path. They have been corrected in the B0 artifact pass:

1. **validate-host.sh**: Replaced by production validate-host.gcp.sh that
   uses both compose files natively. No sed patching required.
   Status: RESOLVED.

2. **supervisor.sh**: Replaced by production supervisor.gcp.sh that uses
   both compose files natively. No sed patching required.
   Status: RESOLVED.

3. **hada.yaml** infrastructure.compose_file: Changed to compose_files
   list[Path] in the Python model (models.py) with backward-compatible
   validator. The shipped config/hada.yaml now uses a native YAML list.
   No sed patching with shell arguments. Code change tested with 5 new
   tests + 4 existing tests (9 total, all pass).
   Status: RESOLVED.

4. **Caddy ports override**: compose.gcp.yaml now uses `ports: !override`
   to fully replace the base ports list (not append). Requires Docker
   Compose >= 2.24.4; hada-control has v5.3.1.
   Status: RESOLVED.

## Summary

| ID | Severity | Status |
|---|---|---|
| F-001 | Low | Accepted (M1 exclusion) |
| F-002 | Critical | RESOLVED (driver_opts bind mounts in compose.gcp.yaml) |
| F-003 | Medium | RESOLVED (data-root not relocated) |
| F-004 | Critical | RESOLVED (Caddy bound to 127.0.0.1, port 443 unpublished) |
| F-005 | Low | RESOLVED (listener kept on 0.0.0.0, port unpublished) |
| F-006 | Low | Accepted for M1 |
| F-007 | Medium | RESOLVED (per-service UID/GID in deployment plan) |
| B-GATE-1 | — | PENDING (Hermesctl access from hada-control) |
| B-GATE-2 | — | PENDING (Hermesctl access from orchestrator container) |
| Script patches | — | RESOLVED (production scripts + code change in B0) |
| Caddy !override | — | RESOLVED (Compose v5.3.1 supports !override) |
| Compose validation | — | NOT VALIDATED LOCALLY (no local Docker; B0 preflight required) |

## Phase A stopping condition

All Phase A inspection steps (1-21) are complete. All required evidence
files have been produced and revised. No modifications were made to
hada-control or any GCP resources. No sudo was used during Phase A.

Awaiting explicit human approval to proceed to Phase B.
