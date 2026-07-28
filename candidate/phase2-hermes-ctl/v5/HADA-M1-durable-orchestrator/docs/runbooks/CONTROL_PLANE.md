# Control-Plane Operations Runbook

## Start

```bash
sudo systemctl start hada-supervisor.service
sudo journalctl -u hada-supervisor.service -f
```

## Validate readiness

```bash
cd /opt/hada
docker compose -f deploy/compose/compose.yaml --env-file .env ps
curl --fail http://127.0.0.1:9108/readyz   # only when run directly on host
```

Inside the Compose network, the orchestrator readiness endpoint is `http://orchestrator:9108/readyz`.

## Verify durable records

```bash
set -a
source /opt/hada/.env
set +a
/opt/hada/.venv/bin/hada audit verify --config /opt/hada/config/hada.yaml
```

Any verification failure is a governance stop condition. Do not truncate the audit table, rewrite sequence values or generate a replacement key to make verification pass.

## Inspect queue health

```bash
cd /opt/hada
docker compose -f deploy/compose/compose.yaml --env-file .env exec valkey \
  valkey-cli -a "$VALKEY_PASSWORD" XINFO GROUPS hada:queue:party-1
```

Do not delete pending or dead-letter entries until they are exported as evidence and reviewed.

## Inspect outbox

```bash
cd /opt/hada
docker compose -f deploy/compose/compose.yaml --env-file .env exec postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT state, count(*) FROM outbox_events GROUP BY state ORDER BY state;"
```

A growing `pending` count indicates Valkey or publisher failure. A growing `failed` count requires human review.

## Inspect centralised logs

Grafana queries Loki through the provisioned Loki data source. Alloy reads Docker JSON logs from `/var/lib/docker/containers` through a read-only mount. Verify the collector without granting Docker socket access:

```bash
cd /opt/hada
docker compose -f deploy/compose/compose.yaml --env-file .env logs alloy
docker compose -f deploy/compose/compose.yaml --env-file .env exec alloy \
  alloy validate /etc/alloy/config.alloy
```

Do not add `/var/run/docker.sock` to Alloy. Log metadata enrichment that requires the Docker API must undergo a new security review.

## Stop

```bash
sudo systemctl stop hada-supervisor.service
cd /opt/hada
docker compose -f deploy/compose/compose.yaml --env-file .env down
```

Do not use `down -v` in normal operations; that deletes durable service volumes.
