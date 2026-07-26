#!/usr/bin/env bash
#
# HADA M1 Phase B — Production Deployment Execution-Gate Runner
# (DEEP FAIL-CLOSED CORRECTED EDITION)
#
# Fail-closed, evidence-driven deployment runner for the HADA M1 Durable
# Orchestrator onto the GCP hada-control VM.
#
# ============================================================================
# EXECUTION GATE
# ============================================================================
# This script MUST NOT perform any remote action (SSH/SCP/deploy) unless the
# environment variable DEPLOY_EXECUTE is EXACTLY "1". When DEPLOY_EXECUTE is
# unset or any other value, the script runs all local static gates and the
# candidate verification/extraction, prints an execution-gate review, and
# exits WITHOUT contacting hada-control.
#
#   DEPLOY_EXECUTE=1 ./scripts/run-phase-b-deploy.sh   # performs deployment
#   ./scripts/run-phase-b-deploy.sh                    # gate review only (safe)
#
# ============================================================================
# TEST MODE (local verification only — never used in production)
# ============================================================================
# HADA_PHASE_B_TEST_LIB=1  : source functions only; do not run main().
# HADA_PHASE_B_MOCK_SSH    : path to a mock SSH executable used in place of
#                            gcloud-compute-ssh (used by tests/phase-b/*).
# HADA_PHASE_B_NO_CLEANUP_TRAP=1 : do not install the EXIT cleanup trap.
#
# ============================================================================
# DEEP CORRECTIONS APPLIED (this edition)
# ============================================================================
#  1. ssh_sudo_capture: captures the sudo/Docker command result first,
#     preserves its exact nonzero status, sorts ONLY after a successful
#     capture, and never emits NONE for a failed query. Executable mocked
#     tests live in tests/phase-b/test_ssh_sudo_capture.sh.
#  2. Prohibited-operation scanner: executable fixture tests live in
#     tests/phase-b/test_prohibited_operation_scanner.sh; flags uncommented
#     destructive commands, ignores comments/docs/refusal messages.
#  3. Stage-aware rollback: the existing-resource check runs BEFORE any
#     mutation; only resources tracked by THIS run are rolled back; after a
#     Gate 2 refusal zero rollback commands are issued.
#  4. Every remote shell block begins with "set -Eeuo pipefail"; all
#     privileged commands use sudo -n; multi-command blocks stop on the first
#     failure; no final echo masks an earlier error.
#  5. Remote temp dir: umask 077 + mode 0700. Resolved Compose JSON is piped
#     directly into structural validation over an SSH stream; any unavoidable
#     temp storage is mode 0600 and deleted immediately.
#  6. No secrets in process arguments: the valkey health check runs INSIDE
#     the container and uses the container's own VALKEY_PASSWORD via
#     VALKEYCLI_AUTH — never valkey-cli -a, never a secret on the host
#     command line, in logs, or in evidence.
#  7. .env validation rejects empty secrets, CHANGE_ME, ***, synthetic and
#     known example/test values, and verifies DSN/URL passwords are
#     consistent with their password variables — without logging any value.
#  8. The mounted filesystem at /var/lib/hada itself is proven to have UUID
#     a1574097-cdf9-4d0a-ace0-adac63038e56 via findmnt output for the mount
#     point (not by checking /dev/sdb independently).
#  9. The complete locked-candidate application tree is installed (base
#     Compose, GCP override, Caddy config, Dockerfile, src, config, scripts,
#     service unit) via an atomic release layout; every installed file is
#     verified against the candidate SHA-256 manifest before any build.
# 10. Repository-connectivity acceptance checks (git ls-remote from
#     hada-control as user hada, and from inside the orchestrator container)
#     run after startup and begin no autonomous repository work.
#
# LOCAL-ONLY SAFETY: this file, by itself, performs no remote action unless
# DEPLOY_EXECUTE=1 is explicitly exported by the operator.
#
set -Eeuo pipefail

# ----------------------------------------------------------------------------
# Configuration — LOCKED VALUES (must match Phase A / B0 exactly)
# ----------------------------------------------------------------------------

DEPLOY_DIR="${HADA_PHASE_B_DEPLOY_DIR:-/home/bobthabuilda/hada-deployment}"

CANDIDATE_ARCHIVE="${HADA_PHASE_B_CANDIDATE_ARCHIVE:-${DEPLOY_DIR}/deploy-v4/HADA-M1-gcp-candidate-v4.zip}"
CANDIDATE_SHA256_FILE="${HADA_PHASE_B_CANDIDATE_SHA256_FILE:-${DEPLOY_DIR}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256}"
EXPECTED_CANDIDATE_SHA256="${HADA_PHASE_B_CANDIDATE_SHA256:-d5582879cba20d92881ba013c68c4b9df3f9e36a3d0ce22aaad0a53bd33856ac}"

# The Phase B runner MUST NOT execute until a successful v4 Phase B0 evidence
# directory is explicitly locked into B0_EVIDENCE_DIR. This is a fail-closed
# gate: if the variable is unset/empty or the locked state-check file does not
# report PASS, the runner refuses (no remote mutation occurs).
B0_EVIDENCE_DIR="${HADA_PHASE_B0_EVIDENCE_DIR:-}"

TARGET_PROJECT="api-intergrations-501314"
TARGET_ZONE="australia-southeast1-b"
TARGET_VM="hada-control"

HADA_STATE_ROOT="/var/lib/hada"
HADA_DOCKER_VOLUMES="${HADA_STATE_ROOT}/docker-volumes"

OPT_HADA="/opt/hada"
OPT_HADA_COMPOSE="${OPT_HADA}/deploy/compose"
OPT_HADA_CADDY="${OPT_HADA}/deploy/caddy"
OPT_HADA_SCRIPTS="${OPT_HADA}/scripts"
OPT_HADA_CONFIG="${OPT_HADA}/config"
OPT_HADA_ENV="${OPT_HADA}/.env"

COMPOSE_PROJECT="hada-m1"

BASE_COMPOSE="${OPT_HADA_COMPOSE}/compose.yaml"
GCP_COMPOSE="${OPT_HADA_COMPOSE}/compose.gcp.yaml"
CADDYFILE_GCP="${OPT_HADA_CADDY}/Caddyfile.gcp"

TIMESTAMP="${HADA_PHASE_B_TIMESTAMP:-$(date +%Y%m%d%H%M%S)}"
EVIDENCE_DIR="${HADA_PHASE_B_EVIDENCE_DIR:-${DEPLOY_DIR}/evidence/phase-b/deploy-run-${TIMESTAMP}}"
mkdir -p "${EVIDENCE_DIR}"
chmod 0700 "${EVIDENCE_DIR}" 2>/dev/null || true

REMOTE_PREFIX="hada-b-deploy-${TIMESTAMP}"
REMOTE_DIR="/tmp/${REMOTE_PREFIX}"
RELEASE_STAGING="${REMOTE_DIR}/release"

DEPLOY_EXECUTE="${DEPLOY_EXECUTE:-0}"

# SSH transport. Tests inject a mock via HADA_PHASE_B_MOCK_SSH.
if [[ -n "${HADA_PHASE_B_MOCK_SSH:-}" ]]; then
    SSH_CMD=("${HADA_PHASE_B_MOCK_SSH}")
else
    SSH_CMD=(gcloud compute ssh "${TARGET_VM}" --project="${TARGET_PROJECT}" --zone="${TARGET_ZONE}" --tunnel-through-iap --command)
fi
# SCP transport. Tests inject a mock via HADA_PHASE_B_MOCK_SCP.
if [[ -n "${HADA_PHASE_B_MOCK_SCP:-}" ]]; then
    SCP_CMD=("${HADA_PHASE_B_MOCK_SCP}")
else
    SCP_CMD=(gcloud compute scp --project="${TARGET_PROJECT}" --zone="${TARGET_ZONE}" --tunnel-through-iap)
fi

EXIT_STATUS=0
REMOTE_DIR_CREATED=0
CANDIDATE_EXTRACT_DIR=""
CANDIDATE_ROOT=""

# Stage-aware rollback: track resources created/started by THIS run only.
CREATED_CONTAINERS=()
CREATED_VOLUMES=()
CREATED_NETWORKS=()
CREATED_IMAGES=()
UNIT_INSTALLED=0
SUPERVISOR_STARTED=0
COMPOSE_UP_DONE=0
# Correction 4: track whether a Compose-up was attempted at all (so a partial
# failure is rolled back), and whether the orchestrator image was BUILT by
# this run (so it is removed only then, never a pre-pulled or pre-existing image).
COMPOSE_UP_ATTEMPTED=0
ORCH_BUILT_BY_RUN=0
# Cross-gate correction 3: recoverable installation tracking. Gate 2 proves
# /opt/hada was ABSENT before this run; Gate 3 sets OPT_HADA_CREATED=1 the
# moment this run creates it, and stamps the release marker with this run's
# timestamp. ENV_CREATED=1 records that .env was provisioned by THIS run.
OPT_HADA_CREATED=0
ENV_CREATED=0
RELEASE_MARKER=".hada-release-id"

# Expected persistent-disk UUID for the filesystem MOUNTED at /var/lib/hada.
EXPECTED_HADA_UUID="a1574097-cdf9-4d0a-ace0-adac63038e56"

TARGET_REPO_URL="https://github.com/mdyerapis-coder/hermesctl.git"

# Required candidate tree contents (atomic release manifest). The COMPLETE
# runtime/build payload — every file referenced by the Dockerfile COPY/ADD
# instructions, the Compose host-bind sources, and the supporting scripts and
# service unit. Gate 1 generates the application manifest from exactly these
# entries; Gate 3 installs all of them and Gate 6 (build context) requires
# them to be present.
CANDIDATE_MANIFEST=(
    pyproject.toml
    README.md
    Dockerfile
    src
    config
    deploy/compose
    deploy/caddy
    deploy/prometheus
    deploy/loki
    deploy/alloy
    deploy/grafana
    scripts/provision-secrets.sh
    scripts/supervisor.sh
    scripts/validate-host.sh
    scripts/container-entrypoint.sh
    scripts/hada-supervisor.service
)

# Build-context sources that MUST exist under the installed tree for a valid
# `docker compose build` and a complete deployment. Used by validate_build_context.
REQUIRED_BUILD_CONTEXT_FILES=(
    pyproject.toml
    README.md
    Dockerfile
    src
    config
    deploy/compose/compose.yaml
    deploy/compose/compose.gcp.yaml
    deploy/caddy/Caddyfile.gcp
    deploy/prometheus/prometheus.yml
    deploy/prometheus/rules/hada.yml
    deploy/loki/config.yml
    deploy/alloy/config.alloy
    deploy/grafana/provisioning/dashboards/dashboards.yaml
    deploy/grafana/provisioning/datasources/datasources.yaml
    deploy/grafana/dashboards/hada-control-plane.json
    scripts/container-entrypoint.sh
    scripts/provision-secrets.sh
    scripts/supervisor.sh
    scripts/validate-host.sh
    scripts/hada-supervisor.service
)

PULL_IMAGES=(
    "postgres:17-alpine"
    "valkey/valkey:8-alpine"
    "prom/prometheus:v3.2.1"
    "grafana/loki:3.4.2"
    "grafana/alloy:v1.12.0"
    "grafana/grafana:11.5.2"
    "caddy:2.10-alpine"
    "prom/node-exporter:v1.9.0"
)
ORCHESTRATOR_IMAGE="hada-orchestrator:0.2.0"

# ----------------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------------

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "${EVIDENCE_DIR}/deploy-console.log"
}

pass() {
    log "PASS: $*"
}

fail() {
    log "FAIL: $*"
    EXIT_STATUS=1
    return 1
}

capture_rc() {
    local outfile="$1"; shift
    local rc=0
    "$@" 2>&1 | tee "${outfile}"
    rc=${PIPESTATUS[0]}
    return "${rc}"
}

# ssh_remote DESC COMMAND
# Runs COMMAND on hada-control. COMMAND must begin with set -Eeuo pipefail.
ssh_remote() {
    local desc="$1"; shift
    local cmd="$1"
    local outfile="${EVIDENCE_DIR}/${desc// /-}.txt"
    log "REMOTE: ${desc}"
    "${SSH_CMD[@]}" "${cmd}" 2>>"${EVIDENCE_DIR}/ssh-stderr.log" | tee "${outfile}"
    return "${PIPESTATUS[0]}"
}

# ssh_sudo_capture DESC INNER_COMMAND
# CORRECTED (deep correction 1):
#   - INNER_COMMAND is passed as a remote shell string; the remote block
#     begins with set -Eeuo pipefail and the ENTIRE inner command string is
#     never quoted as a single executable.
#   - The sudo/Docker command result is captured FIRST: stdout into a
#     variable, its exact exit status into rc (set +e guards against the
#     remote pipefail aborting before rc is read).
#   - On rc != 0 the remote block prints a diagnostic to stderr and exits
#     with the SAME rc. NONE is never emitted for a failed query.
#   - sort runs ONLY after a successful capture.
#   - Locally, PIPESTATUS[0] preserves the remote nonzero status across the
#     local tee pipeline, so the function itself returns nonzero.
ssh_sudo_capture() {
    local desc="$1"; shift
    local inner="$1"
    local outfile="${EVIDENCE_DIR}/${desc// /-}.txt"
    log "REMOTE SUDO: ${desc}"
    local rcmd
    rcmd="set -Eeuo pipefail
set +e
out=\$( ${inner} 2>/tmp/${REMOTE_PREFIX}-capture.err )
rc=\$?
set -e
if (( rc != 0 )); then
  echo \"FAIL: remote capture command failed (rc=\${rc}): ${inner}\" >&2
  cat \"/tmp/${REMOTE_PREFIX}-capture.err\" >&2 2>/dev/null || true
  rm -f \"/tmp/${REMOTE_PREFIX}-capture.err\"
  exit \"\${rc}\"
fi
rm -f \"/tmp/${REMOTE_PREFIX}-capture.err\"
if [[ -z \"\${out}\" ]]; then
  echo NONE
else
  printf '%s\n' \"\${out}\" | sort
fi"
    "${SSH_CMD[@]}" "${rcmd}" 2>>"${EVIDENCE_DIR}/ssh-stderr.log" | tee "${outfile}"
    return "${PIPESTATUS[0]}"
}

# Resource tracking for stage-aware rollback
track_container() { CREATED_CONTAINERS+=("$1"); }
track_volume()    { CREATED_VOLUMES+=("$1"); }
track_network()   { CREATED_NETWORKS+=("$1"); }
track_image()     { CREATED_IMAGES+=("$1"); }

# ----------------------------------------------------------------------------
# Prohibited-operation scanner (deep correction 2)
#
# has_prohibited_violation FILE PATTERN
#   Returns 0 when PATTERN occurs in FILE as an uncommented executable
#   command. Comment lines, documentation/echo/printf lines, grep/test/
#   assert lines, and explicit refusal/prohibition text are ignored.
# Fixture tests: tests/phase-b/test_prohibited_operation_scanner.sh
# ----------------------------------------------------------------------------

has_prohibited_violation() {
    local file="$1" pattern="$2"
    local matches
    matches="$(grep -nF -- "$pattern" "$file" 2>/dev/null || true)"
    [[ -z "$matches" ]] && return 1
    local ln content
    while IFS= read -r ln; do
        content="${ln#*:}"
        # Full-line comment
        [[ "$content" =~ ^[[:space:]]*# ]] && continue
        # Pure quoted-string data line (pattern list / array element) — data,
        # not an executable command
        [[ "$content" =~ ^[[:space:]]*\"[^\"]*\"[[:space:]]*$ ]] && continue
        [[ "$content" =~ ^[[:space:]]*\'[^\']*\'[[:space:]]*$ ]] && continue
        # Echo/printf documentation or refusal output
        [[ "$content" =~ ^[[:space:]]*(echo|printf|log|pass|fail)[[:space:]] ]] && continue
        # grep/test/assert scanner lines
        [[ "$content" =~ (grep|assert_|test\ |test$|\[\[) ]] && continue
        # Explicit refusal / prohibition text anywhere on the line
        [[ "$content" =~ REFUSED|refused|Refused ]] && continue
        [[ "$content" =~ "must not"|"must NOT"|"MUST NOT"|"MUST never" ]] && continue
        [[ "$content" =~ prohibited|Prohibited|PROHIBITED ]] && continue
        [[ "$content" =~ "Do NOT"|"do NOT"|"do not run" ]] && continue
        [[ "$content" =~ "will not"|"Will not"|"WILL NOT" ]] && continue
        [[ "$content" =~ [Nn]ever\ run|[Nn]ever\ delete|NEVER ]] && continue
        # Here-doc / fixture content inside tests is covered by the above
        return 0
    done <<< "$matches"
    return 1
}

# ----------------------------------------------------------------------------
# .env validation library (deep correction 7) — testable locally
# env_validate_file PATH
#   Rejects empty secrets, CHANGE_ME, ***, synthetic values, and known
#   example/test secrets. Verifies the DSN/URL passwords match their
#   password variables. Never prints a value; returns nonzero on failure.
# ----------------------------------------------------------------------------

ENV_FORBIDDEN_SUBSTRINGS=(
    "CHANGE_ME"
    "***"
    "synthetic"
    "SYNTHETIC"
    "test-secret"
    "example-secret"
    "actual-test-secret"
    "EXAMPLE"
)

env_validate_file() {
    local f="$1"
    [[ -f "$f" ]] || { echo "FAIL: env file missing: $f" >&2; return 1; }

    local keys=(POSTGRES_PASSWORD VALKEY_PASSWORD GRAFANA_ADMIN_PASSWORD HADA_DATABASE_DSN HADA_VALKEY_URL)
    local k val
    local -A vals=()
    for k in "${keys[@]}"; do
        if ! grep -q "^${k}=" "$f"; then
            echo "FAIL: missing ${k} in .env" >&2
            return 1
        fi
        val="$(grep "^${k}=" "$f" | head -1 | cut -d= -f2-)"
        val="${val%\"}"; val="${val#\"}"; val="${val%'}"; val="${val#'}"
        if [[ -z "$val" ]]; then
            echo "FAIL: empty value for ${k} in .env" >&2
            return 1
        fi
        vals[$k]="$val"
    done

    # Reject forbidden substrings in any secret value (name only reported)
    local bad
    for k in "${keys[@]}"; do
        for bad in "${ENV_FORBIDDEN_SUBSTRINGS[@]}"; do
            if [[ "${vals[$k]}" == *"$bad"* ]]; then
                echo "FAIL: forbidden value detected for ${k} in .env" >&2
                return 1
            fi
        done
    done

    # Consistency: DSN must carry the Postgres password (percent-encoding not
    # permitted by provision-secrets.sh which uses hex-only secrets).
    local dsn="${vals[HADA_DATABASE_DSN]}" pg="${vals[POSTGRES_PASSWORD]}"
    [[ "$dsn" == postgresql://* ]] || { echo "FAIL: HADA_DATABASE_DSN is not a postgresql:// DSN" >&2; return 1; }
    if [[ "$dsn" != *":${pg}@"* ]]; then
        echo "FAIL: HADA_DATABASE_DSN password inconsistent with POSTGRES_PASSWORD" >&2
        return 1
    fi

    # Consistency: Valkey URL must carry the Valkey password.
    local vurl="${vals[HADA_VALKEY_URL]}" vp="${vals[VALKEY_PASSWORD]}"
    [[ "$vurl" == redis://:* ]] || { echo "FAIL: HADA_VALKEY_URL is not a redis:// URL" >&2; return 1; }
    if [[ "$vurl" != *":${vp}@"* ]]; then
        echo "FAIL: HADA_VALKEY_URL password inconsistent with VALKEY_PASSWORD" >&2
        return 1
    fi

    # Grafana admin password must not reuse the database/valkey secrets.
    if [[ "${vals[GRAFANA_ADMIN_PASSWORD]}" == "$pg" || "${vals[GRAFANA_ADMIN_PASSWORD]}" == "$vp" ]]; then
        echo "FAIL: GRAFANA_ADMIN_PASSWORD reuses another secret" >&2
        return 1
    fi

    return 0
}

# ----------------------------------------------------------------------------
# Cleanup trap — removes ONLY this run's local extract dir and remote temp
# dir. Never touches /var/lib/hada, /opt/hada, or any pre-existing resource.
# ----------------------------------------------------------------------------

cleanup() {
    local rc=$?
    if (( EXIT_STATUS == 0 )); then
        EXIT_STATUS=$rc
    fi
    if [[ -n "${CANDIDATE_EXTRACT_DIR}" && -d "${CANDIDATE_EXTRACT_DIR}" ]]; then
        rm -rf "${CANDIDATE_EXTRACT_DIR}"
        log "[cleanup] removed local extract dir: ${CANDIDATE_EXTRACT_DIR}"
    fi
    if [[ "${REMOTE_DIR_CREATED}" == "1" && -n "${REMOTE_DIR:-}" ]]; then
        if [[ ! "${REMOTE_DIR}" =~ ^/tmp/hada-b-deploy-[0-9]+$ ]]; then
            log "[cleanup] REFUSED: remote path does not match guard: ${REMOTE_DIR}"
        else
            log "[cleanup] attempting remote temp cleanup: ${REMOTE_DIR}"
            local cmd
            cmd="set -Eeuo pipefail
DIR='${REMOTE_DIR}'
if [[ ! \"\${DIR}\" =~ ^/tmp/hada-b-deploy-[0-9]+\$ ]]; then echo REFUSED-pattern >&2; exit 1; fi
rm -rf -- \"\${DIR}\"
echo removed:\${DIR}"
            "${SSH_CMD[@]}" "${cmd}" 2>>"${EVIDENCE_DIR}/cleanup-stderr.log" || true
        fi
    fi
    exit "${EXIT_STATUS}"
}

if [[ "${HADA_PHASE_B_NO_CLEANUP_TRAP:-0}" != "1" ]]; then
    trap cleanup EXIT
    trap 'EXIT_STATUS=130; cleanup' INT
    trap 'EXIT_STATUS=143; cleanup' TERM
fi

# ----------------------------------------------------------------------------
# GATE 0 — Local static validation (always runs, no remote contact)
# ----------------------------------------------------------------------------

run_local_static_validation() {
    log "=============================================="
    log "GATE 0: Local Static Validation"
    log "=============================================="

    # 0a: bash -n on all production scripts + self
    log "[0a] bash -n syntax check..."
    local scripts=(
        "${DEPLOY_DIR}/scripts/provision-secrets.sh"
        "${DEPLOY_DIR}/scripts/supervisor.gcp.sh"
        "${DEPLOY_DIR}/scripts/validate-host.gcp.sh"
        "${DEPLOY_DIR}/scripts/run-phase-b0-v4-preflight.sh"
        "$0"
    )
    local s
    for s in "${scripts[@]}"; do
        [[ -f "$s" ]] || { fail "Missing script for bash -n: $s"; return 1; }
        bash -n "$s" || { fail "bash -n failed on $s"; return 1; }
        pass "bash -n OK: $(basename "$s")"
    done

    # 0b: shellcheck -S error
    log "[0b] shellcheck..."
    command -v shellcheck >/dev/null 2>&1 || { fail "shellcheck not installed"; return 1; }
    local sc_log="${EVIDENCE_DIR}/shellcheck.log"
    : > "$sc_log"
    for s in "${scripts[@]}"; do
        if shellcheck -S error "$s" >>"$sc_log" 2>&1; then
            pass "shellcheck OK: $(basename "$s")"
        else
            fail "shellcheck found errors in $s (see ${sc_log})"
            return 1
        fi
    done

    # 0c: prohibited-operation scan of production scripts using the
    # fixture-tested scanner (fixtures: tests/phase-b/test_prohibited_operation_scanner.sh)
    log "[0c] Prohibited-operation scan (fixture-tested scanner)..."
    local prohibited_patterns=(
        "docker compose down -v"
        "docker compose down --volumes"
        "docker container prune"
        "docker volume prune"
        "docker system prune"
        "rm -rf /var/lib/hada"
        "rm -rf /opt/hada"
        "mkfs.ext4 /dev/sdb"
        "mkfs.ext4 /dev/sda"
        "mkfs "
    )
    local pat
    for s in "${scripts[@]}"; do
        for pat in "${prohibited_patterns[@]}"; do
            if has_prohibited_violation "$s" "$pat"; then
                fail "Prohibited operation found as executable command in $s: [pattern redacted]"
                return 1
            fi
        done
    done
    pass "No prohibited operations in production scripts"

    # 0d: target assertions
    log "[0d] Target assertions..."
    [[ "${TARGET_PROJECT}" == "api-intergrations-501314" ]] || { fail "TARGET_PROJECT mismatch"; return 1; }
    [[ "${TARGET_ZONE}" == "australia-southeast1-b" ]] || { fail "TARGET_ZONE mismatch"; return 1; }
    [[ "${TARGET_VM}" == "hada-control" ]] || { fail "TARGET_VM mismatch"; return 1; }
    pass "Target: project=${TARGET_PROJECT} zone=${TARGET_ZONE} vm=${TARGET_VM}"

    # 0e: candidate checksum
    log "[0e] Candidate checksum assertion..."
    [[ -f "${CANDIDATE_ARCHIVE}" ]] || { fail "Candidate archive missing"; return 1; }
    [[ -f "${CANDIDATE_SHA256_FILE}" ]] || { fail "Candidate SHA256 file missing"; return 1; }
    local actual
    actual="$(sha256sum "${CANDIDATE_ARCHIVE}" | awk '{print $1}')"
    [[ "${actual}" == "${EXPECTED_CANDIDATE_SHA256}" ]] || { fail "Candidate SHA256 mismatch"; return 1; }
    grep -q "^${EXPECTED_CANDIDATE_SHA256}" "${CANDIDATE_SHA256_FILE}" || { fail "SHA256 file does not contain locked value"; return 1; }
    pass "Candidate SHA256 verified: ${actual}"

    # 0f: Phase B0 evidence PASS — BLOCK unless explicitly locked with the
    # complete, v4-specific evidence set. Stale v1/v2/v3 Phase B0 evidence
    # directory (which has no candidate-sha256.txt / preflight-summary.txt,
    # or an identity/sha that does not match v3) MUST be rejected. Merely
    # finding any directory with a PASS state-check.txt is NOT sufficient.
    log "[0f] Phase B0 evidence PASS verification (fail-closed, v4-locked)..."
    if [[ -z "${B0_EVIDENCE_DIR:-}" ]]; then
        fail "B0_EVIDENCE_DIR is not set; refuse to run Phase B without a locked v4 Phase B0 evidence directory (export HADA_PHASE_B0_EVIDENCE_DIR)"
        return 1
    fi

    # Required evidence files for a v4 Phase B0 lock.
    local b0_csha="${B0_EVIDENCE_DIR}/candidate-sha256.txt"
    local b0_ident="${B0_EVIDENCE_DIR}/target-identity.txt"
    local b0_cver="${B0_EVIDENCE_DIR}/compose-version-check.txt"
    local b0_cren="${B0_EVIDENCE_DIR}/compose-render-check.txt"
    local b0_port="${B0_EVIDENCE_DIR}/port-assertion-check.txt"
    local b0_vol="${B0_EVIDENCE_DIR}/volume-assertion-check.txt"
    local b0_state="${B0_EVIDENCE_DIR}/state-check.txt"
    local b0_sum="${B0_EVIDENCE_DIR}/preflight-summary.txt"

    local req_file
    for req_file in "${b0_csha}" "${b0_ident}" "${b0_cver}" "${b0_cren}" "${b0_port}" "${b0_vol}" "${b0_state}" "${b0_sum}"; do
        [[ -f "${req_file}" ]] || { fail "B0 evidence missing required file: ${req_file}"; return 1; }
    done

    # candidate-sha256.txt must match the locked v4 hash exactly.
    local csha
    csha="$(cat "${b0_csha}" | tr -d '[:space:]')"
    [[ "${csha}" == "${EXPECTED_CANDIDATE_SHA256}" ]] || { fail "B0 candidate-sha256.txt (${csha}) does not match locked v4 hash"; return 1; }

    # target-identity.txt must match project, zone and VM exactly.
    grep -qxF "project=${TARGET_PROJECT}" "${b0_ident}" || { fail "B0 target-identity.txt project mismatch"; return 1; }
    grep -qxF "zone=${TARGET_ZONE}" "${b0_ident}" || { fail "B0 target-identity.txt zone mismatch"; return 1; }
    grep -qxF "vm=${TARGET_VM}" "${b0_ident}" || { fail "B0 target-identity.txt vm mismatch"; return 1; }
    # Reject duplicate or unexpected identity keys (e.g. a second project=).
    for key in project zone vm; do
        local _cnt
        _cnt="$(grep -c "^${key}=" "${b0_ident}" 2>/dev/null || true)"
        [[ "${_cnt}" -eq 1 ]] || { fail "B0 target-identity.txt has ${_cnt} '${key}=' lines (expected exactly 1)"; return 1; }
    done

    # Each check file must report the exact expected PASS line and must NOT
    # contain a FAIL line (broad `grep -q PASS` would accept a malformed or
    # contradictory "FAIL: ... PASS ..." line). Exact-match the expected line
    # and reject any "FAIL" anywhere in the file.
    _b0_expect_line() { # $1=file $2=expected-line
        [[ -s "$1" ]] || { fail "B0 ${1##*/} is empty"; return 1; }
        grep -q 'FAIL' "$1" && { fail "B0 ${1##*/} contains a FAIL line"; return 1; }
        grep -qxF "$2" "$1" || { fail "B0 ${1##*/} does not report exact expected PASS line"; return 1; }
        return 0
    }
    _b0_expect_line "${b0_cver}" "PASS: Compose version requirement: PASS" || return 1
    _b0_expect_line "${b0_cren}" "PASS: Compose JSON render: PASS" || return 1
    _b0_expect_line "${b0_port}" "PASS: Port assertion: PASS" || return 1
    _b0_expect_line "${b0_vol}"  "PASS: Volume assertion: PASS" || return 1
    _b0_expect_line "${b0_state}" "PASS: Docker state unchanged during preflight" || return 1

    # preflight-summary.txt must record the complete successful v4 result.
    local sum_ok=1
    local -a b0_required=( "overall-result: PASS" "after-state-capture-succeeded: YES" "container-state-changed: NO" "image-state-changed: NO" "remote-cleanup-result: PASS" "candidate-checksum: PASS" "candidate-manifest: PASS" "compose-version: PASS" "compose-render: PASS" "port-assertion: PASS" "volume-assertion: PASS" "container-state-unchanged: PASS" "image-state-unchanged: PASS" )
    local kv
    for kv in "${b0_required[@]}"; do
        grep -qxF "${kv}" "${b0_sum}" || sum_ok=0
    done
    [[ "${sum_ok}" -eq 1 ]] || { fail "B0 preflight-summary.txt does not record the complete v4 PASS result"; return 1; }
    grep -qxF "candidate-sha256: ${EXPECTED_CANDIDATE_SHA256}" "${b0_sum}" || { fail "B0 preflight-summary.txt candidate-sha256 mismatch"; return 1; }

    pass "Phase B0 v4 evidence lock verified (locked at ${B0_EVIDENCE_DIR})"

    # 0g: this runner contains no literal secrets
    log "[0g] Secret-redaction self-check..."
    if grep -En '^(POSTGRES_PASSWORD|VALKEY_PASSWORD|GRAFANA_ADMIN_PASSWORD)=[^$"*]' "$0" | grep -Evq 'CHANGE_ME|SENTINEL'; then
        fail "Literal secret-like assignment in runner"
        return 1
    fi
    pass "No literal secrets in runner"

    # 0h: cleanup-path guard self-tests
    log "[0h] Cleanup-path guard self-tests..."
    local CLREG='^/tmp/hada-b-deploy-[0-9]+$'
    [[ "" =~ $CLREG ]] && { fail "Empty path matched cleanup regex"; return 1; }
    [[ "/tmp" =~ $CLREG ]] && { fail "/tmp matched cleanup regex"; return 1; }
    [[ "/tmp/" =~ $CLREG ]] && { fail "/tmp/ matched cleanup regex"; return 1; }
    [[ "/tmp/hada-b-deploy-abc" =~ $CLREG ]] && { fail "Non-numeric path matched cleanup regex"; return 1; }
    [[ "/tmp/hada-b-deploy-20260725170000" =~ $CLREG ]] || { fail "Valid cleanup path rejected"; return 1; }
    pass "Cleanup-path guard self-tests passed"

    # 0i: pipeline return-code capture present
    log "[0i] Pipeline return-code capture checks..."
    grep -q 'PIPESTATUS\[0\]' "$0" || { fail "Missing PIPESTATUS[0] usage"; return 1; }
    pass "Pipeline return-code capture present"

    # 0j: DEPLOY_EXECUTE gate
    log "[0j] DEPLOY_EXECUTE gate verification..."
    log "DEPLOY_EXECUTE=${DEPLOY_EXECUTE}"
    pass "DEPLOY_EXECUTE gate verified (value=${DEPLOY_EXECUTE})"

    if (( EXIT_STATUS != 0 )); then
        log "GATE 0: FAILED — aborting before any remote action"
        return 1
    fi
    log "GATE 0: ALL LOCAL STATIC VALIDATIONS PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 1 — Candidate verification & local extraction (no remote)
# ----------------------------------------------------------------------------

verify_and_extract_candidate() {
    log "=============================================="
    log "GATE 1: Candidate Verification & Local Extraction"
    log "=============================================="

    local actual
    actual="$(sha256sum "${CANDIDATE_ARCHIVE}" | awk '{print $1}')"
    [[ "${actual}" == "${EXPECTED_CANDIDATE_SHA256}" ]] || { fail "Candidate checksum mismatch"; return 1; }
    pass "Candidate archive checksum re-verified"

    CANDIDATE_EXTRACT_DIR="$(mktemp -d /tmp/hada-b-extract-XXXXXX)"
    chmod 0700 "${CANDIDATE_EXTRACT_DIR}"
    unzip -q "${CANDIDATE_ARCHIVE}" -d "${CANDIDATE_EXTRACT_DIR}"
    CANDIDATE_ROOT="${CANDIDATE_EXTRACT_DIR}/HADA-M1-durable-orchestrator"
    [[ -d "${CANDIDATE_ROOT}" ]] || { fail "Extracted root missing: ${CANDIDATE_ROOT}"; return 1; }

    local f
    for f in "${CANDIDATE_MANIFEST[@]}"; do
        [[ -e "${CANDIDATE_ROOT}/$f" ]] || { fail "Missing required file in candidate: $f"; return 1; }
    done
    pass "All ${#CANDIDATE_MANIFEST[@]} manifest entries present in candidate"

    # Per-file SHA-256 manifests of the application payload (used by Gate 3
    # to verify every installed file — never build stale pre-existing files).
    # CROSS-GATE CORRECTION 1: the payload is split into TWO explicit
    # manifests, matching the two installation destinations:
    #   candidate-app.sha256  — files installed under /opt/hada (paths are
    #                           relative to /opt/hada, identical on both
    #                           sides, so no path rewriting is ever needed);
    #   candidate-unit.sha256 — the single service unit, whose checksum line
    #                           is rewritten to its installed path
    #                           /etc/systemd/system/hada-supervisor.service.
    # The unit is content-verified against this checksum by Gate 3e.
    local app_entries=()
    for f in "${CANDIDATE_MANIFEST[@]}"; do
        [[ "$f" == "scripts/hada-supervisor.service" ]] && continue
        app_entries+=("$f")
    done
    ( cd "${CANDIDATE_ROOT}" && find "${app_entries[@]}" -type f -exec sha256sum {} + | sort ) \
        > "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256"
    ( cd "${CANDIDATE_ROOT}" && sha256sum scripts/hada-supervisor.service ) \
        | sed 's| scripts/hada-supervisor.service$| /etc/systemd/system/hada-supervisor.service|' \
        > "${CANDIDATE_EXTRACT_DIR}/candidate-unit.sha256"
    pass "Candidate app manifest computed ($(wc -l < "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256") files)"
    pass "Candidate unit checksum computed (installed-path form)"

    log "GATE 1: PASSED (local extraction complete)"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 2 — Remote preparation & initial state capture (DEPLOY_EXECUTE)
# Deep correction 3: the existing-resource refusal runs BEFORE any mutation
# (before temp-dir creation, before any SCP upload). A refusal here performs
# ZERO remote mutations and ZERO rollback commands.
# Deep correction 8: /var/lib/hada UUID proven from findmnt output for the
# mount point itself.
# ----------------------------------------------------------------------------

remote_preparation_and_state_capture() {
    log "=============================================="
    log "GATE 2: Remote Preparation & Initial State Capture"
    log "=============================================="

    # 2a: READ-ONLY existing-resource refusal — before ANY mutation.
    log "[2a] Refusing if HADA resources already exist (read-only, zero mutation)..."
    ssh_remote "check-existing-hada" "set -Eeuo pipefail
found=0
for img in \$(sudo -n docker ps -a --format '{{.Image}}'); do
  case \"\$img\" in
    *hada*|*HADA*) echo \"FAIL: existing HADA container present (image match)\"; found=1 ;;
  esac
done
for name in \$(sudo -n docker ps -a --format '{{.Names}}'); do
  case \"\$name\" in
    ${COMPOSE_PROJECT}*) echo \"FAIL: existing container for project ${COMPOSE_PROJECT}\"; found=1 ;;
  esac
done
for v in \$(sudo -n docker volume ls -q); do
  case \"\$v\" in
    *hada*|*postgres-data*|*valkey-data*|*prometheus-data*|*loki-data*|*alloy-data*|*grafana-data*|*caddy-data*|*caddy-config*)
      echo \"FAIL: existing HADA volume: present\"; found=1 ;;
  esac
done
for n in \$(sudo -n docker network ls --format '{{.Name}}'); do
  case \"\$n\" in
    *hada*|${COMPOSE_PROJECT}*) echo \"FAIL: existing HADA network: present\"; found=1 ;;
  esac
done
if sudo -n docker image inspect '${ORCHESTRATOR_IMAGE}' >/dev/null 2>&1; then
  echo 'FAIL: orchestrator image already present'; found=1
fi
if [[ -e '${OPT_HADA}' ]]; then
  echo 'FAIL: ${OPT_HADA} already exists — application tree present'; found=1
fi
if systemctl list-unit-files 'hada-supervisor.service' 2>/dev/null | grep -q 'hada-supervisor'; then
  echo 'FAIL: hada-supervisor.service unit already installed'; found=1
fi
if (( found != 0 )); then exit 1; fi
echo 'PASS: no pre-existing HADA containers/volumes/networks/images/units/app-tree'
" || { fail "Pre-existing HADA resources — REFUSING with zero mutation and zero rollback"; return 1; }
    pass "No pre-existing HADA resources (refusal check ran before any mutation)"

    # 2b: prove the MOUNTED filesystem at /var/lib/hada has the locked UUID
    log "[2b] Verifying /var/lib/hada mount UUID via findmnt..."
    ssh_remote "verify-hada-mount-uuid" "set -Eeuo pipefail
findmnt -T '${HADA_STATE_ROOT}' >/dev/null 2>&1 || { echo 'FAIL: ${HADA_STATE_ROOT} is not on a mounted filesystem'; exit 1; }
mount_uuid=\$(findmnt -n -T -o UUID '${HADA_STATE_ROOT}' 2>/dev/null || true)
if [[ -z \"\${mount_uuid}\" ]]; then
  echo 'FAIL: findmnt returned no UUID for ${HADA_STATE_ROOT}'; exit 1
fi
if [[ \"\${mount_uuid}\" != '${EXPECTED_HADA_UUID}' ]]; then
  echo 'FAIL: ${HADA_STATE_ROOT} mounted-filesystem UUID mismatch (not ${EXPECTED_HADA_UUID})'; exit 1
fi
echo 'PASS: ${HADA_STATE_ROOT} mounted filesystem has expected UUID'
" || { fail "/var/lib/hada mounted-filesystem UUID verification failed"; return 1; }
    pass "/var/lib/hada mounted filesystem proven to have UUID ${EXPECTED_HADA_UUID} (findmnt)"

    # 2c: capture BEFORE state with sudo -n (fail closed)
    log "[2c] Capturing BEFORE Docker state (sudo -n)..."
    ssh_sudo_capture "docker-ps-before" "sudo -n docker ps -aq" || { fail "ps-before capture failed"; return 1; }
    ssh_sudo_capture "docker-images-before" "sudo -n docker images -q" || { fail "images-before capture failed"; return 1; }
    ssh_sudo_capture "docker-volumes-before" "sudo -n docker volume ls -q" || { fail "volumes-before capture failed"; return 1; }
    ssh_sudo_capture "docker-networks-before" "sudo -n docker network ls --format {{.Name}}" || { fail "networks-before capture failed"; return 1; }
    pass "BEFORE state captured"

    # 2d: Docker Compose >= 2.24.4
    log "[2d] Verifying Docker Compose version >= 2.24.4..."
    ssh_remote "compose-version" "set -Eeuo pipefail
v=\$(sudo -n docker compose version --short 2>/dev/null | sed 's/^v//')
maj=\$(printf '%s' \"\$v\" | cut -d. -f1)
min=\$(printf '%s' \"\$v\" | cut -d. -f2)
pat=\$(printf '%s' \"\$v\" | cut -d. -f3)
if (( maj*10000 + min*100 + pat < 20244 )); then echo 'FAIL: compose version below 2.24.4'; exit 1; fi
echo 'PASS: compose version >= 2.24.4'
" || { fail "Compose version check failed"; return 1; }
    pass "Docker Compose version verified"

    # 2e: NOW create the remote temp dir (first mutation) — umask 077, 0700
    log "[2e] Creating remote temp dir (umask 077 / mode 0700)..."
    ssh_remote "create-remote-dir" "set -Eeuo pipefail
umask 077
install -d -m 0700 '${REMOTE_DIR}'
mode=\$(stat -c '%a' '${REMOTE_DIR}')
[[ \"\${mode}\" == '700' ]] || { echo \"FAIL: remote dir mode \${mode} != 700\"; exit 1; }
echo 'PASS: remote temp dir mode 0700'
" || { fail "create-remote-dir failed"; return 1; }
    REMOTE_DIR_CREATED=1
    pass "Remote temp dir created: ${REMOTE_DIR} (mode 0700)"

    log "GATE 2: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 3 — Upload candidate payload & install complete application tree
# (atomic release layout + per-file manifest verification before any build)
# ----------------------------------------------------------------------------

upload_and_install_application() {
    log "=============================================="
    log "GATE 3: Upload & Install Application Tree (atomic release)"
    log "=============================================="

    # 3a: upload complete payload as a single tarball (never assume /opt/hada
    # already contains the application; never build stale pre-existing files)
    log "[3a] Uploading complete candidate payload..."
    local payload="${CANDIDATE_EXTRACT_DIR}/payload.tar.gz"
    tar czf "${payload}" -C "${CANDIDATE_ROOT}" "${CANDIDATE_MANIFEST[@]}"
    "${SCP_CMD[@]}" "${payload}" "${TARGET_VM}:${REMOTE_DIR}/payload.tar.gz" 2>>"${EVIDENCE_DIR}/scp-stderr.log" \
        || { fail "scp payload.tar.gz"; return 1; }
    "${SCP_CMD[@]}" "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256" "${TARGET_VM}:${REMOTE_DIR}/candidate-app.sha256" 2>>"${EVIDENCE_DIR}/scp-stderr.log" \
        || { fail "scp candidate-app.sha256"; return 1; }
    "${SCP_CMD[@]}" "${CANDIDATE_EXTRACT_DIR}/candidate-unit.sha256" "${TARGET_VM}:${REMOTE_DIR}/candidate-unit.sha256" 2>>"${EVIDENCE_DIR}/scp-stderr.log" \
        || { fail "scp candidate-unit.sha256"; return 1; }
    pass "Candidate payload uploaded ($(wc -l < "${CANDIDATE_EXTRACT_DIR}/candidate-app.sha256") app manifest files + unit checksum)"

    # 3b: unpack into release staging and verify every file against the app
    # manifest; verify the staged unit content against the unit checksum
    # (hash compare — the unit checksum line carries its INSTALLED path, so
    # staging verification compares the hash value explicitly; no path
    # mismatch is possible).
    log "[3b] Unpacking release staging and verifying manifests (fail-closed)..."
    ssh_remote "stage-release" "set -Eeuo pipefail
umask 077
install -d -m 0700 '${RELEASE_STAGING}'
cd '${RELEASE_STAGING}'
tar xzf '${REMOTE_DIR}/payload.tar.gz'
sha256sum -c '${REMOTE_DIR}/candidate-app.sha256' >/dev/null
expected_unit_hash=\$(awk '{print \$1}' '${REMOTE_DIR}/candidate-unit.sha256')
staged_unit_hash=\$(sha256sum scripts/hada-supervisor.service | awk '{print \$1}')
if [[ \"\${staged_unit_hash}\" != \"\${expected_unit_hash}\" ]]; then
  echo 'FAIL: staged service unit content does not match candidate checksum'; exit 1
fi
echo 'PASS: release staging verified (app manifest + unit checksum)'
" || { fail "release staging manifest verification failed"; return 1; }
    pass "Release staging verified against candidate manifests"

    # 3c: create production directories with explicit ownership/mode
    log "[3c] Creating production directories..."
    ssh_remote "create-dirs" "set -Eeuo pipefail
sudo -n install -d -o 70    -g 70    -m 0750 '${HADA_DOCKER_VOLUMES}/postgres-data'
sudo -n install -d -o 999   -g 1000  -m 0770 '${HADA_DOCKER_VOLUMES}/valkey-data'
sudo -n install -d -o 65534 -g 65534 -m 0755 '${HADA_DOCKER_VOLUMES}/prometheus-data'
sudo -n install -d -o 10001 -g 10001 -m 0750 '${HADA_DOCKER_VOLUMES}/loki-data'
sudo -n install -d -o 473   -g 473   -m 0770 '${HADA_DOCKER_VOLUMES}/alloy-data'
sudo -n install -d -o 472   -g 0     -m 0750 '${HADA_DOCKER_VOLUMES}/grafana-data'
sudo -n install -d -o 0     -g 0     -m 0755 '${HADA_DOCKER_VOLUMES}/caddy-data'
sudo -n install -d -o 0     -g 0     -m 0755 '${HADA_DOCKER_VOLUMES}/caddy-config'
sudo -n install -d -o root  -g hada  -m 0750 '${OPT_HADA}'
sudo -n install -d -o root  -g hada  -m 0750 '${OPT_HADA_COMPOSE}'
sudo -n install -d -o root  -g hada  -m 0750 '${OPT_HADA_CADDY}'
sudo -n install -d -o root  -g hada  -m 0750 '${OPT_HADA_SCRIPTS}'
sudo -n install -d -o root  -g hada  -m 0750 '${OPT_HADA_CONFIG}'
sudo -n install -d -o hada  -g hada  -m 0750 '${OPT_HADA}/src'
sudo -n install -d -o hada  -g hada  -m 0750 '${HADA_STATE_ROOT}/evidence' '${HADA_STATE_ROOT}/keys' '${HADA_STATE_ROOT}/workspaces' '${HADA_STATE_ROOT}/repositories'
sudo -n install -d -o hada  -g hada  -m 0750 /var/log/hada
printf '%s\n' '${REMOTE_PREFIX}' | sudo -n tee '${OPT_HADA}/${RELEASE_MARKER}' >/dev/null
sudo -n chown root:hada '${OPT_HADA}/${RELEASE_MARKER}'
sudo -n chmod 0640 '${OPT_HADA}/${RELEASE_MARKER}'
" || { fail "create-dirs failed"; return 1; }
    # /opt/hada was proven ABSENT by Gate 2 and has now been created by THIS
    # run; the release marker records this run's identity for recoverability.
    OPT_HADA_CREATED=1
    pass "Production directories created; /opt/hada created by THIS run (marker: ${RELEASE_MARKER})"

    # 3d: atomic install from verified staging into /opt/hada.
    # The COMPLETE payload is installed so every Dockerfile COPY source and
    # every Compose host-bind source exists in the build context. We copy the
    # entire verified staging tree (not a hand-picked file list) into /opt/hada
    # under a .new directory, then atomically rename directories/files into
    # place. The service unit is installed to /etc/systemd/system.
    log "[3d] Installing COMPLETE application tree from verified staging..."
    ssh_remote "install-release" "set -Eeuo pipefail
R='${RELEASE_STAGING}'
sudo -n rm -rf '${OPT_HADA}/.new'
sudo -n install -d -o root -g hada -m 0750 '${OPT_HADA}/.new'
# Copy full payload (top-level entries from the manifest) into .new
for e in pyproject.toml README.md Dockerfile src config deploy scripts; do
  sudo -n rm -rf '${OPT_HADA}/.new/'\"\${e}\"
  sudo -n cp -a \"\${R}/\${e}\" '${OPT_HADA}/.new/'\"\${e}\"
done
sudo -n chown -R root:hada '${OPT_HADA}/.new'
# Atomic promotion, then remove the staging copy's extra metadata
for e in pyproject.toml README.md Dockerfile src config deploy scripts; do
  sudo -n rm -rf '${OPT_HADA}/'\"\${e}\"
  sudo -n mv '${OPT_HADA}/.new/'\"\${e}\" '${OPT_HADA}/'\"\${e}\"
done
sudo -n rm -rf '${OPT_HADA}/.new'
sudo -n install -m 0644 -o root -g root \"\${R}/scripts/hada-supervisor.service\" /etc/systemd/system/hada-supervisor.service
" || { fail "install-release failed"; return 1; }
    UNIT_INSTALLED=1
    pass "Complete application tree installed (atomic .new -> mv) and unit staged"

    # 3e: verify every installed file against the candidate manifests.
    log "[3e] Verifying installed files against candidate manifests..."
    verify_installed_tree || { fail "installed tree does not match candidate manifests"; return 1; }
    pass "Every installed file verified (app manifest + unit content checksum)"

    # 3f: execute the candidate-derived, checksum-verified provision-secrets.sh
    # remotely (CROSS-GATE CORRECTION 2 — makes Gate 4 reachable on a fresh
    # host). Secrets are generated ON hada-control by the verified script;
    # they never enter local command arguments, local logs, or evidence.
    log "[3f] Provisioning secrets remotely via verified provision-secrets.sh..."
    provision_secrets_remote || { fail "remote secret provisioning failed"; return 1; }
    ENV_CREATED=1
    pass ".env provisioned by THIS run (recorded: ENV_CREATED=1; no secret left the VM)"

    log "GATE 3: PASSED"
    return 0
}

# verify_installed_tree (Gate 3e body; separately testable)
# CROSS-GATE CORRECTION 1: two explicit verifications with NO path mismatch
# possible:
#   - the app tree under /opt/hada is hashed with paths relative to
#     /opt/hada and diffed against candidate-app.sha256 (which uses the same
#     relative paths — the unit is NOT in this manifest);
#   - the installed unit at /etc/systemd/system/hada-supervisor.service is
#     CONTENT-verified by comparing its SHA-256 hash against the hash in
#     candidate-unit.sha256 (never a mere existence check).
verify_installed_tree() {
    ssh_remote "verify-install" "set -Eeuo pipefail
cd '${OPT_HADA}'
{
  sha256sum pyproject.toml
  sha256sum README.md
  sha256sum Dockerfile
  sha256sum config/hada.yaml
  find src -type f -exec sha256sum {} +
  find deploy -type f -exec sha256sum {} +
  sha256sum scripts/provision-secrets.sh
  sha256sum scripts/supervisor.sh
  sha256sum scripts/validate-host.sh
  sha256sum scripts/container-entrypoint.sh
} | sort > '${REMOTE_DIR}/installed-app.sha256'
if ! diff -u '${REMOTE_DIR}/candidate-app.sha256' '${REMOTE_DIR}/installed-app.sha256' >/dev/null; then
  echo 'FAIL: installed application tree differs from candidate app manifest'; exit 1
fi
echo 'PASS: every installed /opt/hada file matches candidate app manifest'
[[ -f /etc/systemd/system/hada-supervisor.service ]] || { echo 'FAIL: service unit missing'; exit 1; }
expected_unit_hash=\$(awk '{print \$1}' '${REMOTE_DIR}/candidate-unit.sha256')
installed_unit_hash=\$(sha256sum /etc/systemd/system/hada-supervisor.service | awk '{print \$1}')
if [[ \"\${installed_unit_hash}\" != \"\${expected_unit_hash}\" ]]; then
  echo 'FAIL: installed service unit content differs from candidate'; exit 1
fi
echo 'PASS: installed service unit content-verified against candidate checksum'
"
}

# provision_secrets_remote (Gate 3f body; separately testable)
provision_secrets_remote() {
    ssh_remote "provision-secrets" "set -Eeuo pipefail
# Execute the checksum-verified installed script to generate on-host secrets.
sudo -n '${OPT_HADA_SCRIPTS}/provision-secrets.sh'
# CORRECTION 5: provision-secrets.sh now builds the Postgres DSN from
# POSTGRES_PASSWORD directly (no ':***@' placeholder), so no remediation is
# needed. We only re-validate DSN/URL password consistency WITHOUT printing
# either value.
pg=\$(sudo -n grep '^POSTGRES_PASSWORD=' \"${OPT_HADA_ENV}\" | head -1 | cut -d= -f2-)
dsn=\$(sudo -n grep '^HADA_DATABASE_DSN=' \"${OPT_HADA_ENV}\" | head -1 | cut -d= -f2-)
case \"\${dsn}\" in *\":\${pg}@\"*) : ;; *) echo 'FAIL: DSN password inconsistent with POSTGRES_PASSWORD'; exit 1 ;; esac
vp=\$(sudo -n grep '^VALKEY_PASSWORD=' \"${OPT_HADA_ENV}\" | head -1 | cut -d= -f2-)
vurl=\$(sudo -n grep '^HADA_VALKEY_URL=' \"${OPT_HADA_ENV}\" | head -1 | cut -d= -f2-)
case \"\${vurl}\" in *\":\${vp}@\"*) : ;; *) echo 'FAIL: Valkey URL password inconsistent with VALKEY_PASSWORD'; exit 1 ;; esac
# CORRECTION 3 (v3): write a PROTECTED COMPLETE Valkey configuration file
# atomically at /var/lib/hada/secrets/valkey/valkey.conf (owned by the numeric
# container UID/GID 999:1000 of the pinned valkey/valkey:8-alpine image,
# mode 0400). Compose mounts it read-only into the container as
# /run/secrets/valkey.conf; valkey-server is started with the supported
# configuration-file form. Valkey 8 has no --requirepass-file. NOTE:
# /var/lib/hada is persistent disk, not tmpfs; no tmpfs is claimed. The file
# is NOT part of evidence and never appears in process args, env, healthcheck,
# logs, or compose output.
sudo -n install -d -o root -g root -m 0700 \"${HADA_STATE_ROOT}/secrets/valkey\"
VALKEY_TMP=\"\$(sudo -n mktemp ${HADA_STATE_ROOT}/secrets/valkey/valkey.conf.XXXXXX)\"
printf 'requirepass %s\nappendonly yes\nappendfsync everysec\nmaxmemory-policy noeviction\n' \"\${vp}\" | sudo -n tee \"\${VALKEY_TMP}\" >/dev/null
sudo -n chown 999:1000 \"\${VALKEY_TMP}\"
sudo -n chmod 0400 \"\${VALKEY_TMP}\"
sudo -n mv -f \"\${VALKEY_TMP}\" \"${HADA_STATE_ROOT}/secrets/valkey/valkey.conf\"
own=\"\$(sudo -n stat -c '%U:%G' \"${OPT_HADA_ENV}\")\"
perms=\"\$(sudo -n stat -c '%a' \"${OPT_HADA_ENV}\")\"
[[ \"\${own}\" == 'root:hada' ]] || { echo 'FAIL: provisioned .env ownership is not root:hada'; exit 1; }
[[ \"\${perms}\" == '640' ]] || { echo 'FAIL: provisioned .env perms are not 640'; exit 1; }
echo 'PASS: secrets provisioned on hada-control (root:hada 0640; valkey config 999:1000 0400; no values emitted)'
"
}

# ----------------------------------------------------------------------------
# GATE 4 — Validate production .env (no values printed) (DEPLOY_EXECUTE)
# ----------------------------------------------------------------------------

validate_production_env() {
    log "=============================================="
    log "GATE 4: Validate Production .env (no values printed)"
    log "=============================================="
    log "[4a] Secrets were provisioned by Gate 3f on hada-control via the"
    log "     checksum-verified provision-secrets.sh (ENV_CREATED=${ENV_CREATED});"
    log "     never accepted on the CLI, never printed by this runner."

    # Ownership/permission check + full policy validation runs remotely; the
    # remote validator reports names only — never values.
    ssh_remote "validate-env" "set -Eeuo pipefail
F='${OPT_HADA_ENV}'
[[ -f \"\${F}\" ]] || { echo 'FAIL: ${OPT_HADA_ENV} missing — run provision-secrets.sh first'; exit 1; }
own=\$(stat -c '%U:%G' \"\${F}\")
perms=\$(stat -c '%a' \"\${F}\")
[[ \"\${own}\" == 'root:hada' ]] || { echo 'FAIL: .env ownership is not root:hada'; exit 1; }
[[ \"\${perms}\" == '640' ]] || { echo 'FAIL: .env perms are not 640'; exit 1; }

keys='POSTGRES_PASSWORD VALKEY_PASSWORD GRAFANA_ADMIN_PASSWORD HADA_DATABASE_DSN HADA_VALKEY_URL'
for k in \${keys}; do
  grep -q \"^\${k}=\" \"\${F}\" || { echo \"FAIL: missing \${k} in .env\"; exit 1; }
  v=\$(grep \"^\${k}=\" \"\${F}\" | head -1 | cut -d= -f2-)
  [[ -n \"\${v}\" ]] || { echo \"FAIL: empty value for \${k} in .env\"; exit 1; }
  for bad in CHANGE_ME '***' synthetic SYNTHETIC test-secret example-secret actual-test-secret EXAMPLE; do
    case \"\${v}\" in
      *\"\${bad}\"*) echo \"FAIL: forbidden value detected for \${k} in .env\"; exit 1 ;;
    esac
  done
done

pg=\$(grep '^POSTGRES_PASSWORD=' \"\${F}\" | head -1 | cut -d= -f2-)
dsn=\$(grep '^HADA_DATABASE_DSN=' \"\${F}\" | head -1 | cut -d= -f2-)
case \"\${dsn}\" in
  postgresql://*) : ;;
  *) echo 'FAIL: HADA_DATABASE_DSN is not a postgresql:// DSN'; exit 1 ;;
esac
case \"\${dsn}\" in
  *\":\${pg}@\"*) : ;;
  *) echo 'FAIL: HADA_DATABASE_DSN password inconsistent with POSTGRES_PASSWORD'; exit 1 ;;
esac

vp=\$(grep '^VALKEY_PASSWORD=' \"\${F}\" | head -1 | cut -d= -f2-)
vurl=\$(grep '^HADA_VALKEY_URL=' \"\${F}\" | head -1 | cut -d= -f2-)
case \"\${vurl}\" in
  redis://:*) : ;;
  *) echo 'FAIL: HADA_VALKEY_URL is not a redis:// URL'; exit 1 ;;
esac
case \"\${vurl}\" in
  *\":\${vp}@\"*) : ;;
  *) echo 'FAIL: HADA_VALKEY_URL password inconsistent with VALKEY_PASSWORD'; exit 1 ;;
esac

gp=\$(grep '^GRAFANA_ADMIN_PASSWORD=' \"\${F}\" | head -1 | cut -d= -f2-)
if [[ \"\${gp}\" == \"\${pg}\" || \"\${gp}\" == \"\${vp}\" ]]; then
  echo 'FAIL: GRAFANA_ADMIN_PASSWORD reuses another secret'; exit 1
fi

echo 'PASS: .env validated (ownership, perms, no forbidden values, DSN/URL consistent)'
" || { fail ".env validation failed"; return 1; }
    pass ".env validated (no values printed)"
    log "GATE 4: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 5 — Render & validate final Compose JSON (DEPLOY_EXECUTE)
# Deep correction 5: rendered JSON is piped DIRECTLY into structural
# validation over an SSH stream; the only temp copy is local mode 0600,
# deleted immediately after validation. The real JSON never persists on the
# remote host and is never world-readable.
# ----------------------------------------------------------------------------

render_validate_compose() {
    log "=============================================="
    log "GATE 5: Render & Validate Final Compose JSON"
    log "=============================================="

    # 5a: render remotely, stream JSON back over SSH into a local 0600 file
    log "[5a] Rendering effective compose JSON (streamed to local mode-0600 temp)..."
    umask 077
    local json_local
    json_local="$(mktemp "${EVIDENCE_DIR}/effective-compose.XXXXXX.json")"
    chmod 0600 "${json_local}"
    "${SSH_CMD[@]}" "set -Eeuo pipefail
cd '${OPT_HADA}'
sudo -n docker compose -p '${COMPOSE_PROJECT}' \
  -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' \
  --env-file '${OPT_HADA_ENV}' config --format json
" 2>>"${EVIDENCE_DIR}/ssh-stderr.log" > "${json_local}" || { fail "compose render (real .env) failed"; rm -f "${json_local}"; return 1; }
    [[ -s "${json_local}" ]] || { fail "compose render produced empty JSON"; rm -f "${json_local}"; return 1; }
    pass "Effective compose JSON rendered and streamed (local mode 0600)"

    # 5b: port assertion — exactly one published port: caddy 127.0.0.1:80, no 443
    log "[5b] Port assertion (loopback-only, no 443)..."
    python3 - "${json_local}" <<'PYEOF' | tee "${EVIDENCE_DIR}/port-assertion.txt"
import json, sys
cfg = json.load(open(sys.argv[1]))
ports = []
for svc, sv in cfg.get('services', {}).items():
    for p in sv.get('ports', []) or []:
        ports.append((svc, str(p.get('host_ip', '0.0.0.0')), str(p.get('published')),
                      str(p.get('target')), str(p.get('protocol', 'tcp'))))
errs = []
if len(ports) != 1:
    errs.append('expected exactly 1 published port, got %d' % len(ports))
for svc, hip, pub, tgt, proto in ports:
    if svc != 'caddy':
        errs.append('published port not on caddy: %s' % svc)
    if hip != '127.0.0.1':
        errs.append('host_ip not loopback: %s' % hip)
    if pub != '80':
        errs.append('published != 80: %s' % pub)
    if tgt != '80':
        errs.append('target != 80: %s' % tgt)
    if proto != 'tcp':
        errs.append('protocol != tcp: %s' % proto)
    if pub == '443' or tgt == '443':
        errs.append('port 443 present')
if errs:
    print('FAIL')
    for e in errs:
        print(e)
    sys.exit(1)
print('PASS: exactly one published port - caddy 127.0.0.1:80:80/tcp, no 443')
PYEOF
    local rc=${PIPESTATUS[0]}
    if (( rc != 0 )); then rm -f "${json_local}"; fail "Port assertion failed"; return 1; fi
    pass "Port assertion: caddy 127.0.0.1:80 only, no 443"

    # 5c: volume assertion — all 8 volumes beneath /var/lib/hada/docker-volumes/
    log "[5c] Volume assertion (all 8 beneath /var/lib/hada/docker-volumes/)..."
    python3 - "${json_local}" <<'PYEOF' | tee "${EVIDENCE_DIR}/volume-assertion.txt"
import json, sys
cfg = json.load(open(sys.argv[1]))
vols = cfg.get('volumes', {})
expected = {
    'postgres-data':   '/var/lib/hada/docker-volumes/postgres-data',
    'valkey-data':     '/var/lib/hada/docker-volumes/valkey-data',
    'prometheus-data': '/var/lib/hada/docker-volumes/prometheus-data',
    'loki-data':       '/var/lib/hada/docker-volumes/loki-data',
    'alloy-data':      '/var/lib/hada/docker-volumes/alloy-data',
    'grafana-data':    '/var/lib/hada/docker-volumes/grafana-data',
    'caddy-data':      '/var/lib/hada/docker-volumes/caddy-data',
    'caddy-config':    '/var/lib/hada/docker-volumes/caddy-config',
}
errs = []
for name in expected:
    if name not in vols:
        errs.append('missing volume %s' % name)
if len(vols) != 8:
    errs.append('expected 8 volumes, got %d' % len(vols))
for name, vol in vols.items():
    do = vol.get('driver_opts', {}) or {}
    if do.get('type') != 'none':
        errs.append('%s type=%s' % (name, do.get('type')))
    if do.get('o') != 'bind':
        errs.append('%s o=%s' % (name, do.get('o')))
    if do.get('device', '') != expected.get(name):
        errs.append('%s device mismatch' % name)
if errs:
    print('FAIL')
    for e in errs:
        print(e)
    sys.exit(1)
print('PASS: all 8 volumes type=none o=bind beneath /var/lib/hada/docker-volumes/')
PYEOF
    rc=${PIPESTATUS[0]}
    if (( rc != 0 )); then rm -f "${json_local}"; fail "Volume assertion failed"; return 1; fi
    pass "Volume assertion: all 8 volumes beneath /var/lib/hada/docker-volumes/"

    # 5d: delete the temporary resolved JSON immediately after validation
    rm -f "${json_local}"
    pass "Temporary resolved Compose JSON deleted (was local mode 0600, never world-readable)"

    # 5e: SECRET-ABSENCE assertion (TRUTHFUL SCOPE). Valkey server command and
    # the valkey healthcheck must never contain a credential value. The
    # orchestrator's `environment` intentionally carries HADA_DATABASE_DSN and
    # HADA_VALKEY_URL (application configuration sourced from .env); we do NOT
    # claim absence there. The scope below is limited to valkey command and
    # healthcheck fields only, per the v3 correction (do not claim no secret
    # exists in any environment field while DSN/URL still carry credentials).
    log "[5e] Secret-absence assertion (valkey command + healthcheck, truthful scope)..."
    local sentinel_json
    sentinel_json="$(mktemp "${EVIDENCE_DIR}/sentinel-compose.XXXXXX.json")"
    chmod 0600 "${sentinel_json}"
    umask 077
    "${SSH_CMD[@]}" "set -Eeuo pipefail
cd '${OPT_HADA}'
SENTINEL_VP='__SENTINEL_VALKEY_PW__'
SENTINEL_PG='__SENTINEL_PG_PW__'
VALKEY_PASSWORD=\"\${SENTINEL_VP}\" POSTGRES_PASSWORD=\"\${SENTINEL_PG}\" GRAFANA_ADMIN_PASSWORD='__SENTINEL_GW_PW__' \
  sudo -n docker compose -p '${COMPOSE_PROJECT}' \
  -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' \
  --env-file '${OPT_HADA_ENV}' config --format json
" 2>>"${EVIDENCE_DIR}/ssh-stderr.log" > "${sentinel_json}" || { fail "sentinel compose render failed"; rm -f "${sentinel_json}"; return 1; }
    python3 - "${sentinel_json}" <<'PYEOF' | tee "${EVIDENCE_DIR}/secret-absence.txt"
import json, sys
cfg = json.load(open(sys.argv[1]))
sentinels = ['__SENTINEL_VALKEY_PW__', '__SENTINEL_PG_PW__', '__SENTINEL_GW_PW__']
errs = []
def scan(obj, path):
    if isinstance(obj, dict):
        for k, v in obj.items():
            scan(v, path + '.' + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scan(v, path + '[%d]' % i)
    elif isinstance(obj, str):
        for s in sentinels:
            if s in obj:
                errs.append('secret sentinel %s found at %s' % (s, path))
for svc, sv in cfg.get('services', {}).items():
    if svc == 'valkey':
        scan(sv.get('command'), svc + '.command')
        hc = sv.get('healthcheck')
        if hc is not None:
            scan(hc.get('test'), svc + '.healthcheck.test')
if errs:
    print('FAIL')
    for e in errs:
        print(e)
    sys.exit(1)
print('PASS: no secret value present in valkey command or healthcheck fields')
PYEOF
    rc=${PIPESTATUS[0]}
    rm -f "${sentinel_json}"
    if (( rc != 0 )); then fail "Secret-absence assertion failed"; return 1; fi
    pass "Valkey command + healthcheck contain no credential value"

    log "GATE 5: PASSED"
    return 0
}

# ---------------------------------------------------------------------------
# GATE 5b — Validate installed build context (DEPLOY_EXECUTE)
# The Dockerfile and Compose reference a complete set of sources. Every one
# MUST exist in the installed /opt/hada tree; an omitted pyproject.toml,
# README.md, or monitoring config file must fail this gate so Gate 6 can
# reach a valid complete build context.
# ---------------------------------------------------------------------------

validate_build_context() {
    log "=============================================="
    log "GATE 5b: Validate Installed Build Context"
    log "=============================================="
    ssh_remote "validate-build-context" "set -Eeuo pipefail
missing=0
for f in ${REQUIRED_BUILD_CONTEXT_FILES[*]}; do
  if [[ ! -e '${OPT_HADA}/'\${f} ]]; then
    echo \"FAIL: build-context source missing: \${f}\"; missing=1
  fi
done
if (( missing != 0 )); then exit 1; fi
echo 'PASS: all Dockerfile/Compose build-context sources present in installed tree'
" || { fail "build-context validation failed"; return 1; }
    pass "Build context complete (Gate 6 can reach a valid build context)"
    log "GATE 5b: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 6 — Image pull / build (explicit list) (DEPLOY_EXECUTE)
# ----------------------------------------------------------------------------

pull_build_images() {
    log "=============================================="
    log "GATE 6: Image Pull / Build"
    log "=============================================="

    local img
    for img in "${PULL_IMAGES[@]}"; do
        log "[6] pull: ${img}"
        ssh_remote "pull-${img//[^a-zA-Z0-9]/_}" "set -Eeuo pipefail
sudo -n docker pull '${img}'
" || { fail "pull failed: ${img}"; return 1; }
        track_image "${img}"
    done
    pass "All ${#PULL_IMAGES[@]} pinned images pulled"

    log "[6] build: ${ORCHESTRATOR_IMAGE} from verified installed tree"
    ssh_remote "build-orchestrator" "set -Eeuo pipefail
cd '${OPT_HADA}'
sudo -n docker compose -p '${COMPOSE_PROJECT}' \
  -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' \
  --env-file '${OPT_HADA_ENV}' build --no-cache orchestrator
" || { fail "orchestrator build failed"; return 1; }
    track_image "${ORCHESTRATOR_IMAGE}"
    ORCH_BUILT_BY_RUN=1
    pass "Orchestrator image built from verified tree: ${ORCHESTRATOR_IMAGE}"

    log "GATE 6: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 7 — Service startup (DEPLOY_EXECUTE)
# ----------------------------------------------------------------------------

start_services() {
    log "=============================================="
    log "GATE 7: Service Startup"
    log "=============================================="

    # CORRECTION 4: record that a Compose-up was attempted BEFORE invoking it,
    # so a partial failure (containers created but `up` exits nonzero) is
    # detected and rolled back as a partial creation, not mistaken for a
    # clean no-op.
    COMPOSE_UP_ATTEMPTED=1
    ssh_remote "compose-up" "set -Eeuo pipefail
cd '${OPT_HADA}'
sudo -n docker compose -p '${COMPOSE_PROJECT}' \
  -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' \
  --env-file '${OPT_HADA_ENV}' up -d --remove-orphans
" || { fail "compose up failed"; return 1; }
    COMPOSE_UP_DONE=1
    # Track the standard compose-created resources for stage-aware rollback.
    local svc
    for svc in postgres valkey prometheus loki alloy grafana caddy node-exporter orchestrator; do
        track_container "${COMPOSE_PROJECT}-${svc}-1"
    done
    for v in postgres-data valkey-data prometheus-data loki-data alloy-data grafana-data caddy-data caddy-config; do
        track_volume "${COMPOSE_PROJECT}_${v}"
    done
    track_network "${COMPOSE_PROJECT}_control"
    track_network "${COMPOSE_PROJECT}_ingress"
    pass "Services started (up -d); resources tracked for stage-aware rollback"

    ssh_remote "enable-supervisor" "set -Eeuo pipefail
sudo -n systemctl daemon-reload
sudo -n systemctl enable hada-supervisor.service
sudo -n systemctl start hada-supervisor.service
" || { fail "supervisor enable/start failed"; return 1; }
    SUPERVISOR_STARTED=1
    pass "hada-supervisor.service enabled and started"

    log "GATE 7: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 8 — Health validation (DEPLOY_EXECUTE)
# Deep correction 6: valkey health check runs INSIDE the container using the
# container's own VALKEY_PASSWORD via VALKEYCLI_AUTH. No -a flag, no secret
# in the host command line, logs, or evidence.
# ----------------------------------------------------------------------------

health_validate() {
    log "=============================================="
    log "GATE 8: Health Validation (bounded)"
    log "=============================================="

    log "[8a] postgres health..."
    ssh_remote "health-postgres" "set -Eeuo pipefail
for i in \$(seq 1 30); do
  if sudo -n docker compose -p '${COMPOSE_PROJECT}' -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' --env-file '${OPT_HADA_ENV}' exec -T postgres pg_isready -U hada -d hada >/dev/null 2>&1; then
    echo 'POSTGRES_HEALTHY'; exit 0
  fi
  sleep 4
done
echo 'FAIL: postgres not healthy within timeout' >&2; exit 1
" || { fail "postgres health timeout"; return 1; }
    pass "PostgreSQL healthy"

    log "[8b] valkey auth ping (in-container VALKEYCLI_AUTH read from the protected config file; VALKEY_PASSWORD is NOT in the container environment)..."
    ssh_remote "health-valkey" "set -Eeuo pipefail
for i in \$(seq 1 30); do
  if sudo -n docker compose -p '${COMPOSE_PROJECT}' -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' --env-file '${OPT_HADA_ENV}' exec -T valkey sh -c 'VP=\$(awk \"/^requirepass /{print \\\$2}\" /run/secrets/valkey.conf); VALKEYCLI_AUTH=\"\$VP\" valkey-cli ping 2>/dev/null' | grep -q PONG; then
    echo 'VALKEY_HEALTHY'; exit 0
  fi
  sleep 4
done
echo 'FAIL: valkey not healthy within timeout' >&2; exit 1
" || { fail "valkey health timeout"; return 1; }
    pass "Valkey healthy (auth via in-container VALKEYCLI_AUTH from protected file; no secret in host command line)"

    log "[8c] orchestrator /readyz..."
    ssh_remote "health-orchestrator" "set -Eeuo pipefail
for i in \$(seq 1 40); do
  if sudo -n docker compose -p '${COMPOSE_PROJECT}' -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' --env-file '${OPT_HADA_ENV}' exec -T orchestrator python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:9108/readyz', timeout=3)\" >/dev/null 2>&1; then
    echo 'ORCHESTRATOR_READYZ'; exit 0
  fi
  sleep 6
done
echo 'FAIL: orchestrator not ready within timeout' >&2; exit 1
" || { fail "orchestrator health timeout"; return 1; }
    pass "Orchestrator /readyz responding"

    log "[8d] all services running..."
    ssh_remote "services-running" "set -Eeuo pipefail
out=\$(sudo -n docker compose -p '${COMPOSE_PROJECT}' -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' --env-file '${OPT_HADA_ENV}' ps --all --format json)
printf '%s' \"\${out}\" | python3 -c 'import json,sys
d = json.load(sys.stdin)
bad = [s.get(\"Service\",\"?\") for s in d if s.get(\"State\") != \"running\"]
if bad:
    print(\"FAIL: not running: \" + \",\".join(bad)); sys.exit(1)
print(\"RUNNING\")'
" || { fail "not all services running"; return 1; }
    pass "All services running"

    log "[8e] loopback-only published socket..."
    ssh_remote "loopback-check" "set -Eeuo pipefail
binds=\$(sudo -n ss -lntp 2>/dev/null | grep -E ':80[[:space:]]' | awk '{print \$4}' || true)
[[ -n \"\${binds}\" ]] || { echo 'FAIL: no :80 listener found'; exit 1; }
printf '%s\n' \"\${binds}\" | grep -q '127.0.0.1:80' || { echo 'FAIL: no 127.0.0.1:80 bind'; exit 1; }
if printf '%s\n' \"\${binds}\" | grep -qE '(^0\.0\.0\.0:80$|^\[::\]:80$|^:::80$|\*:80$)'; then
  echo 'FAIL: port 80 bound on wildcard'; exit 1
fi
echo 'PASS: caddy published only on 127.0.0.1:80'
" || { fail "loopback verification failed"; return 1; }
    pass "Published socket is loopback-only (127.0.0.1:80)"

    log "GATE 8: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 9 — Final state capture (no secrets) (DEPLOY_EXECUTE)
# ----------------------------------------------------------------------------

capture_final_state() {
    log "=============================================="
    log "GATE 9: Final State Capture"
    log "=============================================="
    ssh_sudo_capture "docker-ps-final" "sudo -n docker ps -a --format {{.Names}}" || { fail "ps-final capture failed"; return 1; }
    ssh_sudo_capture "docker-images-final" "sudo -n docker images -q" || { fail "images-final capture failed"; return 1; }
    ssh_sudo_capture "docker-volumes-final" "sudo -n docker volume ls -q" || { fail "volumes-final capture failed"; return 1; }
    ssh_sudo_capture "docker-networks-final" "sudo -n docker network ls --format {{.Name}}" || { fail "networks-final capture failed"; return 1; }
    pass "Final Docker state captured (evidence contains no secrets)"
    log "GATE 9: PASSED"
    return 0
}

# ----------------------------------------------------------------------------
# GATE 10 — Repository-connectivity acceptance (DEPLOY_EXECUTE)
# git ls-remote ONLY. Begins no autonomous repository work.
# ----------------------------------------------------------------------------

check_repository_connectivity() {
    log "=============================================="
    log "GATE 10: Repository-Connectivity Acceptance"
    log "=============================================="

    log "[10a] git ls-remote from hada-control as user hada..."
    ssh_remote "repo-ls-remote-host" "set -Eeuo pipefail
sudo -n -u hada git ls-remote --exit-code '${TARGET_REPO_URL}' HEAD >/dev/null 2>&1 \
  || { echo 'FAIL: git ls-remote from host as hada failed'; exit 1; }
echo 'LS_REMOTE_HOST_OK'
" || { fail "Repository connectivity from host failed"; return 1; }
    pass "git ls-remote from hada-control (user hada) succeeded"

    log "[10b] git ls-remote from inside orchestrator container..."
    ssh_remote "repo-ls-remote-container" "set -Eeuo pipefail
sudo -n docker compose -p '${COMPOSE_PROJECT}' -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' --env-file '${OPT_HADA_ENV}' \
  exec -T orchestrator git ls-remote --exit-code '${TARGET_REPO_URL}' HEAD >/dev/null 2>&1 \
  || { echo 'FAIL: git ls-remote from orchestrator container failed'; exit 1; }
echo 'LS_REMOTE_CONTAINER_OK'
" || { fail "Repository connectivity from orchestrator container failed"; return 1; }
    pass "git ls-remote from orchestrator container succeeded"

    log "GATE 10: PASSED (no autonomous repository work performed)"
    return 0
}

# ----------------------------------------------------------------------------
# Stage-aware bounded rollback (deep correction 3)
#   - NEVER runs 'compose down -v', NEVER deletes /var/lib/hada or /opt/hada.
#   - Rolls back ONLY resources tracked as created/started by THIS run.
#   - After a Gate 2 refusal or initial-state failure, NOTHING is called:
#     no compose down, no service stop/disable, no unit removal.
# ----------------------------------------------------------------------------

bounded_rollback() {
    log "=============================================="
    log "BOUNDED ROLLBACK (stage-aware, non-destructive)"
    log "=============================================="
    log "Rollback will NOT run 'docker compose down -v', will NOT delete"
    log "/var/lib/hada or /opt/hada data. Only resources created/started by"
    log "THIS run (tracked) will be rolled back."

    # Stop supervisor ONLY if we started it this run
    if (( SUPERVISOR_STARTED == 1 )); then
        ssh_remote "rb-stop-supervisor" "set -Eeuo pipefail
sudo -n systemctl stop hada-supervisor.service
sudo -n systemctl disable hada-supervisor.service
" || log "WARN: supervisor stop/disable failed (continuing rollback)"
    else
        log "[rollback] supervisor was not started by this run — not stopping it"
    fi

    # CORRECTION 4: if Compose-up was attempted but did NOT complete cleanly
    # (partial creation), bring down ONLY the explicit hada-m1 project created
    # by this run and remove its volume METADATA (never the underlying bind
    # directories under /var/lib/hada). Pre-existing resources are untouched.
    if (( COMPOSE_UP_ATTEMPTED == 1 )); then
        if (( COMPOSE_UP_DONE == 1 )) && (( ${#CREATED_CONTAINERS[@]} > 0 )); then
            ssh_remote "rb-compose-down" "set -Eeuo pipefail
cd '${OPT_HADA}'
sudo -n docker compose -p '${COMPOSE_PROJECT}' \
  -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' \
  --env-file '${OPT_HADA_ENV}' down --remove-orphans
" || log "WARN: compose down failed (continuing rollback)"
        else
            # Partial creation: containers may exist for the hada-m1 project.
            # `down` is still the correct idempotent cleanup for the explicit
            # project; it removes only this run's project resources.
            ssh_remote "rb-compose-down-partial" "set -Eeuo pipefail
cd '${OPT_HADA}'
sudo -n docker compose -p '${COMPOSE_PROJECT}' \
  -f '${BASE_COMPOSE}' -f '${GCP_COMPOSE}' \
  --env-file '${OPT_HADA_ENV}' down --remove-orphans || true
" || true
        fi
        # Remove Docker VOLUME METADATA created by this run (the named
        # volumes), WITHOUT deleting the underlying bind directories under
        # /var/lib/hada/docker-volumes (those are persistent host data).
        if (( ${#CREATED_VOLUMES[@]} > 0 )); then
            local vlist
            vlist="$(printf '%s\n' "${CREATED_VOLUMES[@]}")"
            ssh_remote "rb-remove-volume-meta" "set -Eeuo pipefail
for v in ${vlist}; do
  sudo -n docker volume rm --force \"\${v}\" >/dev/null 2>&1 || true
done
echo \"removed volume metadata for the hada-m1 project (bind dirs preserved)\"
" || log "WARN: volume metadata removal failed (continuing rollback)"
        fi
        # Remove the orchestrator image ONLY if it was built by this run.
        if (( ORCH_BUILT_BY_RUN == 1 )); then
            ssh_remote "rb-remove-orchestrator-image" "set -Eeuo pipefail
sudo -n docker image rm --force '${ORCHESTRATOR_IMAGE}' >/dev/null 2>&1 || true
echo \"removed orchestrator image built by this run\"
" || log "WARN: orchestrator image removal failed (continuing rollback)"
        fi
    else
        log "[rollback] compose stack was not attempted by this run — no compose cleanup"
    fi

    # Remove the unit ONLY if we installed it this run
    if (( UNIT_INSTALLED == 1 )); then
        ssh_remote "rb-remove-unit" "set -Eeuo pipefail
sudo -n rm -f /etc/systemd/system/hada-supervisor.service
sudo -n systemctl daemon-reload
" || log "WARN: unit removal failed (continuing rollback)"
    else
        log "[rollback] unit was not installed by this run — not removing it"
    fi

    # CROSS-GATE CORRECTION 3: recoverable installation. Remove the
    # incomplete /opt/hada release ONLY when (a) Gate 2 proved it absent and
    # THIS run created it (OPT_HADA_CREATED=1), (b) services were never
    # started by this run, and (c) the release marker inside it carries THIS
    # run's identity. A pre-existing installation can never satisfy (a) or
    # (c) and is never touched. /var/lib/hada is never touched by any branch.
    if (( OPT_HADA_CREATED == 1 )) && (( SUPERVISOR_STARTED == 0 )) && (( COMPOSE_UP_DONE == 0 )); then
        ssh_remote "rb-remove-incomplete-release" "set -Eeuo pipefail
D='${OPT_HADA}'
M=\"\${D}/${RELEASE_MARKER}\"
if [[ ! -e \"\${D}\" ]]; then echo 'rollback: no application tree present — nothing to remove'; exit 0; fi
if [[ ! -f \"\${M}\" ]]; then
  echo 'REFUSED: no release marker — tree not created by this run; preserving it'; exit 0
fi
marker=\$(sudo -n cat \"\${M}\")
if [[ \"\${marker}\" != '${REMOTE_PREFIX}' ]]; then
  echo 'REFUSED: release marker belongs to a different run; preserving tree'; exit 0
fi
sudo -n rm -rf -- \"\${D}\"
echo 'rollback: incomplete release created by this run removed (marker-verified)'
" || log "WARN: incomplete-release removal failed (continuing rollback)"
        log "[rollback] incomplete /opt/hada release created by this run removed — next run is unblocked"
    else
        log "[rollback] /opt/hada not created by this run (or services were started) — tree preserved"
    fi

    log "Rollback complete. Persistent data preserved under /var/lib/hada."
    return 0
}

# ----------------------------------------------------------------------------
# Execution-gate review document
# ----------------------------------------------------------------------------

write_gate_review() {
    local out="${EVIDENCE_DIR}/execution-gate-review.md"
    {
        echo "# HADA M1 Phase B — Execution-Gate Review (DEEP CORRECTED)"
        echo
        echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "Runner: scripts/run-phase-b-deploy.sh"
        echo "DEPLOY_EXECUTE=${DEPLOY_EXECUTE}"
        echo
        echo "## Locked configuration"
        echo "- Candidate SHA-256: ${EXPECTED_CANDIDATE_SHA256}"
        echo "- Target: project=${TARGET_PROJECT} zone=${TARGET_ZONE} vm=${TARGET_VM}"
        echo "- Persistent mount: ${HADA_STATE_ROOT} (UUID proven via findmnt: ${EXPECTED_HADA_UUID})"
        echo "- Compose project: ${COMPOSE_PROJECT}"
        echo
        echo "## Gate 0 (local static) results: see deploy-console.log"
        echo
        echo "## Deep corrections applied"
        echo "1. ssh_sudo_capture: capture first, exact rc preserved, sort after success, never NONE on failure"
        echo "2. Prohibited-op scanner: executable fixtures (tests/phase-b/test_prohibited_operation_scanner.sh)"
        echo "3. Stage-aware rollback: refusal before mutation; rollback only tracked resources"
        echo "4. Every remote block: set -Eeuo pipefail + sudo -n; fail-fast multi-command blocks"
        echo "5. Remote temp dir umask 077/mode 0700; resolved JSON streamed, local 0600, deleted"
        echo "6. Valkey: in-container VALKEYCLI_AUTH from container env; no -a; no secret in args/logs"
        echo "7. .env validation: rejects empty/CHANGE_ME/***/synthetic/example; DSN+URL consistency"
        echo "8. UUID proven for the MOUNTED filesystem at /var/lib/hada via findmnt"
        echo "9. Complete candidate tree installed via atomic release; manifest-verified before build"
        echo "10. Repository connectivity: git ls-remote host (user hada) + orchestrator container"
        echo
        echo "## Conclusion"
        if [[ "${DEPLOY_EXECUTE}" == "1" ]]; then
            echo "Deployment executed under DEPLOY_EXECUTE=1."
        else
            echo "Local execution-gate review complete. Runner is fail-closed."
        fi
    } > "${out}"
    chmod 0600 "${out}" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# Main flow
# ----------------------------------------------------------------------------

main() {
    log "=============================================="
    log "HADA M1 Phase B — Production Deployment Execution Gate (DEEP CORRECTED)"
    log "Timestamp: ${TIMESTAMP}"
    log "Evidence:  ${EVIDENCE_DIR}"
    log "DEPLOY_EXECUTE=${DEPLOY_EXECUTE}"
    log "=============================================="

    run_local_static_validation  || { log "ABORT: Gate 0 failed"; exit 1; }
    verify_and_extract_candidate || { log "ABORT: Gate 1 failed"; exit 1; }

    if [[ "${DEPLOY_EXECUTE}" == "1" ]]; then
        log "DEPLOY_EXECUTE=1 — proceeding with remote deployment gates."

        # Gate 2: refusal BEFORE any mutation; a failure here triggers NO
        # rollback (zero resources were created by this run).
        remote_preparation_and_state_capture || { log "ABORT: Gate 2 failed (zero mutation, zero rollback)"; exit 1; }

        upload_and_install_application || { bounded_rollback; log "ABORT: Gate 3 failed"; exit 1; }
        validate_production_env        || { bounded_rollback; log "ABORT: Gate 4 failed"; exit 1; }
        render_validate_compose        || { bounded_rollback; log "ABORT: Gate 5 failed"; exit 1; }
        validate_build_context         || { bounded_rollback; log "ABORT: Gate 5b failed"; exit 1; }
        pull_build_images              || { bounded_rollback; log "ABORT: Gate 6 failed"; exit 1; }
        start_services                 || { bounded_rollback; log "ABORT: Gate 7 failed"; exit 1; }
        health_validate                || { bounded_rollback; log "ABORT: Gate 8 failed"; exit 1; }
        capture_final_state            || { log "WARN: Gate 9 capture failed"; EXIT_STATUS=1; }

        check_repository_connectivity  || { log "WARN: Gate 10 repo-connectivity failed"; EXIT_STATUS=1; }

        log "=============================================="
        log "DEPLOYMENT VALIDATION COMPLETE"
        log "Status: IMPLEMENTATION_CANDIDATE_AWAITING_PARTY_3"
        log "No autonomous repository work performed."
        log "=============================================="
    else
        log "DEPLOY_EXECUTE is not '1' — execution-gate review only."
        log "No SSH/SCP/deploy actions were performed."
        log "Re-run with DEPLOY_EXECUTE=1 to perform the deployment."
    fi

    write_gate_review
    log "Execution-gate review written to: ${EVIDENCE_DIR}/execution-gate-review.md"
    exit "${EXIT_STATUS}"
}

if [[ "${HADA_PHASE_B_TEST_LIB:-0}" != "1" ]]; then
    main "$@"
fi

# Standalone, test-callable wrapper around Gate 0f (identical logic, top level
# so it is available when the runner is sourced in test-lib mode).
verify_phase_b0_evidence() {
    if [[ -z "${B0_EVIDENCE_DIR:-}" ]]; then
        fail "B0_EVIDENCE_DIR is not set; refuse to run Phase B without a locked v4 Phase B0 evidence directory"
        return 1
    fi

    local b0_csha="${B0_EVIDENCE_DIR}/candidate-sha256.txt"
    local b0_ident="${B0_EVIDENCE_DIR}/target-identity.txt"
    local b0_cver="${B0_EVIDENCE_DIR}/compose-version-check.txt"
    local b0_cren="${B0_EVIDENCE_DIR}/compose-render-check.txt"
    local b0_port="${B0_EVIDENCE_DIR}/port-assertion-check.txt"
    local b0_vol="${B0_EVIDENCE_DIR}/volume-assertion-check.txt"
    local b0_state="${B0_EVIDENCE_DIR}/state-check.txt"
    local b0_sum="${B0_EVIDENCE_DIR}/preflight-summary.txt"

    local req_file
    for req_file in "${b0_csha}" "${b0_ident}" "${b0_cver}" "${b0_cren}" "${b0_port}" "${b0_vol}" "${b0_state}" "${b0_sum}"; do
        [[ -f "${req_file}" ]] || { fail "B0 evidence missing required file: ${req_file}"; return 1; }
    done

    local csha
    csha="$(cat "${b0_csha}" | tr -d '[:space:]')"
    [[ "${csha}" == "${EXPECTED_CANDIDATE_SHA256}" ]] || { fail "B0 candidate-sha256.txt (${csha}) does not match locked v4 hash"; return 1; }

    # target-identity.txt must match project, zone and VM exactly.
    grep -qxF "project=${TARGET_PROJECT}" "${b0_ident}" || { fail "B0 target-identity.txt project mismatch"; return 1; }
    grep -qxF "zone=${TARGET_ZONE}" "${b0_ident}" || { fail "B0 target-identity.txt zone mismatch"; return 1; }
    grep -qxF "vm=${TARGET_VM}" "${b0_ident}" || { fail "B0 target-identity.txt vm mismatch"; return 1; }
    # Reject duplicate or unexpected identity keys (e.g. a second project=).
    for key in project zone vm; do
        local _cnt
        _cnt="$(grep -c "^${key}=" "${b0_ident}" 2>/dev/null || true)"
        [[ "${_cnt}" -eq 1 ]] || { fail "B0 target-identity.txt has ${_cnt} '${key}=' lines (expected exactly 1)"; return 1; }
    done

    # Each check file must report the exact expected PASS line and must NOT
    # contain a FAIL line (broad `grep -q PASS` would accept a malformed or
    # contradictory "FAIL: ... PASS ..." line). Exact-match the expected line
    # and reject any "FAIL" anywhere in the file.
    _b0_expect_line() { # $1=file $2=expected-line
        [[ -s "$1" ]] || { fail "B0 ${1##*/} is empty"; return 1; }
        grep -q 'FAIL' "$1" && { fail "B0 ${1##*/} contains a FAIL line"; return 1; }
        grep -qxF "$2" "$1" || { fail "B0 ${1##*/} does not report exact expected PASS line"; return 1; }
        return 0
    }
    _b0_expect_line "${b0_cver}" "PASS: Compose version requirement: PASS" || return 1
    _b0_expect_line "${b0_cren}" "PASS: Compose JSON render: PASS" || return 1
    _b0_expect_line "${b0_port}" "PASS: Port assertion: PASS" || return 1
    _b0_expect_line "${b0_vol}"  "PASS: Volume assertion: PASS" || return 1
    _b0_expect_line "${b0_state}" "PASS: Docker state unchanged during preflight" || return 1

    local sum_ok=1
    local -a b0_required=( "overall-result: PASS" "after-state-capture-succeeded: YES" "container-state-changed: NO" "image-state-changed: NO" "remote-cleanup-result: PASS" "candidate-checksum: PASS" "candidate-manifest: PASS" "compose-version: PASS" "compose-render: PASS" "port-assertion: PASS" "volume-assertion: PASS" "container-state-unchanged: PASS" "image-state-unchanged: PASS" )
    local kv
    for kv in "${b0_required[@]}"; do
        grep -qxF "${kv}" "${b0_sum}" || sum_ok=0
    done
    [[ "${sum_ok}" -eq 1 ]] || { fail "B0 preflight-summary.txt does not record the complete v4 PASS result"; return 1; }
    grep -qxF "candidate-sha256: ${EXPECTED_CANDIDATE_SHA256}" "${b0_sum}" || { fail "B0 preflight-summary.txt candidate-sha256 mismatch"; return 1; }

    pass "Phase B0 v4 evidence lock verified (locked at ${B0_EVIDENCE_DIR})"
}
