#!/usr/bin/env bash
#
# HADA M1 Phase B — Executable fixture tests for the prohibited-operation
# scanner (correction 2)
#
# The scanner has_prohibited_violation() is sourced from
# scripts/run-phase-b-deploy.sh and executed against fixture files.
#
# It MUST fail (flag) on uncommented commands including:
#   docker system prune
#   docker volume prune
#   docker compose down -v
#   rm -rf /var/lib/hada
#   rm -rf /opt/hada
#   mkfs.ext4 /dev/sdb
#
# It MUST NOT fail merely because the text occurs in comments, documentation
# or explicit refusal messages.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-proh-fix-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found: ${RUNNER}" >&2; exit 1; }

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

expect_flagged() {
    local desc="$1" pattern="$2" fixture="$3"
    if has_prohibited_violation "${fixture}" "${pattern}"; then
        assert_pass "${desc}"
    else
        assert_fail "${desc} (scanner MISSED uncommented '${pattern}')"
    fi
}

expect_clean() {
    local desc="$1" pattern="$2" fixture="$3"
    if has_prohibited_violation "${fixture}" "${pattern}"; then
        assert_fail "${desc} (scanner FALSE-POSITIVE on '${pattern}')"
    else
        assert_pass "${desc}"
    fi
}

# ---------------------------------------------------------------------------
# MUST-FLAG fixtures: uncommented executable destructive commands
# ---------------------------------------------------------------------------

F="${TEMP_DIR}/flag-system-prune.sh"
printf '#!/usr/bin/env bash\nsudo -n docker system prune -f\n' > "${F}"
expect_flagged "flags uncommented 'docker system prune'" "docker system prune" "${F}"

F="${TEMP_DIR}/flag-volume-prune.sh"
printf '#!/usr/bin/env bash\ndocker volume prune -f\n' > "${F}"
expect_flagged "flags uncommented 'docker volume prune'" "docker volume prune" "${F}"

F="${TEMP_DIR}/flag-compose-down-v.sh"
printf '#!/usr/bin/env bash\ncd /opt/hada && docker compose down -v\n' > "${F}"
expect_flagged "flags uncommented 'docker compose down -v'" "docker compose down -v" "${F}"

F="${TEMP_DIR}/flag-rm-varlib.sh"
printf '#!/usr/bin/env bash\nrm -rf /var/lib/hada\n' > "${F}"
expect_flagged "flags uncommented 'rm -rf /var/lib/hada'" "rm -rf /var/lib/hada" "${F}"

F="${TEMP_DIR}/flag-rm-opt.sh"
printf '#!/usr/bin/env bash\nsudo rm -rf /opt/hada\n' > "${F}"
expect_flagged "flags uncommented 'rm -rf /opt/hada'" "rm -rf /opt/hada" "${F}"

# Note: the mkfs.ext4 fixture below is a fixture FILE only; nothing executes it.
F="${TEMP_DIR}/flag-mkfs.sh"
printf '#!/usr/bin/env bash\nmkfs.ext4 /dev/sdb\n' > "${F}"
expect_flagged "flags uncommented 'mkfs.ext4 /dev/sdb'" "mkfs.ext4 /dev/sdb" "${F}"

# Indented uncommented occurrence (still executable)
F="${TEMP_DIR}/flag-indented.sh"
printf '#!/usr/bin/env bash\nif true; then\n  docker system prune -f\nfi\n' > "${F}"
expect_flagged "flags indented uncommented 'docker system prune'" "docker system prune" "${F}"

# ---------------------------------------------------------------------------
# MUST-NOT-FLAG fixtures: comments, documentation, refusal messages
# ---------------------------------------------------------------------------

F="${TEMP_DIR}/clean-comment.sh"
printf '#!/usr/bin/env bash\n# docker system prune is prohibited here\n' > "${F}"
expect_clean "ignores commented 'docker system prune'" "docker system prune" "${F}"

F="${TEMP_DIR}/clean-doc-echo.sh"
printf '#!/usr/bin/env bash\necho "docker volume prune will not be run by this script"\n' > "${F}"
expect_clean "ignores echo documentation of 'docker volume prune'" "docker volume prune" "${F}"

F="${TEMP_DIR}/clean-refusal.sh"
printf '#!/usr/bin/env bash\necho "REFUSED: docker compose down -v is prohibited"\n' > "${F}"
expect_clean "ignores refusal message naming 'docker compose down -v'" "docker compose down -v" "${F}"

F="${TEMP_DIR}/clean-rollback-doc.sh"
printf '#!/usr/bin/env bash\nlog "Rollback never runs docker compose down -v"\n' > "${F}"
expect_clean "ignores log documentation about 'docker compose down -v'" "docker compose down -v" "${F}"

F="${TEMP_DIR}/clean-never.sh"
printf '#!/usr/bin/env bash\nprintf "This runner must not execute mkfs.ext4 /dev/sdb"\n' > "${F}"
expect_clean "ignores prohibition text naming mkfs.ext4 /dev/sdb" "mkfs.ext4 /dev/sdb" "${F}"

F="${TEMP_DIR}/clean-grep-check.sh"
printf '#!/usr/bin/env bash\ngrep -q "rm -rf /var/lib/hada" "$0" && echo FOUND\n' > "${F}"
expect_clean "ignores grep-check for 'rm -rf /var/lib/hada'" "rm -rf /var/lib/hada" "${F}"

F="${TEMP_DIR}/clean-assert-line.sh"
printf '#!/usr/bin/env bash\nassert_line_not_present "rm -rf /opt/hada" "$f"\n' > "${F}"
expect_clean "ignores assert helper naming 'rm -rf /opt/hada'" "rm -rf /opt/hada" "${F}"

# A file that contains ALL patterns only in comments/docs must be fully clean
F="${TEMP_DIR}/clean-all-docs.sh"
{
    printf '#!/usr/bin/env bash\n'
    printf '# docker system prune: never run\n'
    printf '# docker volume prune: never run\n'
    printf '# docker compose down -v: never run\n'
    printf '# rm -rf /var/lib/hada: never run\n'
    printf '# rm -rf /opt/hada: never run\n'
    printf '# mkfs.ext4 /dev/sdb: never run\n'
    printf 'echo "REFUSED: destructive operations are prohibited"\n'
} > "${F}"
ok=1
for pat in "docker system prune" "docker volume prune" "docker compose down -v" "rm -rf /var/lib/hada" "rm -rf /opt/hada" "mkfs.ext4 /dev/sdb"; do
    if has_prohibited_violation "${F}" "${pat}"; then ok=0; break; fi
done
if [[ ${ok} -eq 1 ]]; then
    assert_pass "comment/documentation-only file with all six patterns is fully clean"
else
    assert_fail "comment/documentation-only file incorrectly flagged for '${pat}'"
fi

# ---------------------------------------------------------------------------
# Production scripts must be clean (scan the actual deployment scripts)
# ---------------------------------------------------------------------------
PROD_CLEAN=1
for s in "${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh" \
         "${DEPLOY_ROOT}/scripts/provision-secrets.sh" \
         "${DEPLOY_ROOT}/scripts/supervisor.gcp.sh" \
         "${DEPLOY_ROOT}/scripts/validate-host.gcp.sh" \
         "${DEPLOY_ROOT}/scripts/run-phase-b0-v4-preflight.sh"; do
    [[ -f "$s" ]] || { assert_fail "production script missing: $s"; PROD_CLEAN=0; continue; }
    for pat in "docker system prune" "docker volume prune" "docker container prune" \
               "docker compose down -v" "docker compose down --volumes" \
               "rm -rf /var/lib/hada" "rm -rf /opt/hada" "mkfs.ext4 /dev/sdb" "mkfs.ext4 /dev/sda"; do
        if has_prohibited_violation "$s" "${pat}"; then
            assert_fail "production script $(basename "$s") contains uncommented prohibited pattern"
            PROD_CLEAN=0
        fi
    done
done
if [[ ${PROD_CLEAN} -eq 1 ]]; then
    assert_pass "all production scripts are free of uncommented prohibited operations"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Prohibited-operation scanner fixture results"
echo "============================================"
echo "Passed: ${PASS_COUNT}"
echo "Failed: ${FAIL_COUNT}"
echo ""
if [[ ${FAIL_COUNT} -gt 0 ]]; then
    echo "RESULT: FAIL"
    exit 1
fi
echo "RESULT: PASS"
exit 0
