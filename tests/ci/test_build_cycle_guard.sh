#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="$ROOT/scripts/ci/build_cycle_guard.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
REMOTE="$TMP/origin.git"
SEED="$TMP/seed"
STATE="$TMP/state"
TRACE="$TMP/command-trace"
OWNER_PID=$$

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
seed_branch=$(git -C "$SEED" branch --show-current)
seed_status=$(git -C "$SEED" status --porcelain)

prepare_cycle() {
  local out
  out=$(python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" \
    --ttl 300 --owner-pid "$OWNER_PID" \
    --allow-path README.md --allow-path decorative.sh --allow-path conflict.txt)
  token=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' <<<"$out")
  run_id=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<<"$out")
  worktree=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])' <<<"$out")
  branch=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["branch"])' <<<"$out")
  base=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["base_sha"])' <<<"$out")
  printf '%s' "$branch" >"$TMP/current-branch"
}

commit_change() {
  local text=${1:-change}
  printf '%s\n' "$text" >>"$worktree/README.md"
  git -C "$worktree" config user.name Test
  git -C "$worktree" config user.email test@example.invalid
  git -C "$worktree" add README.md
  git -C "$worktree" commit -qm "$text"
}

HEALTH="$TMP/health"
printf '#!/usr/bin/env bash\nprintf "hermetic health pass\\n"\n' >"$HEALTH"
chmod +x "$HEALTH"

# prepare: controller-owned bare mirror + exact immutable SHA + isolated worktree
set +e
python3 "$GUARD" prepare --repo "$SEED" --state-dir "$TMP/no-allow-state" \
  --ttl 300 --owner-pid "$OWNER_PID" >"$TMP/no-allow.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
grep -q 'at least one --allow-path is required' "$TMP/no-allow.out"
prepare_cycle
[[ ${#token} == 64 ]]
[[ -d "$STATE/repository.git" ]]
[[ "$worktree" == "$STATE/runs/$run_id/worktree" ]]
[[ "$(git -C "$worktree" rev-parse HEAD)" == "$base" ]]
[[ "$(git -C "$SEED" branch --show-current)" == "$seed_branch" ]]
[[ "$(git -C "$SEED" status --porcelain)" == "$seed_status" ]]

# foreign ownership cannot mutate any stage
bad=$(printf 'f%.0s' {1..64})
for command in heartbeat verify release; do
  set +e
  if [[ $command == release ]]; then
    python3 "$GUARD" release --state-dir "$STATE" --token "$bad" --status failed >/dev/null 2>&1
  elif [[ $command == verify ]]; then
    HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
      --state-dir "$STATE" --token "$bad" --command-timeout 5 >/dev/null 2>&1
  else
    python3 "$GUARD" heartbeat --state-dir "$STATE" --token "$bad" >/dev/null 2>&1
  fi
  rc=$?
  set -e
  [[ $rc == 1 ]]
done

# contention: a live owner with unexpired heartbeat blocks re-prepare
python3 - "$STATE/lease.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text())
# owner is still live (pid matches), heartbeat fresh — contention should block
PY
set +e
python3 "$GUARD" prepare --repo "$SEED" --state-dir "$STATE" \
  --ttl 300 --owner-pid "$OWNER_PID" --allow-path README.md >"$TMP/busy.out" 2>&1
rc=$?
set -e
[[ $rc == 75 ]]
grep -q 'active build-cycle lease' "$TMP/busy.out"
python3 "$GUARD" heartbeat --state-dir "$STATE" --token "$token" >/dev/null
python3 "$GUARD" status --state-dir "$STATE" >"$TMP/status.json"
python3 - "$TMP/status.json" <<'PY'
import json, sys
v=json.load(open(sys.argv[1])); assert v['owner_live'] is True; assert 'token' not in v
PY
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status complete >/dev/null

# A committed candidate outside the cycle's explicit path allowlist fails closed.
prepare_cycle
printf 'out of scope\n' >"$worktree/forbidden.md"
git -C "$worktree" add forbidden.md
git -C "$worktree" config user.name Test
git -C "$worktree" config user.email test@example.invalid
git -C "$worktree" commit -qm forbidden
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >"$TMP/allowlist.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
grep -q 'candidate path outside allowlist: forbidden.md' "$TMP/allowlist.out"
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status quarantined >/dev/null

# clean committed candidate verifies, produces hashed evidence, and decorative separators pass
prepare_cycle
printf '# ===== decorative separator\n' >"$worktree/decorative.sh"
git -C "$worktree" add decorative.sh
git -C "$worktree" config user.name Test
git -C "$worktree" config user.email test@example.invalid
git -C "$worktree" commit -qm change
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >"$TMP/verified.json"
python3 - "$STATE/lease.json" <<'PY'
import json, re, sys
v=json.load(open(sys.argv[1])); assert v['status']=='verified'; assert re.fullmatch(r'[0-9a-f]{64}', v['gate_log_sha256'])
PY

# draft-only publication is bound to the exact verified SHA and idempotently reuses an existing PR
mkdir -p "$TMP/bin"
verified_head=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["verified_head"])' "$STATE/lease.json")
real_git=$(command -v git)
cat >"$TMP/bin/git" <<EOF
#!/usr/bin/env bash
set -euo pipefail
branch=\$(cat "$TMP/current-branch")
last=\${!#}
# Reproduce a mutable-branch race immediately before a branch-name push.
if [[ "\${1:-}" == push && "\$last" == "\$branch" ]]; then
  printf 'unverified race\n' >> decorative.sh
  "$real_git" add decorative.sh
  "$real_git" -c user.name=Race -c user.email=race@example.invalid commit -qm race
fi
exec "$real_git" "\$@"
EOF
chmod +x "$TMP/bin/git"
cat >"$TMP/bin/gh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "\$*" >>"$TRACE"
branch=\$(cat "$TMP/current-branch")
case "\$1 \$2" in
  'pr list')
    if [[ -f "$TMP/pr-created" ]]; then
      printf '[{"url":"https://example.invalid/pr/1","isDraft":true,"headRefName":"%s","baseRefName":"main","headRefOid":"$verified_head"}]\n' "\$branch"
    else
      printf '[]\n'
    fi
    ;;
  'pr create')
    touch "$TMP/pr-created"
    printf 'https://example.invalid/pr/1\n'
    ;;
  'pr view')
    printf '{"url":"https://example.invalid/pr/1","isDraft":true,"headRefName":"%s","baseRefName":"main","headRefOid":"$verified_head"}\n' "\$branch"
    ;;
  *) exit 9 ;;
esac
EOF
chmod +x "$TMP/bin/gh"
printf 'body\n' >"$TMP/body.md"
PATH="$TMP/bin:$PATH" python3 "$GUARD" publish --state-dir "$STATE" \
  --token "$token" --title 'bounded cycle' --body-file "$TMP/body.md" >/dev/null
remote_head=$("$real_git" --git-dir="$REMOTE" rev-parse "refs/heads/$branch")
[[ "$remote_head" == "$verified_head" ]]
[[ "$(grep -c '^pr create ' "$TRACE")" == 1 ]]
grep -q '^pr create --draft --base main --head agent/build-cycle-' "$TRACE"
if grep -Eq 'merge|rebase|force' "$TRACE"; then
  echo 'FAIL: publication invoked a prohibited operation' >&2
  exit 1
fi
[[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$STATE/lease.json")" == awaiting_human ]]
# Simulate recovery after create succeeded but final state transition was interrupted.
python3 - "$STATE/lease.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['status']='verified'; p.write_text(json.dumps(d))
PY
PATH="$TMP/bin:$PATH" python3 "$GUARD" publish --state-dir "$STATE" \
  --token "$token" --title 'bounded cycle' --body-file "$TMP/body.md" >/dev/null
[[ "$(grep -c '^pr create ' "$TRACE")" == 1 ]]
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status complete >/dev/null

# main moving after prepare blocks verification and quarantines the cycle
prepare_cycle
commit_change stale
printf 'main moved\n' >>"$SEED/README.md"
git -C "$SEED" add README.md
git -C "$SEED" commit -qm moved
git -C "$SEED" push -q origin main
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >"$TMP/stale.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
grep -q 'origin/main moved' "$TMP/stale.out"
[[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$STATE/lease.json")" == quarantined ]]
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status quarantined >/dev/null
[[ -f "$STATE/quarantine/$run_id/manifest.json" ]]

# real conflict markers and hung gates fail closed
prepare_cycle
printf '<<<<<<< HEAD\nbad\n=======\nworse\n>>>>>>> branch\n' >"$worktree/conflict.txt"
git -C "$worktree" add conflict.txt
git -C "$worktree" config user.name Test
git -C "$worktree" config user.email test@example.invalid
git -C "$worktree" commit -qm conflict
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 5 >"$TMP/marker.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
grep -q 'unresolved conflict markers: conflict.txt:1' "$TMP/marker.out"
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status quarantined >/dev/null

prepare_cycle
commit_change timeout
printf '#!/usr/bin/env bash\nsleep 5\n' >"$HEALTH"
chmod +x "$HEALTH"
set +e
HADA_BUILD_VERIFY_COMMAND="$HEALTH" python3 "$GUARD" verify \
  --state-dir "$STATE" --token "$token" --command-timeout 1 >"$TMP/timeout.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status quarantined >/dev/null

# dead-owner recovery quarantines; corrupt/unsafe paths fail before deletion
prepare_cycle
python3 - "$STATE/lease.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['pid']=99999999; d['pid_start_time']='dead'; d['heartbeat_at']=0; p.write_text(json.dumps(d))
PY
python3 "$GUARD" recover --state-dir "$STATE" >"$TMP/recover.json"
[[ ! -e "$STATE/lease.json" ]]
[[ -f "$STATE/quarantine/$run_id/manifest.json" ]]

prepare_cycle
python3 - "$STATE/lease.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['worktree']='/'; p.write_text(json.dumps(d))
PY
set +e
python3 "$GUARD" release --state-dir "$STATE" --token "$token" --status failed >"$TMP/unsafe.out" 2>&1
rc=$?
set -e
[[ $rc == 1 ]]
grep -q 'unsafe worktree path' "$TMP/unsafe.out"
[[ -d / ]]

[[ "$(git -C "$SEED" branch --show-current)" == "$seed_branch" ]]
[[ "$(git -C "$SEED" status --porcelain)" == "$seed_status" ]]
printf 'PASS: token lease, live-owner protection, heartbeat, and recovery\n'
printf 'PASS: mirror-isolated immutable worktree, stale-base and marker rejection\n'
printf 'PASS: hashed verification, draft-only idempotent publication, safe quarantine\n'
