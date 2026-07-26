# HADA M1 Phase B0 — Bounded Preflight Plan (Revised)

Generated: 2026-07-25
Revised: 2026-07-25 (final artifact correction pass)
Status: AWAITING PREFLIGHT EXECUTION APPROVAL

## Purpose

Phase B0 is a bounded preflight that verifies the effective Docker Compose
configuration on hada-control WITHOUT starting containers, pulling images,
installing packages, running bootstrap, restarting services, rebooting the VM,
altering disks, or altering firewall rules.

Phase B0 proves that the Compose configuration is correct before any real
deployment begins. It is read-only with respect to the running system — the
only writes are to a temporary preflight directory on the VM.

## Implementation

Phase B0 is implemented as a single executable script:

    scripts/run-phase-b0-preflight.sh

The script is self-contained and may be run locally from the deployment
workstation. It uses IAP SSH/SCP to interact with hada-control.

## Boundary

Phase B0 does NOT:
- Start containers (no `docker compose up`, `start`, `restart`)
- Pull images (no `docker pull`, `docker compose pull`)
- Build images (no `docker build`, `docker compose build`)
- Create containers (no `docker create`)
- Install packages
- Run bootstrap
- Restart services
- Reboot the VM
- Alter disks
- Alter firewall rules
- Begin deployment

Phase B0 only:
- Creates a uniquely named remote temporary directory
- Uploads only the required preflight files into that directory
- Uses a synthetic non-production .env (no real secrets)
- Runs `docker compose config --format json` only
- Parses the JSON output with Python's standard-library json module
- Validates published ports from structured JSON fields
- Validates volumes from structured JSON fields
- Captures Compose version and before/after container/image state
- Retrieves evidence into evidence/phase-b0/preflight-run-<timestamp>/
- Safely removes only its remote temporary directory

## Prerequisites

1. Docker Compose version >= 2.24.4 on hada-control.
   Verified: Docker Compose version v5.3.1 on hada-control (2026-07-25).

2. The `!override` tag is supported (Compose >= 2.24.x).
   Applied: compose.gcp.yaml uses `ports: !override` for Caddy.

3. Production artifacts are ready locally:
   - HADA-M1-gcp-candidate.zip (candidate archive with all overlays)
   - deploy/compose/compose.gcp.yaml (with !override)
   - deploy/caddy/Caddyfile.gcp
   - scripts/run-phase-b0-preflight.sh (this script)

4. Code changes are tested locally (inside the candidate tree):
   - compose_file -> compose_files list[Path] in models.py
   - compose_health() accepts list[str] in health.py
   - 5 new tests + 4 existing tests pass (9 total)

## Parser choice: docker compose config --format json + stdlib json

Phase B0 uses `docker compose config --format json` (not YAML output piped
through PyYAML). This avoids depending on PyYAML being installed on
hada-control. The JSON output is parsed by Python's standard-library `json`
module, which is always available with Python 3.

## Port validation from structured JSON fields

The port assertion does NOT search for the short-form text "127.0.0.1:80:80".
Instead, it validates the structured JSON fields returned by
`docker compose config --format json`.

The exact required result is:
- exactly one published port across all services;
- service: caddy;
- host_ip: 127.0.0.1;
- published: 80;
- target: 80;
- protocol: tcp;
- no published or target port 443.

## Volume validation from structured JSON

The eight top-level volumes are validated from structured JSON:
- postgres-data, valkey-data, prometheus-data, loki-data, alloy-data,
  grafana-data, caddy-data, caddy-config

Each must have:
- driver_opts.type = none
- driver_opts.o = bind
- its exact device beneath /var/lib/hada/docker-volumes/

## Before-and-after evidence

Phase B0 captures before and after state using read-only commands:
- `docker ps -aq | sort` (container IDs)
- `docker images -q | sort -u` (image IDs)

The before and after files must be identical, proving that preflight started
no containers and pulled or created no images.

## Fail-closed temporary cleanup

The remote temporary directory is removed only when its path matches the
pattern `/tmp/hada-b0-preflight-[0-9]+`. An empty path, `/tmp` itself, or
any other path is refused and the script exits with an error.

## Evidence captured

The script retrieves the following into evidence/phase-b0/preflight-run-<timestamp>/:
1. compose-version.txt — Docker Compose version
2. docker-ps-before.txt — container IDs before preflight
3. docker-images-before.txt — image IDs before preflight
4. effective-compose.json — rendered effective Compose config (JSON)
5. port-assertion.txt — structured port validation output
6. volume-assertion.txt — structured volume validation output
7. docker-ps-after.txt — container IDs after preflight
8. docker-images-after.txt — image IDs after preflight
9. before-after-diff.txt — diff comparison results

## What B0 does NOT prove

B0 does NOT prove:
- That containers will start successfully
- That migrations will apply
- That the orchestrator will be healthy
- That Valkey authentication works at runtime
- That the audit chain is valid
- That workspace creation works
- That Hermesctl is accessible from the VM or container

Those are Phase B validation gates (B11.1 through B11.15) that require
actual deployment. B0 only proves the Compose configuration is correct.

## Compose config local validation status

Docker Compose is NOT available on the local Fedora workstation. The
Compose configuration has NOT been validated locally. It can only be
validated on hada-control during Phase B0 preflight.

The `!override` tag in compose.gcp.yaml requires Docker Compose >= 2.24.4.
The version on hada-control is v5.3.1, which supports `!override`.
