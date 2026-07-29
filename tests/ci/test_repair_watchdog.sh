#!/usr/bin/env bash
# Hermetic tests for repair_watchdog.sh — no GitHub or network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WATCHDOG="$ROOT/scripts/ci/repair_watchdog.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
SCANNER="$TMP/scanner"
STATE="$TMP/state"
COUNT="$TMP/count"
HEALTH="$TMP/health"
cat >"$HEALTH" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$HEALTH"

fail=0
check() {
  local description="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    printf 'PASS: %s\n' "$description"
  else
    printf 'FAIL: %s (expected %q, got %q)\n' "$description" "$expected" "$actual" >&2
    fail=$((fail + 1))
  fi
}

write_scanner() {
  local mode="$1"
  cat >"$SCANNER" <<EOF
#!/usr/bin/env bash
n=0
[[ -f "$COUNT" ]] && n=\$(cat "$COUNT")
n=\$((n + 1)); printf '%s' "\$n" >"$COUNT"
case "$mode" in
  healthy) echo 'No open PRs.'; exit 0 ;;
  transient_then_ok)
    if (( n < 2 )); then echo 'HTTP 429: rate limit'; exit 1; fi
    echo 'No open PRs.'; exit 0 ;;
  persistent) echo 'HTTP 503: unavailable'; exit 1 ;;
  auth) echo 'unauthorized: token expired'; exit 1 ;;
  finding) echo 'scan complete: 1 failing PR(s) diagnosed'; exit 0 ;;
esac
EOF
  chmod +x "$SCANNER"
  rm -f "$COUNT"
}

run_watchdog() {
  HADA_REPAIR_SCANNER="$SCANNER" \
  HADA_REPAIR_HEALTHCHECK="$HEALTH" \
  HADA_REPAIR_STATE_DIR="$STATE" \
  HADA_REPAIR_MAX_ATTEMPTS=3 \
  HADA_REPAIR_BACKOFF_SECONDS="0 0" \
    "$WATCHDOG" 2>&1
}

write_scanner healthy
out=$(run_watchdog)
check "healthy scan is silent" "" "$out"
check "healthy state persisted" "healthy" "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$STATE/health.json")"

write_scanner transient_then_ok
out=$(run_watchdog)
check "transient error retries exactly once" "2" "$(cat "$COUNT")"
check "transient recovery remains silent without prior failed run" "" "$out"

write_scanner persistent
set +e
out=$(run_watchdog); rc=$?
set -e
check "persistent failure exits non-zero" "1" "$rc"
grep -q 'consecutive failures=1' <<<"$out" || { echo 'FAIL: persistent alert lacks failure count' >&2; fail=$((fail + 1)); }
check "failure state persisted" "1" "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["consecutive_failures"])' "$STATE/health.json")"

write_scanner healthy
out=$(run_watchdog)
grep -q 'RECOVERED after 1 consecutive failure' <<<"$out" || { echo 'FAIL: recovery message missing' >&2; fail=$((fail + 1)); }

write_scanner auth
set +e
out=$(run_watchdog); rc=$?
set -e
grep -q 'Human input required' <<<"$out" || { echo 'FAIL: auth failure did not request human input' >&2; fail=$((fail + 1)); }

write_scanner healthy
cat >"$HEALTH" <<'EOF'
#!/usr/bin/env bash
echo 'pytest: 2 failed, 300 passed'
exit 1
EOF
chmod +x "$HEALTH"
set +e
out=$(run_watchdog); rc=$?
set -e
check "main regression exits non-zero" "1" "$rc"
grep -q 'MAIN HEALTHCHECK FAILED' <<<"$out" || { echo 'FAIL: main regression was not classified' >&2; fail=$((fail + 1)); }

cat >"$HEALTH" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$HEALTH"
write_scanner finding
out=$(run_watchdog)
grep -q '1 failing PR' <<<"$out" || { echo 'FAIL: interesting scan result suppressed' >&2; fail=$((fail + 1)); }

printf '%s\n' '----'
printf 'repair-watchdog tests: %s failure(s)\n' "$fail"
(( fail == 0 ))
