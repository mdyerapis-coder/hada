#!/usr/bin/env bash
# repair_watchdog.sh — deterministic self-healing supervisor for HADA repair.
#
# Removes the read-only scan from the LLM failure domain. It validates the
# repair harness, serialises executions, retries transient failures, persists
# health, stays silent when healthy, and emits actionable recovery/incident
# messages for delivery to Hermes Instance Control.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCANNER="${HADA_REPAIR_SCANNER:-$ROOT/scripts/ci/autonomous_repair.sh}"
HEALTHCHECK="${HADA_REPAIR_HEALTHCHECK:-}"
REPO="${HADA_REPAIR_REPO:-mdyerapis-coder/hada}"
LIMIT="${HADA_REPAIR_LIMIT:-10}"
STATE_DIR="${HADA_REPAIR_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/hada-repair}"
STATE_FILE="$STATE_DIR/health.json"
LOCK_FILE="$STATE_DIR/watchdog.lock"
MAX_ATTEMPTS="${HADA_REPAIR_MAX_ATTEMPTS:-3}"
BACKOFF_SECONDS="${HADA_REPAIR_BACKOFF_SECONDS:-5 15}"

mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  # Another watchdog owns the repair scan. This is healthy contention.
  exit 0
fi

for cmd in flock python3; do
  command -v "$cmd" >/dev/null 2>&1 || {
    printf 'HADA repair watchdog ALERT: required command missing: %s\nHuman input required to install it.\n' "$cmd"
    exit 1
  }
done
[[ -f "$SCANNER" && -r "$SCANNER" ]] || {
  printf 'HADA repair watchdog ALERT: scanner is missing or unreadable: %s\n' "$SCANNER"
  exit 1
}

# Shell syntax is the cheapest integrity probe for the production scanner.
if [[ "$SCANNER" == "$ROOT/"* ]] && ! bash -n "$SCANNER"; then
  printf 'HADA repair watchdog ALERT: scanner failed shell syntax validation: %s\n' "$SCANNER"
  exit 1
fi

read_state() {
  python3 - "$STATE_FILE" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    d = json.loads(p.read_text())
except Exception:
    d = {}
print(int(d.get("consecutive_failures", 0)))
PY
}

write_state() {
  local status="$1" failures="$2" detail="$3"
  python3 - "$STATE_FILE" "$status" "$failures" "$detail" <<'PY'
import datetime, json, os, pathlib, sys, tempfile
path = pathlib.Path(sys.argv[1])
status, failures, detail = sys.argv[2], int(sys.argv[3]), sys.argv[4]
data = {
    "status": status,
    "consecutive_failures": failures,
    "last_detail": detail[:2000],
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
path.parent.mkdir(parents=True, exist_ok=True)
fd, tmp = tempfile.mkstemp(prefix="health-", suffix=".json", dir=path.parent)
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)
PY
}

is_transient() {
  grep -qiE 'HTTP (429|5[0-9][0-9])|rate limit|timed? out|timeout|temporar|connection reset|could not resolve|network is unreachable|TLS|EOF' <<<"$1"
}

run_scanner() {
  if [[ -x "$SCANNER" ]]; then
    "$SCANNER" --scan --repo "$REPO" --limit "$LIMIT"
  else
    bash "$SCANNER" --scan --repo "$REPO" --limit "$LIMIT"
  fi
}

run_main_healthcheck() {
  if [[ -n "$HEALTHCHECK" ]]; then
    [[ -x "$HEALTHCHECK" ]] || { echo "healthcheck is not executable: $HEALTHCHECK"; return 1; }
    "$HEALTHCHECK"
    return
  fi

  local py="python3"
  [[ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ]] && py="$HOME/.hermes/hermes-agent/venv/bin/python"
  (
    cd "$ROOT"
    bash scripts/ci/run_fast_tests.sh
    "$py" -m compileall -q candidate/phase2-hermes-ctl/hermes_ctl
    PYTHONPATH="$ROOT/candidate/phase2-hermes-ctl" \
      "$py" -m pytest candidate/phase2-hermes-ctl/tests -q
  )
}

previous_failures="$(read_state)"
output=""
rc=1
failure_kind="GitHub scan"
attempt=1
read -r -a backoffs <<<"$BACKOFF_SECONDS"
while (( attempt <= MAX_ATTEMPTS )); do
  set +e
  output="$(run_scanner 2>&1)"
  rc=$?
  set -e
  if (( rc == 0 )); then
    break
  fi
  if ! is_transient "$output" || (( attempt == MAX_ATTEMPTS )); then
    break
  fi
  idx=$((attempt - 1))
  delay="${backoffs[$idx]:-${backoffs[-1]:-5}}"
  sleep "$delay"
  attempt=$((attempt + 1))
done

if (( rc == 0 )); then
  set +e
  health_output="$(run_main_healthcheck 2>&1)"
  health_rc=$?
  set -e
  if (( health_rc != 0 )); then
    rc=$health_rc
    failure_kind="main healthcheck"
    attempt=1
    output="MAIN HEALTHCHECK FAILED
$health_output"
  fi
fi

if (( rc != 0 )); then
  failures=$((previous_failures + 1))
  write_state "failed" "$failures" "$output"
  printf 'HADA repair watchdog ALERT: %s failed after %s attempt(s); consecutive failures=%s.\n' "$failure_kind" "$attempt" "$failures"
  printf '%s\n' "$output" | tail -20
  if grep -qiE 'unauthorized|forbidden|bad credentials|authentication failed|gh auth|HTTP (401|403)|permission denied' <<<"$output"; then
    printf 'Human input required: GitHub authentication/permissions need attention.\n'
  else
    printf 'Self-healing will retry on the next scheduled run.\n'
  fi
  exit 1
fi

write_state "healthy" 0 "$output"
if (( previous_failures > 0 )); then
  printf 'HADA repair watchdog RECOVERED after %s consecutive failure(s).\n' "$previous_failures"
fi

# A clean no-open-PR scan is intentionally silent. Interesting scan findings
# remain visible so the reasoning repair cron can act on them.
if ! grep -qE 'No open PRs\.|scan complete: 0 failing PR' <<<"$output"; then
  printf '%s\n' "$output"
fi
