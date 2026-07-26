#!/usr/bin/env bash
#
# HADA M1 Phase B — Proposed Commands (Revised B0)
#
# This script lists every proposed Phase B command. Each command is
# commented out and preceded by its purpose. No Phase B commands are
# executed during Phase A or Phase B0.
#
# Generated: 2026-07-25T03:42:00Z
# Revised: 2026-07-25 (human correction pass)
# Revised: 2026-07-25 (B0 artifact correction pass)
#
# Governance: These commands must only be executed after explicit
# human approval of Phase B. The operator must not begin Phase B
# without that approval.
#
# Key revisions applied:
#   - Both compose files are used everywhere:
#       deploy/compose/compose.yaml
#       deploy/compose/compose.gcp.yaml
#   - Docker data-root is NOT relocated.
#   - Volume directories use per-service UID/GID (not uniform hada:hada).
#   - Secrets are provisioned atomically (no sed-based approach).
#   - Remote archive SHA-256 verification before extraction.
#   - Extraction into a clean staging directory.
#   - Orchestrator listener stays on 0.0.0.0 (port 9108 unpublished).
#   - Caddy bound to 127.0.0.1, port 443 not published, ACME disabled.
#   - Hermesctl remote checks documented as mandatory Phase B gates.
#   - Caddy ports use !override to fully replace base ports (not append).
#   - Production scripts (supervisor.gcp.sh, validate-host.gcp.sh) replace
#     shipped versions; no sed patching during deployment.
#   - compose_file in hada.yaml changed to compose_files list (code change
#     with tests; see code-change-compose-files.md).
#   - Hardcoded container names replaced with docker compose exec -T <service>.
#   - Valkey password never inserted into host command line, output, or evidence.
#   - Governance constraint test runs inside a transaction with ROLLBACK.
#   - Public-listener validation distinguishes acceptable 127.0.0.1:80 from
#     prohibited 0.0.0.0/[::] and prohibited host port 443.
#

set -Eeuo pipefail

PROJECT="api-intergrations-501314"
ZONE="australia-southeast1-b"
VM="hada-control"
ARCHIVE="HADA-M1-gcp-candidate.zip"
EXPECTED_SHA256="9da95a53eac87d6b2f2860f2b3944d39d66f85882848f9a69b88f06909c14371"
SSH_CMD="gcloud compute ssh ${VM} --project=${PROJECT} --zone=${ZONE} --tunnel-through-iap"
SCP_CMD="gcloud compute scp --project=${PROJECT} --zone=${ZONE} --tunnel-through-iap"

# The two compose files — used together in every compose command.
# For host-side commands use absolute paths; for commands run from
# /opt/hada as CWD, use relative paths.
COMPOSE_FILES="-f deploy/compose/compose.yaml -f deploy/compose/compose.gcp.yaml"
COMPOSE_FILES_ABS="-f /opt/hada/deploy/compose/compose.yaml -f /opt/hada/deploy/compose/compose.gcp.yaml"

# ============================================================================
# Step B1: Transfer candidate archive to VM
# Purpose: Copy the GCP candidate archive (with all production overlays)
#          to the VM for deployment. No ad-hoc source-code patching
#          is performed after bootstrap.
# ============================================================================

# ${SCP_CMD} ${ARCHIVE} ${VM}:/tmp/

# ============================================================================
# Step B1.1: Verify remote archive SHA-256 before extraction
# Purpose: Ensure the archive was not corrupted or modified in transit.
#          The checksum must match the locally computed value.
# ============================================================================

# ${SSH_CMD} --command='cd /tmp && sha256sum '${ARCHIVE}' && \
#   echo "Expected: '${EXPECTED_SHA256}'" && \
#   echo "${EXPECTED_SHA256}  ${ARCHIVE}" | sha256sum -c -'

# ============================================================================
# Step B2: Extract into a clean staging directory and run bootstrap
# Purpose: Install system packages, Docker, create service account,
#          install HADA to /opt/hada, generate signing keys.
#          Extraction is into a clean staging directory (human decision #11).
# ============================================================================

# ${SSH_CMD} --command='cd /tmp && \
#   rm -rf /tmp/hada-staging && \
#   mkdir -p /tmp/hada-staging && \
#   cd /tmp/hada-staging && \
#   unzip -o /tmp/'${ARCHIVE}' && \
#   ls -la HADA-M1-durable-orchestrator/scripts/bootstrap-ubuntu.sh && \
#   sudo bash HADA-M1-durable-orchestrator/scripts/bootstrap-ubuntu.sh'

# Note: Docker's global data-root is NOT modified. No /etc/docker/daemon.json
# is created. Docker images and container layers remain on the boot disk.
# Stateful data is redirected via driver_opts bind mounts (Step B3).

# ============================================================================
# Step B3: Create Docker volume directories with per-service UID/GID
# Purpose: Ensure each bind-mounted volume directory has correct ownership
#          for the container that writes to it (human decisions #1 and #7).
#          NOT all directories are owned by hada:hada.
# ============================================================================

# ${SSH_CMD} --command='sudo install -d -o 70   -g 70   -m 0750 /var/lib/hada/docker-volumes/postgres-data && \
#   sudo install -d -o 999  -g 1000 -m 0770 /var/lib/hada/docker-volumes/valkey-data && \
#   sudo install -d -o 65534 -g 65534 -m 0755 /var/lib/hada/docker-volumes/prometheus-data && \
#   sudo install -d -o 10001 -g 10001 -m 0750 /var/lib/hada/docker-volumes/loki-data && \
#   sudo install -d -o 473  -g 473  -m 0770 /var/lib/hada/docker-volumes/alloy-data && \
#   sudo install -d -o 472  -g 0    -m 0750 /var/lib/hada/docker-volumes/grafana-data && \
#   sudo install -d -o 0    -g 0    -m 0755 /var/lib/hada/docker-volumes/caddy-data && \
#   sudo install -d -o 0    -g 0    -m 0755 /var/lib/hada/docker-volumes/caddy-config'

# Container UID/GID (verified via skopeo inspect):
#   postgres   : UID 70,   GID 70
#   valkey     : UID 999,  GID 1000
#   prometheus : UID 65534(nobody), GID 65534
#   loki       : UID 10001, GID 10001  (matches hada)
#   alloy      : UID 473,  GID 473
#   grafana    : UID 472,  GID 0
#   caddy      : UID 0,    GID 0  (runs as root)

# ============================================================================
# Step B4: Copy compose.gcp.yaml, Caddyfile.gcp, and production scripts to VM
# Purpose: Install the production override, Caddyfile, and production versions
#          of supervisor.sh and validate-host.sh alongside the base.
#          Production scripts replace shipped versions; no sed patching.
# ============================================================================

# ${SCP_CMD} /home/bobthabuilda/hada-deployment/deploy/compose/compose.gcp.yaml \
#   ${VM}:/tmp/compose.gcp.yaml
# ${SCP_CMD} /home/bobthabuilda/hada-deployment/deploy/caddy/Caddyfile.gcp \
#   ${VM}:/tmp/Caddyfile.gcp
# ${SCP_CMD} /home/bobthabuilda/hada-deployment/scripts/supervisor.gcp.sh \
#   ${VM}:/tmp/supervisor.gcp.sh
# ${SCP_CMD} /home/bobthabuilda/hada-deployment/scripts/validate-host.gcp.sh \
#   ${VM}:/tmp/validate-host.gcp.sh

# ${SSH_CMD} --command='sudo install -m 0644 -o root -g hada \
#   /tmp/compose.gcp.yaml /opt/hada/deploy/compose/compose.gcp.yaml && \
#   sudo install -m 0644 -o root -g hada \
#   /tmp/Caddyfile.gcp /opt/hada/deploy/caddy/Caddyfile.gcp && \
#   sudo install -m 0755 -o root -g hada \
#   /tmp/supervisor.gcp.sh /opt/hada/scripts/supervisor.sh && \
#   sudo install -m 0755 -o root -g hada \
#   /tmp/validate-host.gcp.sh /opt/hada/scripts/validate-host.sh'

# ============================================================================
# Step B5: Provision secrets atomically
# Purpose: Generate each secret once, reuse in DSN/URL, write .env atomically.
#          Replaces the incomplete sed-based approach (human decision #8).
# ============================================================================

# ${SCP_CMD} /home/bobthabuilda/hada-deployment/scripts/provision-secrets.sh \
#   ${VM}:/tmp/provision-secrets.sh
# ${SSH_CMD} --command='sudo bash /tmp/provision-secrets.sh'

# The script:
#   - generates each secret exactly once (openssl rand -hex 32)
#   - reuses each in its PASSWORD and DSN/URL
#   - writes /opt/hada/.env atomically (temp file + mv)
#   - assigns root:hada ownership, mode 0640
#   - never displays secrets
#   - fails if any CHANGE_ME placeholder remains

# ============================================================================
# Step B6: Configure hada.yaml
# Purpose: Set target repository.
#          The compose_files list is already in the shipped config (code
#          change: compose_file -> compose_files list[Path]).
#          monitoring.listen_host stays 0.0.0.0 (port 9108 unpublished).
#          No sed patching of compose_file — the config uses compose_files
#          list natively.
# ============================================================================

# ${SSH_CMD} --command='sudo sed -i \
#   -e "s|target_repository: \"\"|target_repository: \"https://github.com/mdyerapis-coder/hermesctl.git\"|" \
#   /opt/hada/config/hada.yaml'

# Note: The updated hada.yaml already contains:
#   infrastructure:
#     compose_files:
#       - /opt/hada/deploy/compose/compose.yaml
#       - /opt/hada/deploy/compose/compose.gcp.yaml
# This is a native list, not a shell argument string.

# ============================================================================
# Step B7: Run host validation (with both compose files)
# Purpose: Verify all prerequisites are met before starting services.
#          The production validate-host.gcp.sh (installed as
#          /opt/hada/scripts/validate-host.sh) uses BOTH compose files
#          natively. No sed patching required.
# ============================================================================

# ${SSH_CMD} --command='sudo /opt/hada/scripts/validate-host.sh'

# ============================================================================
# Step B8: Build and start Docker Compose services (with both files)
# Purpose: Pull images, build orchestrator, start all services.
# ============================================================================

# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' --env-file .env up -d'

# ============================================================================
# Step B9: Verify database migrations
# Purpose: Confirm PostgreSQL schema is applied correctly.
# ============================================================================

# ${SSH_CMD} --command='sudo -u hada /opt/hada/.venv/bin/hada db migrate \
#   --config /opt/hada/config/hada.yaml'

# Or verify via the orchestrator container's entrypoint which runs migrations.

# ============================================================================
# Step B10: Enable and start the systemd supervisor (with both compose files)
# Purpose: Start the watchdog that monitors and recovers the control plane.
#          The production supervisor.gcp.sh (installed as
#          /opt/hada/scripts/supervisor.sh) uses BOTH compose files natively.
#          No sed patching required.
# ============================================================================

# ${SSH_CMD} --command='sudo systemctl enable --now hada-supervisor.service'

# ============================================================================
# Step B11: Validation suite
# Purpose: Run all Phase B validation checks.
# All compose commands use BOTH files.
# All container exec commands use docker compose exec -T <service> (not
# hardcoded container names like hada-postgres-1).
# ============================================================================

# --- B11.1: Verify persistent disk mounting ---
# ${SSH_CMD} --command='findmnt /var/lib/hada && blkid /dev/sdb'

# --- B11.2: Verify Docker Compose configuration (both files) ---
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' --env-file .env config'

# --- B11.3: Verify PostgreSQL health and migrations ---
# Uses docker compose exec -T (no hardcoded container name).
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T postgres pg_isready -U hada -d hada && \
#   docker compose '${COMPOSE_FILES}' exec -T postgres psql -U hada -d hada \
#     -c "SELECT version, checksum FROM schema_migrations ORDER BY version"'

# --- B11.4: Verify governance constraints (self-approval rejected) ---
# Runs inside a transaction with ROLLBACK so no test records are left behind.
# The INSERT should fail because the CHECK constraint rejects self-approval
# (reviewer_party = subject_party = 1 with status = 'approved').
# The transaction is rolled back regardless of outcome.
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T postgres psql -U hada -d hada \
#     -c "BEGIN; \
#         INSERT INTO gate_decisions \
#           (decision_id, milestone_id, gate, status, reviewer_party, \
#            subject_party, evidence, findings, decision_digest) \
#         VALUES \
#           ('\''test-b11-4'\'', '\''m1'\'', '\''architecture'\'', '\''approved'\'', \
#            1, 1, '\''[]'\''::jsonb, '\''[]'\''::jsonb, repeat('\''0'\'', 64)); \
#         ROLLBACK;" 2>&1 | grep -q "violates\|rejected\|may not" \
#           && echo "PASS: self-approval rejected" \
#           || echo "FAIL: self-approval not rejected"'
# Note: This requires a milestone row with milestone_id='m1' to exist.
# If no milestone exists yet, the trigger will reject the insert with a
# different error (milestone does not exist), which also indicates the
# constraint mechanism is active. The test should be run after B9 (migrations)
# and after a milestone has been created via the CLI.

# --- B11.5: Verify authenticated Valkey operation ---
# The Valkey password is read from .env inside the container's environment
# variable VALKEY_PASSWORD (set by compose). It is never extracted from
# .env on the host, never inserted into the host command line, never
# displayed in output, and never written into evidence.
# The command uses --no-auth-warning to suppress the warning that would
# otherwise echo the password. The password is referenced as an environment
# variable inside the container, not passed as a visible CLI argument.
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T valkey \
#     bash -c '\''valkey-cli --no-auth-warning -a "$VALKEY_PASSWORD" ping'\'' \
#     2>/dev/null | grep -q PONG \
#       && echo "PASS: Valkey authenticated" \
#       || echo "FAIL: Valkey not responding"'

# --- B11.6: Verify orchestrator liveness and readiness ---
# Port 9108 is NOT published. Access via docker compose exec -T (no
# hardcoded container name).
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T orchestrator \
#     curl -s http://127.0.0.1:9108/healthz'
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T orchestrator \
#     curl -s http://127.0.0.1:9108/readyz'

# --- B11.7: Verify immutable audit records ---
# Uses docker compose exec -T postgres (no hardcoded container name).
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T postgres psql -U hada -d hada \
#     -c "UPDATE audit_events SET event_type='\''tampered'\'' WHERE sequence=1;" \
#     2>&1 | grep -q "may not be updated" \
#       && echo "PASS: audit records immutable" \
#       || echo "FAIL"'

# --- B11.8: Verify audit signing and hash-chain ---
# ${SSH_CMD} --command='sudo -u hada /opt/hada/.venv/bin/hada audit verify \
#   --config /opt/hada/config/hada.yaml'

# --- B11.9: Verify bounded workspace creation ---
# ${SSH_CMD} --command='sudo -u hada /opt/hada/.venv/bin/hada workspace create M1 task-001 \
#   --config /opt/hada/config/hada.yaml'

# --- B11.10: Verify Hermesctl repo accessibility from orchestrator container ---
# MANDATORY Phase B gate (human decision #9)
# Uses docker compose exec -T orchestrator (no hardcoded container name).
# ${SSH_CMD} --command='cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T orchestrator \
#     git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main'

# --- B11.11: Verify Hermesctl repo accessibility from hada-control as hada ---
# MANDATORY Phase B gate (human decision #9)
# The hada service account shell is /usr/sbin/nologin; use sudo -u hada.
# If credentials are required for HTTPS to GitHub, report the exact
# requirement without exposing credentials.
# ${SSH_CMD} --command='sudo -u hada git ls-remote https://github.com/mdyerapis-coder/hermesctl.git refs/heads/main'

# --- B11.12: Verify watchdog recovery behaviour ---
# ${SSH_CMD} --command='sudo systemctl status hada-supervisor.service'

# --- B11.13: Verify no unexpected public listeners ---
# Distinguishes:
#   - ACCEPTABLE: 127.0.0.1:80 (Caddy bound to localhost)
#   - PROHIBITED: 0.0.0.0:80 or [::]:80 (Caddy on all interfaces)
#   - PROHIBITED: any listener on port 443
#   - PROHIBITED: any published service port (5432, 6379, 9090, 3100, 9108, 12345)
#
# The check first verifies that 127.0.0.1:80 is present (Caddy is running
# and bound to localhost). Then it checks that no 0.0.0.0 or [::] listener
# exists for port 80, no listener exists for port 443, and no published
# service ports are exposed.
# ${SSH_CMD} --command=' \
#   ss -tlnp | grep -q "127.0.0.1:80 " && echo "PASS: Caddy on 127.0.0.1:80" || echo "FAIL: Caddy not on 127.0.0.1:80" ; \
#   ss -tlnp | grep -E "0\.0\.0\.0:80 |\[::\]:80 " && echo "FAIL: port 80 on all interfaces" || echo "PASS: port 80 not on all interfaces" ; \
#   ss -tlnp | grep -E ":443 " && echo "FAIL: port 443 is published" || echo "PASS: port 443 not published" ; \
#   ss -tlnp | grep -E ":5432 |:6379 |:9090 |:3100 |:9108 |:12345 " && echo "FAIL: service port published" || echo "PASS: no service ports published"'
# Also verify from outside:
# curl -s --connect-timeout 5 http://34.151.78.183:80/ 2>&1 || echo "PASS: port 80 not accessible externally"

# --- B11.14: Verify service recovery following reboot ---
# ${SSH_CMD} --command='sudo reboot'
# Wait for VM to come back, then verify:
# ${SSH_CMD} --command='systemctl is-active hada-supervisor.service && docker ps'

# --- B11.15: Verify persistence of state after reboot ---
# Uses docker compose exec -T postgres (no hardcoded container name).
# ${SSH_CMD} --command='findmnt /var/lib/hada && \
#   cd /opt/hada && \
#   docker compose '${COMPOSE_FILES}' exec -T postgres psql -U hada -d hada \
#     -c "SELECT count(*) FROM schema_migrations"'

# ============================================================================
# End of proposed Phase B commands
# ============================================================================
#
# These commands must NOT be executed until Phase B is explicitly approved.
# The operator (Hermes) must not begin Phase B without human approval.
# The only valid successful deployment status is:
#   IMPLEMENTATION_CANDIDATE_AWAITING_PARTY_3
#
# Failure statuses are:
#   FAILED_VALIDATION
#   BLOCKED_REQUIRES_HUMAN_INPUT
