# HADA M1 GCP Candidate v5 — Fix Release

Built from `releases/v4/HADA-M1-gcp-candidate-v4.zip` (sha256 `d5582879…`) with
8 deployment-blocking fixes applied. Deployed and verified on `hada-control`
(all 9 containers healthy: orchestrator, postgres, valkey, caddy, grafana,
prometheus, loki, alloy, node-exporter).

## Fixes

1. **Dockerfile** — add `passwd` package so `groupadd`/`useradd` are available
   in the slim image (was missing → image build failed).
2. **scripts/supervisor.sh** — ensure executable bit (`0755`); was `0600` so
   systemd returned `status=203/EXEC`.
3. **deploy/compose/compose.yaml** — valkey secret mount target: the secret is
   named `valkey_conf` but valkey-server reads `/run/secrets/valkey.conf`; set
   `target: valkey.conf` so the mount lands at the expected path.
4. **deploy/compose/compose.yaml** — valkey healthcheck now passes the extracted
   `requirepass` to `valkey-cli -a` (was capturing it into an unused env var →
   healthcheck always returned NOAUTH → container never healthy).
5. **deploy/** config files — set world-readable (`0644`) so non-root containers
   (prometheus/loki/alloy) can read the `:ro` bind-mounted configs.
6. **deploy/loki/config.yml** — add `compactor.delete_request_store: filesystem`
   (retention enabled without a valid store → Loki failed config validation).
7. **deploy/compose/compose.yaml** — alloy: add `cap_add: CHOWN/DAC_OVERRIDE/
   FOWNER` + `read_only: false` + `:rw` volume. `cap_drop: ALL` from the
   `*security` anchor stripped write capability, so alloy (root) could not
   `mkdir /var/lib/alloy/data` even with a RW volume.
8. **deploy/** — runtime secret files (`/var/lib/hada/docker-volumes/*`,
   `valkey.conf`) created at install time (these steps are normally done by the
   skipped `provision-secrets.sh`, which would otherwise regenerate all
   passwords and overwrite the staged `.env`).

## Deploy verification

- `validate-host.sh`: 11/11 PASS
- `systemctl is-active hada-supervisor.service`: active
- Orchestrator `/healthz` → ok, `/readyz` → ready, DB schema current
- Grafana reachable via Caddy (`:80`) over IAP tunnel and Tailscale
  (`100.77.108.35`)

## Not changed

- Inference backend: OpenCode Zen free models (`deepseek-v4-flash-free` impl,
  `nemotron-3-ultra-free` adversarial) per deployment config — not part of the
  candidate source.
- `require_tls: false` and Tailscale+IAP access design are deployment choices,
  not candidate changes.
