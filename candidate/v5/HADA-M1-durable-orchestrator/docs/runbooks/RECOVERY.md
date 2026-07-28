# Recovery Runbook

The supervisor performs bounded container recovery. After the configured number of unsuccessful attempts it exits with code 70 and emits a critical journal event. Operators must inspect `journalctl -u hada-supervisor`, `docker compose ps`, service logs, disk pressure, GPU state and database integrity.

Never resolve a recovery incident by deleting governance state, reducing review requirements, marking gates approved, disabling evidence validation or increasing retry limits without an ADR and independent review.
