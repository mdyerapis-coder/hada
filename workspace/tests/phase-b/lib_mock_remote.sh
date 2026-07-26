#!/usr/bin/env bash
#
# HADA M1 Phase B — Shared mocked-remote sandbox harness for integration
# tests. LOCAL-ONLY: provides an executing mock SSH/SCP transport that
# rewrites the runner's absolute remote paths into a per-test sandbox and
# executes the EXACT generated remote command locally under PATH shims
# (sudo/stat/chown/install/docker/systemctl/findmnt). No network, no Docker
# daemon, no root.
#
# Usage (from a test script, after defining TEMP_DIR):
#   source "${HERE}/lib_mock_remote.sh"
#   mock_remote_init "${TEMP_DIR}"
#   -> exports HADA_SANDBOX, HADA_MOCK_SSH_LOG, HADA_PHASE_B_MOCK_SSH,
#      HADA_PHASE_B_MOCK_SCP, HADA_MOCK_SHIMS
#
# shellcheck disable=SC2034

mock_remote_init() {
    local base="$1"
    HADA_SANDBOX="${base}/sandbox"
    export HADA_SANDBOX
    mkdir -p "${HADA_SANDBOX}/tmp" \
             "${HADA_SANDBOX}/opt" \
             "${HADA_SANDBOX}/etc/systemd/system" \
             "${HADA_SANDBOX}/var/lib/hada/docker-volumes" \
             "${HADA_SANDBOX}/var/log"

    HADA_MOCK_SSH_LOG="${base}/ssh-commands.log"
    : > "${HADA_MOCK_SSH_LOG}"
    export HADA_MOCK_SSH_LOG

    HADA_MOCK_SHIMS="${base}/shims"
    export HADA_MOCK_SHIMS
    mkdir -p "${HADA_MOCK_SHIMS}"

    # ---- sudo shim: strips -n/-u, special-cases provision-secrets.sh ------
    cat > "${HADA_MOCK_SHIMS}/sudo" <<'SHIM'
#!/usr/bin/env bash
while [[ "${1-}" == "-n" || "${1-}" == "-u" ]]; do
    if [[ "${1-}" == "-u" ]]; then shift 2; else shift; fi
done
[[ $# -gt 0 ]] || { echo "sudo shim: missing command" >&2; exit 1; }
case "$1" in
    */provision-secrets.sh)
        # Execute the checksum-verified installed script. Its internal
        # hardcoded /opt/hada paths are redirected into the sandbox so the
        # .env is created inside the sandbox; the valkey secret file is
        # written to the sandbox host secrets path (mode 0600) so the
        # runner's Gate 3f reading of it works.
        SB_VALKEY="${HADA_SANDBOX:?}/var/lib/hada/secrets/valkey"
        mkdir -p "${SB_VALKEY}"
        t="$(mktemp)"
        sed "s|/opt/hada|${HADA_SANDBOX:?}/opt/hada|g; s|/var/lib/hada|${HADA_SANDBOX:?}/var/lib/hada|g" "$1" > "$t"
        bash "$t"; rc=$?
        rm -f "$t"
        # Emulate the runner Gate 3f: write the valkey password to the
        # protected host secret file (mode 0600) from the generated .env.
        if [[ -f "${HADA_SANDBOX}/opt/hada/.env" ]]; then
            vp="$(grep '^VALKEY_PASSWORD=' "${HADA_SANDBOX}/opt/hada/.env" | head -1 | cut -d= -f2-)"
            printf '%s' "${vp}" > "${SB_VALKEY}/requirepass"
            chmod 0600 "${SB_VALKEY}/requirepass"
        fi
        exit "$rc" ;;
esac
exec "$@"
SHIM

    # ---- stat shim: ownership queries report the expected root:hada -------
    cat > "${HADA_MOCK_SHIMS}/stat" <<'SHIM'
#!/usr/bin/env bash
if [[ "$*" == *"%U:%G"* ]]; then echo "root:hada"; exit 0; fi
exec /usr/bin/stat "$@"
SHIM

    # ---- chown shim: no-op success (sandbox runs unprivileged) ------------
    cat > "${HADA_MOCK_SHIMS}/chown" <<'SHIM'
#!/usr/bin/env bash
exit 0
SHIM

    # ---- install shim: strip -o/-g (ownership) then run real install ------
    cat > "${HADA_MOCK_SHIMS}/install" <<'SHIM'
#!/usr/bin/env bash
args=()
skip=0
for a in "$@"; do
    if (( skip )); then skip=0; continue; fi
    case "$a" in
        -o|-g) skip=1 ;;
        *) args+=("$a") ;;
    esac
done
exec /usr/bin/install "${args[@]}"
SHIM

    # ---- systemctl shim: silent success, no units reported ----------------
    cat > "${HADA_MOCK_SHIMS}/systemctl" <<'SHIM'
#!/usr/bin/env bash
exit 0
SHIM

    # ---- findmnt shim: reports the locked UUID for any -o UUID query ------
    cat > "${HADA_MOCK_SHIMS}/findmnt" <<'SHIM'
#!/usr/bin/env bash
if [[ "$*" == *"-o UUID"* ]]; then
    echo "a1574097-cdf9-4d0a-ace0-adac63038e56"
fi
exit 0
SHIM

    # ---- docker shim: clean host + fixture compose config JSON ------------
    cat > "${HADA_MOCK_SHIMS}/docker" <<'SHIM'
#!/usr/bin/env bash
args="$*"
case "${args}" in
    "ps -a --format {{.Image}}"|"ps -a --format {{.Names}}"|"ps -aq"|"images -q"|"volume ls -q") exit 0 ;;
    "network ls --format {{.Name}}") echo bridge; exit 0 ;;
    "image inspect hada-orchestrator:0.2.0") exit 1 ;;
    "compose version --short") echo "2.27.0"; exit 0 ;;
esac
if [[ "${args}" == *"config --format json"* ]]; then
    cat <<'JSON'
{"name":"hada-m1","services":{"caddy":{"ports":[{"mode":"ingress","host_ip":"127.0.0.1","target":80,"published":80,"protocol":"tcp"}]},"postgres":{}},"volumes":{"postgres-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/postgres-data"}},"valkey-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/valkey-data"}},"prometheus-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/prometheus-data"}},"loki-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/loki-data"}},"alloy-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/alloy-data"}},"grafana-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/grafana-data"}},"caddy-data":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/caddy-data"}},"caddy-config":{"driver":"local","driver_opts":{"type":"none","o":"bind","device":"/var/lib/hada/docker-volumes/caddy-config"}}}}
JSON
    exit 0
fi
exit 0
SHIM

    chmod +x "${HADA_MOCK_SHIMS}"/*

    # ---- executing mock SSH ------------------------------------------------
    HADA_PHASE_B_MOCK_SSH="${base}/mock-ssh"
    export HADA_PHASE_B_MOCK_SSH
    cat > "${HADA_PHASE_B_MOCK_SSH}" <<'SHIM'
#!/usr/bin/env bash
cmd="${@: -1}"
printf '%s\n' "$(printf '%s' "${cmd}" | base64 -w0)" >> "${HADA_MOCK_SSH_LOG:?}"
SB="${HADA_SANDBOX:?}"
cmd="${cmd//\/opt\/hada/${SB}/opt/hada}"
cmd="${cmd//\/var\/lib\/hada/${SB}/var/lib/hada}"
cmd="${cmd//\/var\/log\/hada/${SB}/var/log/hada}"
cmd="${cmd//\/etc\/systemd\/system/${SB}/etc/systemd/system}"
cmd="${cmd//\/tmp\/hada-b-deploy-/${SB}/tmp/hada-b-deploy-}"
PATH="${HADA_MOCK_SHIMS:?}:${PATH}" exec bash -c "${cmd}"
SHIM
    chmod +x "${HADA_PHASE_B_MOCK_SSH}"

    # ---- mock SCP: copies into the sandbox ---------------------------------
    HADA_PHASE_B_MOCK_SCP="${base}/mock-scp"
    export HADA_PHASE_B_MOCK_SCP
    cat > "${HADA_PHASE_B_MOCK_SCP}" <<'SHIM'
#!/usr/bin/env bash
src="$1"
dst="$2"
dst="${dst#hada-control:}"
SB="${HADA_SANDBOX:?}"
dst="${dst//\/tmp\/hada-b-deploy-/${SB}/tmp/hada-b-deploy-}"
dst="${dst//\/opt\/hada/${SB}/opt/hada}"
mkdir -p "$(dirname "${dst}")"
cp "${src}" "${dst}"
SHIM
    chmod +x "${HADA_PHASE_B_MOCK_SCP}"
}

# Decode the base64-per-line command log to readable text.
mock_remote_decode_log() {
    local rec
    while IFS= read -r rec; do
        printf '%s\n----\n' "$(printf '%s' "${rec}" | base64 -d)"
    done < "${HADA_MOCK_SSH_LOG}"
}
