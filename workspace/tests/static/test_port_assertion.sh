#!/usr/bin/env bash
#
# HADA M1 Phase B0 — Static assertions for the port-assertion Python program
#
# Proves:
#   - the exact port-assertion Python embedded in run-phase-b0-preflight.sh
#     parses and runs against valid sample Compose JSON
#   - valid JSON with caddy 127.0.0.1:80:80/tcp and no 443 returns zero
#   - invalid JSON containing published or target port 443 returns nonzero
#   - the runner no longer embeds broken pp[\"...\"] f-string expressions
#
# Does not contact hada-control.
#
set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNNER="${ROOT}/scripts/run-phase-b0-v4-preflight.sh"

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

if [[ ! -f "${RUNNER}" ]]; then
  echo "FAIL: runner not found: ${RUNNER}" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Extract the first python3 -c '...' port-assertion program from the runner
# ---------------------------------------------------------------------------

EXTRACT_PY="${TEMP_DIR}/extract_port_prog.py"
cat > "${EXTRACT_PY}" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text()
# Locate the port-assertion block by unique marker, then take its python3 -c body
marker = "Validating published ports"
idx = text.find(marker)
if idx < 0:
    sys.stderr.write("marker not found\n")
    sys.exit(2)
chunk = text[idx:]
m = re.search(r"python3 -c '([\s\S]*?)'\s*2>&1\s*\|\s*tee", chunk)
if not m:
    sys.stderr.write("python3 -c block not found after marker\n")
    sys.exit(3)
prog = m.group(1)
# The shell source stores double quotes as plain " inside the single-quoted
# -c argument. Write the program as Python sees it.
sys.stdout.write(prog)
PY

PORT_PROG="${TEMP_DIR}/port_assertion_prog.py"
if ! python3 "${EXTRACT_PY}" "${RUNNER}" > "${PORT_PROG}"; then
  assert_fail "extract port-assertion Python from runner"
  echo "RESULT: FAIL"
  exit 1
fi
assert_pass "extracted port-assertion Python from runner"

# ---------------------------------------------------------------------------
# The extracted program must parse
# ---------------------------------------------------------------------------

if python3 -m py_compile "${PORT_PROG}" 2>"${TEMP_DIR}/compile.err"; then
  assert_pass "exact port-assertion Python program parses (py_compile)"
else
  assert_fail "port-assertion Python does not parse: $(cat "${TEMP_DIR}/compile.err")"
fi

# Guard: no broken escaped dict keys inside f-strings in the runner source
if grep -E 'pp\[\\"|p2\[\\"' "${RUNNER}" >/dev/null 2>&1; then
  assert_fail "runner still contains escaped dict-key expressions in f-strings"
else
  assert_pass "runner has no escaped dict-key expressions in f-strings"
fi

# ---------------------------------------------------------------------------
# Valid JSON: caddy 127.0.0.1:80:80/tcp, no 443 -> rc 0
# (published as string, matching real docker compose config --format json)
# ---------------------------------------------------------------------------

VALID_JSON="${TEMP_DIR}/valid.json"
cat > "${VALID_JSON}" <<'JSON'
{
  "services": {
    "caddy": {
      "ports": [
        {
          "mode": "ingress",
          "host_ip": "127.0.0.1",
          "target": 80,
          "published": "80",
          "protocol": "tcp"
        }
      ]
    },
    "postgres": {
      "ports": []
    }
  }
}
JSON

set +e
python3 "${PORT_PROG}" < "${VALID_JSON}" >"${TEMP_DIR}/valid.out" 2>"${TEMP_DIR}/valid.err"
VALID_RC=$?
set -e

if [[ "${VALID_RC}" -eq 0 ]] && grep -q 'PASS: exactly one published port' "${TEMP_DIR}/valid.out"; then
  assert_pass "valid JSON caddy 127.0.0.1:80:80/tcp no 443 returns zero"
else
  assert_fail "valid JSON should return 0 (rc=${VALID_RC}, out=$(cat "${TEMP_DIR}/valid.out"), err=$(cat "${TEMP_DIR}/valid.err"))"
fi

# Also accept integer published=80
VALID_JSON_INT="${TEMP_DIR}/valid-int.json"
cat > "${VALID_JSON_INT}" <<'JSON'
{
  "services": {
    "caddy": {
      "ports": [
        {
          "host_ip": "127.0.0.1",
          "target": 80,
          "published": 80,
          "protocol": "tcp"
        }
      ]
    }
  }
}
JSON

set +e
python3 "${PORT_PROG}" < "${VALID_JSON_INT}" >"${TEMP_DIR}/valid-int.out" 2>"${TEMP_DIR}/valid-int.err"
VALID_INT_RC=$?
set -e

if [[ "${VALID_INT_RC}" -eq 0 ]]; then
  assert_pass "valid JSON with integer published=80 returns zero"
else
  assert_fail "integer published=80 should return 0 (rc=${VALID_INT_RC})"
fi

# ---------------------------------------------------------------------------
# Invalid JSON: published port 443 -> nonzero
# ---------------------------------------------------------------------------

BAD_PUB_JSON="${TEMP_DIR}/bad-published-443.json"
cat > "${BAD_PUB_JSON}" <<'JSON'
{
  "services": {
    "caddy": {
      "ports": [
        {
          "host_ip": "127.0.0.1",
          "target": 80,
          "published": "80",
          "protocol": "tcp"
        },
        {
          "host_ip": "0.0.0.0",
          "target": 443,
          "published": "443",
          "protocol": "tcp"
        }
      ]
    }
  }
}
JSON

set +e
python3 "${PORT_PROG}" < "${BAD_PUB_JSON}" >"${TEMP_DIR}/bad-pub.out" 2>"${TEMP_DIR}/bad-pub.err"
BAD_PUB_RC=$?
set -e

if [[ "${BAD_PUB_RC}" -ne 0 ]] && grep -q 'port 443' "${TEMP_DIR}/bad-pub.out"; then
  assert_pass "invalid JSON with published port 443 returns nonzero"
else
  assert_fail "published 443 should fail (rc=${BAD_PUB_RC}, out=$(cat "${TEMP_DIR}/bad-pub.out"))"
fi

# ---------------------------------------------------------------------------
# Invalid JSON: target port 443 only -> nonzero
# ---------------------------------------------------------------------------

BAD_TGT_JSON="${TEMP_DIR}/bad-target-443.json"
cat > "${BAD_TGT_JSON}" <<'JSON'
{
  "services": {
    "caddy": {
      "ports": [
        {
          "host_ip": "127.0.0.1",
          "target": 443,
          "published": "8443",
          "protocol": "tcp"
        }
      ]
    }
  }
}
JSON

set +e
python3 "${PORT_PROG}" < "${BAD_TGT_JSON}" >"${TEMP_DIR}/bad-tgt.out" 2>"${TEMP_DIR}/bad-tgt.err"
BAD_TGT_RC=$?
set -e

if [[ "${BAD_TGT_RC}" -ne 0 ]] && grep -q '443' "${TEMP_DIR}/bad-tgt.out"; then
  assert_pass "invalid JSON with target port 443 returns nonzero"
else
  assert_fail "target 443 should fail (rc=${BAD_TGT_RC}, out=$(cat "${TEMP_DIR}/bad-tgt.out"))"
fi

# ---------------------------------------------------------------------------
# Real effective-compose.json from prior preflight render (if present)
# ---------------------------------------------------------------------------

REAL_JSON="${ROOT}/evidence/phase-b0/preflight-run-20260725170700/effective-compose.json"
if [[ -f "${REAL_JSON}" ]]; then
  set +e
  python3 "${PORT_PROG}" < "${REAL_JSON}" >"${TEMP_DIR}/real.out" 2>"${TEMP_DIR}/real.err"
  REAL_RC=$?
  set -e
  if [[ "${REAL_RC}" -eq 0 ]]; then
    assert_pass "prior preflight effective-compose.json passes port assertion"
  else
    assert_fail "prior effective-compose.json should pass (rc=${REAL_RC}, out=$(cat "${TEMP_DIR}/real.out"))"
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "============================================"
echo "Static port-assertion results"
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
