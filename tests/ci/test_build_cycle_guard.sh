#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="$ROOT/scripts/ci/build_cycle_guard.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
REMOTE="$TMP/origin.git"
SEED="$TMP/seed"
STATE="$TMP/state"

mkdir -p "$SEED"
git init --bare -q "$REMOTE"
git -C "$SEED" init -q
git -C "$SEED" config user.name Test
git -C "$SEED" config user.email test@example.invalid
printf 'base\n' >"$SEED/README.md"
git -C "$SEED" add README.md
git -C "$SEED" commit -qm base
git -C "$SEED" branch -M main
git -C "$SEED" remote add origin "$REMOTE"
git -C "$SEED" push -q -u origin main
git --git-dir="$REMOTE" symbolic-ref HEAD refs/heads/main

out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300)
token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
worktree=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])' <<<"$out")
base=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["base_sha"])' <<<"$out")
[[ -n "$token" ]]
[[ -d "$worktree/.git" || -f "$worktree/.git" ]]
[[ "$(git -C "$worktree" rev-parse HEAD)" == "$base" ]]

set +e
python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300 >/tmp/build-guard-busy.out 2>&1
rc=$?
set -e
[[ "$rc" == 75 ]]
grep -q 'active lease' /tmp/build-guard-busy.out

python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status complete >/dev/null
[[ ! -e "$STATE/lease.json" ]]

# A cycle must be based on the immutable origin/main SHA and contain a clean
# committed change before verification.
out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300)
token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
worktree=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])' <<<"$out")
printf 'change\n' >>"$worktree/README.md"
git -C "$worktree" config user.name Test
git -C "$worktree" config user.email test@example.invalid
git -C "$worktree" add README.md
git -C "$worktree" commit -qm change
HEALTH="$TMP/health"
printf '#!/usr/bin/env bash\nexit 0\n' >"$HEALTH"
chmod +x "$HEALTH"
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >/dev/null
[[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$STATE/lease.json")" == verified ]]
mkdir -p "$TMP/bin"
cat >"$TMP/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >"$TMP/gh.args"
printf 'https://example.invalid/pr/1\n'
EOF
chmod +x "$TMP/bin/gh"
printf 'body\n' >"$TMP/body.md"
PATH="$TMP/bin:$PATH" python3 "$GUARD" publish \
  --state-dir "$STATE" --token "$token" --title 'bounded cycle' --body-file "$TMP/body.md" >/dev/null
grep -q '^pr create --draft --base main --head agent/build-cycle-' "$TMP/gh.args"
if grep -q 'merge' "$TMP/gh.args"; then
  echo 'FAIL: publish invoked merge' >&2
  exit 1
fi
[[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$STATE/lease.json")" == published ]]
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status complete >/dev/null

# If main moves after prepare, verification must fail closed and quarantine.
out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300)
token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
worktree=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])' <<<"$out")
printf 'cycle\n' >>"$worktree/README.md"
git -C "$worktree" config user.name Test
git -C "$worktree" config user.email test@example.invalid
git -C "$worktree" add README.md
git -C "$worktree" commit -qm cycle
printf 'main moved\n' >>"$SEED/README.md"
git -C "$SEED" add README.md
git -C "$SEED" commit -qm moved
git -C "$SEED" push -q origin main
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >"$TMP/stale.out" 2>&1
rc=$?
set -e
[[ "$rc" == 1 ]]
grep -q 'origin/main moved' "$TMP/stale.out"
[[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$STATE/lease.json")" == quarantined ]]
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status quarantined >/dev/null

# True Git conflict markers are rejected; decorative comment separators are not.
out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300)
token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
worktree=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])' <<<"$out")
printf '# ===== decorative separator\n<<<<<<< HEAD\nbad\n=======\nworse\n>>>>>>> branch\n' >"$worktree/conflict.txt"
git -C "$worktree" add conflict.txt
git -C "$worktree" commit -qm conflict
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >"$TMP/marker.out" 2>&1
rc=$?
set -e
[[ "$rc" == 1 ]]
grep -q 'unresolved conflict markers: conflict.txt:2' "$TMP/marker.out"
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status quarantined >/dev/null

# A hung verification is time-bounded and its expired lease self-recovers.
out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300)
token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
worktree=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])' <<<"$out")
printf 'timeout\n' >>"$worktree/README.md"
git -C "$worktree" add README.md
git -C "$worktree" commit -qm timeout
printf '#!/usr/bin/env bash\nsleep 5\n' >"$HEALTH"
chmod +x "$HEALTH"
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 1 >"$TMP/timeout.out" 2>&1
rc=$?
set -e
[[ "$rc" == 1 ]]
python3 - "$STATE/lease.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]); d = json.loads(p.read_text()); d["expires_at"] = 0
p.write_text(json.dumps(d))
PY
out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" --ttl 300)
[[ "$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["recovered_stale_lease"]).lower())' <<<"$out")" == true ]]
token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status complete >/dev/null

# Corrupt state must fail closed before any path outside state/worktrees is removed.
python3 - "$STATE/lease.json" "$SEED" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({"token": "tampered", "repo": sys.argv[2], "worktree": "/", "status": "active"}))
PY
set +e
python3 "$GUARD" release --state-dir "$STATE" --token tampered --status failed >"$TMP/unsafe.out" 2>&1
rc=$?
set -e
[[ "$rc" == 1 ]]
grep -q 'unsafe worktree path' "$TMP/unsafe.out"
[[ -d / ]]
rm -f "$STATE/lease.json"

printf 'PASS: prepare creates pinned isolated worktree and serialises cycles\n'
printf 'PASS: verify accepts a clean committed cycle and rejects a stale base\n'
printf 'PASS: publish is draft-only; marker, timeout, recovery, and path safety hold\n'
