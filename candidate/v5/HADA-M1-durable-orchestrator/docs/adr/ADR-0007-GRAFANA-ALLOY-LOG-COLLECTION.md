# ADR-0007: Use Grafana Alloy for container log collection

**Status:** Accepted for M1 implementation candidate  
**Date:** 2026-07-25

## Context

HADA needs local collection of Docker JSON logs into Loki without granting the collector access to the Docker API socket. Promtail reached end of life on 2 March 2026 and is no longer an appropriate new deployment dependency.

## Decision

HADA uses Grafana Alloy. Alloy reads `/var/lib/docker/containers/*/*-json.log` through a read-only bind mount, parses the Docker JSON envelope and forwards records to Loki over the internal control network. The Docker socket is not mounted.

The Alloy configuration is validated in CI with the same versioned container image used by Compose.

## Consequences

- HADA avoids deploying an end-of-life collector.
- The collector receives read access to all Docker JSON logs on the host; log redaction remains mandatory before sensitive material reaches stdout or stderr.
- Docker logging-driver changes require a corresponding Alloy configuration review.
- The container-log mount is host-specific and must be validated on the selected Vast.ai image.
