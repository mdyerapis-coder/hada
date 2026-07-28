# Hermes Autonomous Development Appliance (HADA)

HADA is a governed, self-provisioning autonomous software-engineering appliance. It is deliberately separate from Hermesctl: HADA provisions and operates the development environment; Hermesctl remains the independently configured target repository.

## Current milestone

This repository contains the **M1 — Durable Orchestrator implementation candidate**. It extends the M0 governed foundation with:

- ordered PostgreSQL migrations and database-enforced governance constraints;
- append-only gate, policy, evidence and audit records;
- an Ed25519-signed, SHA-256 hash-chained audit ledger;
- a content-addressed evidence store with signed manifests;
- optimistic task-state transitions and enforced reviewer separation;
- Valkey Streams queues, consumer groups, stale-message reclaim and durable dead-letter handling;
- token-bound renewable leases;
- a PostgreSQL transactional outbox for reliable queue publication;
- pinned Git workspaces built from a validated repository origin and resolved commit;
- a fail-closed tool policy and Bubblewrap execution sandbox;
- an orchestrator runtime with readiness, liveness and Prometheus metrics;
- Docker Compose deployment, Grafana dashboard, Prometheus alerts and Grafana Alloy log shipping;
- unit and integration-test coverage for the control plane.

M1 is not marked approved. Party 3 must review the signed evidence bundle outside HADA before the milestone can close. No Hermesctl changes or inference services are included in M1.

## Security model

HADA is autonomous only within explicit milestone scope. Agent output, repository content and commands are untrusted. Party 1 cannot approve implementation work, Party 2 cannot mutate implementation workspaces, Party 3 cannot mutate internal task state, and the supervisor cannot change governance records.

The execution broker does not invoke a shell. It resolves an allowlisted executable beneath trusted roots, confines the exact task workspace, clears agent-supplied environment variables, rejects Git helper/configuration overrides, and requires a networkless Bubblewrap namespace where configured. If the sandbox is unavailable, execution is denied.

## Fresh Ubuntu 24.04 bootstrap

```bash
sudo ./scripts/bootstrap-ubuntu.sh
sudo install -o root -g hada -m 0640 .env.example /opt/hada/.env
sudoedit /opt/hada/.env
sudoedit /opt/hada/config/hada.yaml
sudo /opt/hada/scripts/validate-host.sh
sudo systemctl enable --now hada-supervisor.service
```

The bootstrap creates a fixed UID/GID 10001 service account so the non-root orchestrator container and host state directory have deterministic ownership. It also creates the appliance Ed25519 signing key if one does not already exist.

## Local validation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff format --check .
ruff check .
mypy src
pytest -q --cov=hada --cov-report=term-missing --cov-fail-under=70
hada validate-config --config config/hada.yaml
```

PostgreSQL and Valkey integration tests run when these variables are configured:

```bash
export HADA_INTEGRATION_DSN='postgresql://hada:password@127.0.0.1:5432/hada'
export HADA_INTEGRATION_VALKEY_URL='redis://127.0.0.1:6379/0'
pytest -q -m integration
```

## Operator commands

```bash
hada keys generate \
  --private-key /var/lib/hada/keys/audit-signing-key.pem \
  --public-key /var/lib/hada/keys/audit-signing-key.pub.pem

hada db migrate --config /opt/hada/config/hada.yaml
hada audit verify --config /opt/hada/config/hada.yaml
hada evidence add report.json --media-type application/json \
  --config /opt/hada/config/hada.yaml
hada evidence verify <sha256-digest> --config /opt/hada/config/hada.yaml
hada workspace create M1 task-001 --config /opt/hada/config/hada.yaml
hada orchestrator run --config /opt/hada/config/hada.yaml
```

## Repository boundary

HADA owns provisioning, durable state, orchestration, governance, evidence, observability and bounded recovery. Hermesctl is cloned only from a configured, approved repository URL into a task-specific worktree pinned to a resolved commit. HADA must never treat its own repository as the product repository.

See:

- `docs/architecture/ARCHITECTURE.md`
- `docs/rfc/RFC-0002-DURABLE-ORCHESTRATOR.md`
- `docs/security/THREAT-MODEL.md`
- `docs/reports/M1-MILESTONE-REPORT.md`
- `docs/reports/M1-EXTERNAL-REVIEW-CHECKLIST.md`
