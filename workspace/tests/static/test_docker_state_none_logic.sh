#!/usr/bin/env bash
#
# HADA M1 Phase B0 — Static assertions for Docker state capture logic
#
# Proves the remote capture commands used in run-phase-b0-preflight.sh:
#   - successful empty sudo Docker output becomes NONE
#   - successful non-empty container output is sorted
#   - successful non-empty image output is sorted and unique
#   - a mocked Docker command failure returns nonzero
#   - a mocked sudo failure returns nonzero
#   - failed commands do not output NONE
#   - identical NONE files compare successfully
#   - differing states fail closed
#
# Does not contact hada-control.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() {
  local desc="$1"
  printf 'PASS: %s\n' "${desc}"
  PASS_COUNT=$((PASS_COUNT + 1))
}

assert_fail() {
  local desc="$1"
  printf 'FAIL: %s\n' "${desc}" >&2
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

# Exact remote capture logic from run-phase-b0-preflight.sh (containers)
capture_containers() {
  raw="$(sudo -n docker ps -aq)" || {
    rc=$?
    echo "FAIL: sudo -n docker ps -aq failed with rc=${rc}" >&2
    return "${rc}"
  }
  if [[ -n "${raw}" ]]; then
    printf '%s\n' "${raw}" | sort
  else
    printf 'NONE\n'
  fi
}

# Exact remote capture logic from run-phase-b0-preflight.sh (images)
capture_images() {
  raw="$(sudo -n docker images -q)" || {
    rc=$?
    echo "FAIL: sudo -n docker images -q failed with rc=${rc}" >&2
    return "${rc}"
  }
  if [[ -n "${raw}" ]]; then
    printf '%s\n' "${raw}" | sort -u
  else
    printf 'NONE\n'
  fi
}

install_mock_sudo_passthrough() {
  local bin_dir="$1"
  cat > "${bin_dir}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1-}" == "-n" ]]; then
  shift
fi
if [[ "$#" -eq 0 ]]; then
  echo "sudo: missing command" >&2
  exit 1
fi
exec "$@"
EOF
  chmod +x "${bin_dir}/sudo"
}

# ---------------------------------------------------------------------------
# Test 1: successful empty sudo Docker container output becomes NONE
# ---------------------------------------------------------------------------

MOCK1="${TEMP_DIR}/mock1"
mkdir -p "${MOCK1}"
install_mock_sudo_passthrough "${MOCK1}"
cat > "${MOCK1}/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "ps" && "$2" == "-aq" ]]; then
  exit 0
fi
echo "unexpected docker args: $*" >&2
exit 99
EOF
chmod +x "${MOCK1}/docker"

OUT1="${TEMP_DIR}/empty-ps.txt"
set +e
PATH="${MOCK1}:${PATH}" capture_containers >"${OUT1}" 2>"${TEMP_DIR}/empty-ps.err"
RC1=$?
set -e

if [[ "${RC1}" -eq 0 && "$(cat "${OUT1}")" == "NONE" ]]; then
  assert_pass "successful empty sudo Docker container output becomes NONE"
else
  assert_fail "empty container output -> NONE (rc=${RC1}, out=$(cat "${OUT1}"), err=$(cat "${TEMP_DIR}/empty-ps.err"))"
fi

# ---------------------------------------------------------------------------
# Test 2: successful empty sudo Docker image output becomes NONE
# ---------------------------------------------------------------------------

MOCK2="${TEMP_DIR}/mock2"
mkdir -p "${MOCK2}"
install_mock_sudo_passthrough "${MOCK2}"
cat > "${MOCK2}/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "images" && "$2" == "-q" ]]; then
  exit 0
fi
echo "unexpected docker args: $*" >&2
exit 99
EOF
chmod +x "${MOCK2}/docker"

OUT2="${TEMP_DIR}/empty-images.txt"
set +e
PATH="${MOCK2}:${PATH}" capture_images >"${OUT2}" 2>"${TEMP_DIR}/empty-images.err"
RC2=$?
set -e

if [[ "${RC2}" -eq 0 && "$(cat "${OUT2}")" == "NONE" ]]; then
  assert_pass "successful empty sudo Docker image output becomes NONE"
else
  assert_fail "empty image output -> NONE (rc=${RC2}, out=$(cat "${OUT2}"))"
fi

# ---------------------------------------------------------------------------
# Test 3: successful non-empty container output is sorted
# ---------------------------------------------------------------------------

MOCK3="${TEMP_DIR}/mock3"
mkdir -p "${MOCK3}"
install_mock_sudo_passthrough "${MOCK3}"
cat > "${MOCK3}/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "ps" && "$2" == "-aq" ]]; then
  printf '%s\n' 'def456' 'abc123' 'ghi789'
  exit 0
fi
exit 99
EOF
chmod +x "${MOCK3}/docker"

OUT3="${TEMP_DIR}/nonempty-ps.txt"
set +e
PATH="${MOCK3}:${PATH}" capture_containers >"${OUT3}" 2>"${TEMP_DIR}/nonempty-ps.err"
RC3=$?
set -e

EXPECTED_SORTED=$'abc123\ndef456\nghi789'
if [[ "${RC3}" -eq 0 && "$(cat "${OUT3}")" == "${EXPECTED_SORTED}" ]]; then
  assert_pass "successful non-empty container output is sorted"
else
  assert_fail "non-empty container sort (rc=${RC3}, out=$(cat "${OUT3}"))"
fi

# ---------------------------------------------------------------------------
# Test 4: successful non-empty image output is sorted and unique
# ---------------------------------------------------------------------------

MOCK4="${TEMP_DIR}/mock4"
mkdir -p "${MOCK4}"
install_mock_sudo_passthrough "${MOCK4}"
cat > "${MOCK4}/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "images" && "$2" == "-q" ]]; then
  printf '%s\n' 'img_bbb' 'img_aaa' 'img_bbb' 'img_ccc'
  exit 0
fi
exit 99
EOF
chmod +x "${MOCK4}/docker"

OUT4="${TEMP_DIR}/nonempty-images.txt"
set +e
PATH="${MOCK4}:${PATH}" capture_images >"${OUT4}" 2>"${TEMP_DIR}/nonempty-images.err"
RC4=$?
set -e

EXPECTED_SORTED_UNIQUE=$'img_aaa\nimg_bbb\nimg_ccc'
if [[ "${RC4}" -eq 0 && "$(cat "${OUT4}")" == "${EXPECTED_SORTED_UNIQUE}" ]]; then
  assert_pass "successful non-empty image output is sorted and unique"
else
  assert_fail "non-empty image sort -u (rc=${RC4}, out=$(cat "${OUT4}"))"
fi

# ---------------------------------------------------------------------------
# Test 5: mocked Docker command failure returns nonzero
# ---------------------------------------------------------------------------

MOCK5="${TEMP_DIR}/mock5"
mkdir -p "${MOCK5}"
install_mock_sudo_passthrough "${MOCK5}"
cat > "${MOCK5}/docker" <<'EOF'
#!/usr/bin/env bash
echo "permission denied while trying to connect to the docker API" >&2
exit 1
EOF
chmod +x "${MOCK5}/docker"

OUT5="${TEMP_DIR}/docker-fail.txt"
ERR5="${TEMP_DIR}/docker-fail.err"
set +e
PATH="${MOCK5}:${PATH}" capture_containers >"${OUT5}" 2>"${ERR5}"
RC5=$?
set -e

if [[ "${RC5}" -ne 0 ]]; then
  assert_pass "mocked Docker command failure returns nonzero (rc=${RC5})"
else
  assert_fail "mocked Docker failure should return nonzero"
fi

# ---------------------------------------------------------------------------
# Test 6: mocked sudo failure returns nonzero
# ---------------------------------------------------------------------------

MOCK6="${TEMP_DIR}/mock6"
mkdir -p "${MOCK6}"
cat > "${MOCK6}/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo: a password is required" >&2
exit 1
EOF
chmod +x "${MOCK6}/sudo"
# docker should not be reached
cat > "${MOCK6}/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker should not run" >&2
exit 0
EOF
chmod +x "${MOCK6}/docker"

OUT6="${TEMP_DIR}/sudo-fail.txt"
ERR6="${TEMP_DIR}/sudo-fail.err"
set +e
PATH="${MOCK6}:${PATH}" capture_images >"${OUT6}" 2>"${ERR6}"
RC6=$?
set -e

if [[ "${RC6}" -ne 0 ]]; then
  assert_pass "mocked sudo failure returns nonzero (rc=${RC6})"
else
  assert_fail "mocked sudo failure should return nonzero"
fi

# ---------------------------------------------------------------------------
# Test 7: failed commands do not output NONE
# ---------------------------------------------------------------------------

if grep -q 'NONE' "${OUT5}" 2>/dev/null; then
  assert_fail "failed Docker command must not output NONE (got: $(cat "${OUT5}"))"
else
  assert_pass "failed Docker command does not output NONE"
fi

if grep -q 'NONE' "${OUT6}" 2>/dev/null; then
  assert_fail "failed sudo command must not output NONE (got: $(cat "${OUT6}"))"
else
  assert_pass "failed sudo command does not output NONE"
fi

if ! grep -q 'FAIL: sudo -n docker' "${ERR5}" && ! grep -q 'FAIL: sudo -n docker' "${ERR6}"; then
  assert_fail "failure path should emit FAIL diagnostic on stderr"
else
  assert_pass "failure path emits FAIL diagnostic on stderr"
fi

# ---------------------------------------------------------------------------
# Test 8: Identical NONE files compare successfully (no diff)
# ---------------------------------------------------------------------------

BEFORE_FILE="${TEMP_DIR}/none-before.txt"
AFTER_FILE="${TEMP_DIR}/none-after.txt"
printf 'NONE\n' > "${BEFORE_FILE}"
printf 'NONE\n' > "${AFTER_FILE}"

if diff "${BEFORE_FILE}" "${AFTER_FILE}" > /dev/null 2>&1; then
  assert_pass "identical NONE files compare successfully"
else
  assert_fail "identical NONE files should compare as equal"
fi

# ---------------------------------------------------------------------------
# Test 9: Differing states fail closed (NONE before vs IDs after)
# ---------------------------------------------------------------------------

BEFORE_FILE="${TEMP_DIR}/diff-before.txt"
AFTER_FILE="${TEMP_DIR}/diff-after.txt"
printf 'NONE\n' > "${BEFORE_FILE}"
printf 'abc123\ndef456\n' > "${AFTER_FILE}"

if diff "${BEFORE_FILE}" "${AFTER_FILE}" > /dev/null 2>&1; then
  assert_fail "differing states (NONE before vs IDs after) should fail closed"
else
  assert_pass "differing states (NONE before vs IDs after) fail closed"
fi

# ---------------------------------------------------------------------------
# Test 10: Differing container IDs fail closed
# ---------------------------------------------------------------------------

BEFORE_FILE="${TEMP_DIR}/diff-ids-before.txt"
AFTER_FILE="${TEMP_DIR}/diff-ids-after.txt"
printf 'abc123\ndef456\n' > "${BEFORE_FILE}"
printf 'abc123\nxyz999\n' > "${AFTER_FILE}"

if diff "${BEFORE_FILE}" "${AFTER_FILE}" > /dev/null 2>&1; then
  assert_fail "differing container IDs should fail closed"
else
  assert_pass "differing container IDs fail closed"
fi

# ---------------------------------------------------------------------------
# Test 11: runner embeds sudo -n and no pipeline-inside-$(...) for captures
# ---------------------------------------------------------------------------

RUNNER="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/run-phase-b0-v4-preflight.sh"
if [[ ! -f "${RUNNER}" ]]; then
  assert_fail "runner not found: ${RUNNER}"
else
  # Four captures: ps before/after + images before/after
  SUDO_PS_COUNT="$(grep -c 'sudo -n docker ps -aq' "${RUNNER}" || true)"
  SUDO_IMG_COUNT="$(grep -c 'sudo -n docker images -q' "${RUNNER}" || true)"
  BAD_PIPE_PS="$(grep -c 'docker ps -aq | sort' "${RUNNER}" || true)"
  BAD_PIPE_IMG="$(grep -c 'docker images -q | sort' "${RUNNER}" || true)"

  if [[ "${SUDO_PS_COUNT}" -ge 2 && "${SUDO_IMG_COUNT}" -ge 2 ]]; then
    assert_pass "runner uses sudo -n for container and image captures"
  else
    assert_fail "runner missing sudo -n captures (ps=${SUDO_PS_COUNT}, img=${SUDO_IMG_COUNT})"
  fi

  if [[ "${BAD_PIPE_PS}" -eq 0 && "${BAD_PIPE_IMG}" -eq 0 ]]; then
    assert_pass "runner has no pipeline inside docker state command substitution"
  else
    assert_fail "runner still pipelines inside docker state \$(...) (ps=${BAD_PIPE_PS}, img=${BAD_PIPE_IMG})"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "============================================"
echo "Static Docker-state assertion results"
echo "============================================"
echo "Passed: ${PASS_COUNT}"
echo "Failed: ${FAIL_COUNT}"
echo ""

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  echo "RESULT: FAIL"
  exit 1
else
  echo "RESULT: PASS"
  exit 0
fi
