# HADA M1 — Compose Configuration Validation Status

Generated: 2026-07-25
Status: NOT VALIDATED LOCALLY

## Summary

The Docker Compose configuration (compose.yaml + compose.gcp.yaml) has NOT
been validated locally because Docker is not installed on the local Fedora
workstation.

```
$ which docker
which: no docker in (...)
docker not found locally
```

The configuration can only be validated on hada-control, where Docker
Compose v5.3.1 is installed. This validation is part of the Phase B0
preflight plan (see preflight-plan.md, Step B0.4).

## What was done locally

1. The compose.gcp.yaml file was inspected manually and by reading its YAML
   structure. The `!override` tag is used for the Caddy ports to fully
   replace the base ports list (not append).

2. The compose_files code change (models.py, health.py) was tested with
   Python unit tests (9 passed). These tests verify the config model and
   the docker compose command construction, but they do NOT run
   `docker compose config` because Docker is not available.

3. The bash syntax of all shell scripts was validated with `bash -n`.

4. SHA-256 checksums were computed and verified for all production
   artifacts and evidence files.

## What requires Phase B0 on hada-control

The following can ONLY be proven on hada-control with Docker Compose:

- `docker compose config` renders without errors
- The effective configuration shows only 127.0.0.1:80:80 published
- Port 443 is absent from the effective configuration
- All eight stateful volumes point beneath /var/lib/hada/docker-volumes/
- The `!override` tag correctly replaces (not appends) the base ports

These are the Step B0.4 through B0.7 assertions in the preflight plan.
