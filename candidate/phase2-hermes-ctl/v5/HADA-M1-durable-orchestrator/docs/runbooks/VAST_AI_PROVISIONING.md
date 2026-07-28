# Vast.ai Provisioning Runbook

## Instance requirements

- Ubuntu 24.04 LTS image with SSH access
- NVIDIA GPU and driver compatible with the selected inference backend
- at least 100 GB persistent disk for images, models, workspaces and evidence
- public TCP 22; expose 80/443 only when the instance has a stable hostname and TLS is required
- no provider image that preloads unknown orchestration software

## Procedure

1. Create a dedicated SSH key for the appliance.
2. Provision the Vast.ai instance and verify its host key out of band.
3. Clone this repository to a temporary bootstrap directory.
4. Copy `.env.example` to `.env`; generate independent high-entropy passwords.
5. Set the target Hermesctl repository and approved model identifiers.
6. Run `sudo ./scripts/bootstrap-ubuntu.sh`.
7. Move the configured `.env` to `/opt/hada/.env`, owned by root and group-readable by `hada` with mode `0640`.
8. Run `/opt/hada/scripts/validate-host.sh`.
9. Run `/opt/hada/.venv/bin/hada validate-config --config /opt/hada/config/hada.yaml`.
10. Enable `hada-supervisor.service` only after validation succeeds.
11. Confirm `/healthz`, Grafana, Prometheus targets, Loki ingestion and container health.

## Mandatory stop

Do not begin M1 when model identifiers, target repository, TLS hostname, secrets, GPU capacity or Party 3 review exchange are unresolved.
