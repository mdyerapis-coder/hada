#!/usr/bin/env bash
#
# HADA M1 Phase B — .env validation tests (correction 7)
#
# Exercises env_validate_file() from scripts/run-phase-b-deploy.sh against
# fixture .env files. Proves rejection of:
#   - empty secret values
#   - CHANGE_ME
#   - ***
#   - synthetic values
#   - known example/test secrets
# and DSN/URL <-> password consistency verification, all WITHOUT printing
# any secret value (the validator reports key names only).
#
# All fixture secrets below are test-only strings generated for this test;
# none are real credentials and none are printed by the validator.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-env-test-XXXXXX)"
chmod 0700 "${TEMP_DIR}"
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

# Test-only pseudo-secrets (hex, like provision-secrets.sh would generate)
PG_OK="f3a91c0d2b8e4a6c9d1f0b3a5c7e9d2f4a6b8c0d2e4f6a8b0c1d3e5f7a9b1c3d"
VK_OK="0b2d4f6a8c0e2f4a6c8e0a2c4e6f8a0b1c3d5e7f9a1b3c5d7e9f0a2b4c6d8e0f"
GF_OK="9e7c5a3b1d0f2e4c6a8b0d2f4e6a8c0b3d5f7a9c1e3b5d7f9a0c2e4b6d8f0a1c"

write_env() {
    # write_env FILE PG VK GF DSN VURL
    local f="$1" pg="$2" vk="$3" gf="$4" dsn="$5" vurl="$6"
    cat > "$f" <<EOF
HADA_ENV=production
POSTGRES_DB=hada
POSTGRES_USER=hada
POSTGRES_PASSWORD=${pg}
VALKEY_PASSWORD=${vk}
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${gf}
HADA_DATABASE_DSN=${dsn}
HADA_VALKEY_URL=${vurl}
EOF
    chmod 0600 "$f"
}

expect_reject() {
    local desc="$1" f="$2"
    local out rc
    set +e
    out="$(env_validate_file "$f" 2>&1)"
    rc=$?
    set -e
    if [[ ${rc} -ne 0 ]]; then
        assert_pass "${desc}"
    else
        assert_fail "${desc} (validator accepted a bad .env)"
    fi
    # The validator must never print a secret value
    local secret
    for secret in "${PG_OK}" "${VK_OK}" "${GF_OK}"; do
        if [[ -n "${secret}" && "${out}" == *"${secret}"* ]]; then
            assert_fail "${desc}: validator output leaked a secret value"
        fi
    done
}

expect_accept() {
    local desc="$1" f="$2"
    local out rc
    set +e
    out="$(env_validate_file "$f" 2>&1)"
    rc=$?
    set -e
    if [[ ${rc} -eq 0 ]]; then
        assert_pass "${desc}"
    else
        assert_fail "${desc} (validator rejected a good .env: ${out})"
    fi
    local secret
    for secret in "${PG_OK}" "${VK_OK}" "${GF_OK}"; do
        if [[ "${out}" == *"${secret}"* ]]; then
            assert_fail "${desc}: validator output leaked a secret value"
        fi
    done
}

# ---------------------------------------------------------------------------
# 1: fully consistent .env is accepted
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/good.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_accept "consistent .env with strong distinct secrets is accepted" "$F"

# ---------------------------------------------------------------------------
# 2: empty secret value rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/empty-pg.env"
write_env "$F" "" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "empty POSTGRES_PASSWORD rejected" "$F"

F="${TEMP_DIR}/empty-vk.env"
write_env "$F" "${PG_OK}" "" "${GF_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:@valkey:6379/0"
expect_reject "empty VALKEY_PASSWORD rejected" "$F"

# ---------------------------------------------------------------------------
# 3: CHANGE_ME rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/changeme.env"
write_env "$F" "CHANGE_ME" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:CHANGE_ME@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "CHANGE_ME value rejected" "$F"

F="${TEMP_DIR}/changeme-embedded.env"
write_env "$F" "abcCHANGE_MExyz" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:abcCHANGE_MExyz@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "embedded CHANGE_ME substring rejected" "$F"

# ---------------------------------------------------------------------------
# 4: *** rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/stars.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:***@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "*** redaction placeholder in DSN rejected" "$F"

F="${TEMP_DIR}/stars-pw.env"
write_env "$F" "***" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:***@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "*** as password rejected" "$F"

# ---------------------------------------------------------------------------
# 5: synthetic values rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/synth.env"
write_env "$F" "CHANGE_ME_SYNTHETIC" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:CHANGE_ME_SYNTHETIC@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "synthetic placeholder value rejected" "$F"

F="${TEMP_DIR}/synth2.env"
write_env "$F" "${PG_OK}" "my-synthetic-password" "${GF_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:my-synthetic-password@valkey:6379/0"
expect_reject "embedded 'synthetic' substring rejected" "$F"

# ---------------------------------------------------------------------------
# 6: known example/test secrets rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/testsecret.env"
write_env "$F" "actual-test-secret" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:actual-test-secret@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "known test secret 'actual-test-secret' rejected" "$F"

F="${TEMP_DIR}/example.env"
write_env "$F" "${PG_OK}" "example-secret" "${GF_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:example-secret@valkey:6379/0"
expect_reject "known example secret 'example-secret' rejected" "$F"

# ---------------------------------------------------------------------------
# 7: DSN password inconsistent with POSTGRES_PASSWORD rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/dsn-mismatch.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:${VK_OK}@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "DSN carrying the wrong password rejected (inconsistent with POSTGRES_PASSWORD)" "$F"

# ---------------------------------------------------------------------------
# 8: Valkey URL password inconsistent with VALKEY_PASSWORD rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/vurl-mismatch.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:${PG_OK}@valkey:6379/0"
expect_reject "Valkey URL carrying the wrong password rejected (inconsistent with VALKEY_PASSWORD)" "$F"

# ---------------------------------------------------------------------------
# 9: malformed DSN / URL schemes rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/bad-dsn.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${GF_OK}" \
    "mysql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "non-postgresql DSN scheme rejected" "$F"

F="${TEMP_DIR}/bad-vurl.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${GF_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "http://:${VK_OK}@valkey:6379/0"
expect_reject "non-redis Valkey URL scheme rejected" "$F"

# ---------------------------------------------------------------------------
# 10: missing key rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/missing-key.env"
cat > "$F" <<EOF
POSTGRES_PASSWORD=${PG_OK}
VALKEY_PASSWORD=${VK_OK}
HADA_DATABASE_DSN=postgresql://hada:${PG_OK}@postgres:5432/hada
HADA_VALKEY_URL=redis://:${VK_OK}@valkey:6379/0
EOF
chmod 0600 "$F"
expect_reject "missing GRAFANA_ADMIN_PASSWORD rejected" "$F"

# ---------------------------------------------------------------------------
# 11: secret reuse (grafana == postgres) rejected
# ---------------------------------------------------------------------------
F="${TEMP_DIR}/reuse.env"
write_env "$F" "${PG_OK}" "${VK_OK}" "${PG_OK}" \
    "postgresql://hada:${PG_OK}@postgres:5432/hada" \
    "redis://:${VK_OK}@valkey:6379/0"
expect_reject "GRAFANA_ADMIN_PASSWORD reusing POSTGRES_PASSWORD rejected" "$F"

# ---------------------------------------------------------------------------
# 12: remote Gate-4 validator block never echoes a secret value
#     (static assertion on the runner's generated remote script)
# ---------------------------------------------------------------------------
GATE4_BLOCK="$(sed -n '/GATE 4: Validate Production .env/,/GATE 4: PASSED/p' "${RUNNER}")"
if grep -E 'echo .*\$\{?(v|pg|vp|gp|dsn|vurl)\}?' <<<"${GATE4_BLOCK}" | grep -vE 'FAIL:|PASS:' | grep -q .; then
    assert_fail "Gate 4 remote block echoes a variable that may hold a secret"
else
    assert_pass "Gate 4 remote block never echoes secret-bearing variables"
fi
if grep -q 'forbidden value detected for' "${RUNNER}"; then
    assert_pass "Gate 4 failure messages report key names only"
else
    assert_fail "Gate 4 failure messages missing name-only reporting"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo ".env validation test results"
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
