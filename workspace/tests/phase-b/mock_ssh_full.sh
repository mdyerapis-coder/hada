#!/usr/bin/env bash
# shellcheck disable=SC2124
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# Smart mock SSH for the full Gates 1-10 acceptance test (v3).
#
# Logs every remote command (base64) to HADA_MOCK_SSH_LOG, then:
#   - docker compose config --format json  -> render valid JSON from the v3
#     candidate compose files (so Gate 5 succeeds);
#   - docker ps --all --format json        -> report all services running+healthy
#     (so Gate 8a/8c/8d service-running checks pass without loops);
#   - pg_isready / valkey-cli ping / python urlopen / ss -> success markers
#     (so health checks and loopback checks pass without long sleeps);
#   - git ls-remote --exit-code <URL> HEAD  -> echo LS_REMOTE_HOST_OK /
#     LS_REMOTE_CONTAINER_OK on SUCCESS and exit 0; for a NON-matching URL
#     (failure fixture) exit non-zero and emit NO success marker (fail-closed);
#   - docker volume/network/image inspect/ls -> benign success;
#   - everything else -> executed via bash -c with the mock PATH shims so
#     install/verify/copy commands actually run in the sandbox.
#
# LOCAL-ONLY.

set -uo pipefail

log_cmd() { printf '%s\n' "$(printf '%s' "$1" | base64 -w0)" >> "${HADA_MOCK_SSH_LOG:?}"; }

# ssh is invoked as: ssh [options] host "command" — the remote command is
# always the LAST argument (same convention as lib_mock_remote's mock-ssh).
cmd="${@: -1}"

# Rewrite absolute deployment paths into the sandbox so install/verify/copy
# commands actually run inside the mock filesystem (same as lib_mock_remote).
if [[ -n "${HADA_SANDBOX:-}" ]]; then
    cmd="${cmd//\/opt\/hada/${HADA_SANDBOX}\/opt\/hada}"
    cmd="${cmd//\/var\/lib\/hada/${HADA_SANDBOX}\/var\/lib\/hada}"
    cmd="${cmd//\/var\/log\/hada/${HADA_SANDBOX}\/var\/log\/hada}"
    cmd="${cmd//\/etc\/systemd\/system/${HADA_SANDBOX}\/etc\/systemd\/system}"
    cmd="${cmd//\/tmp\/hada-b-deploy-/${HADA_SANDBOX}\/tmp\/hada-b-deploy-}"
fi

log_cmd "${cmd}"

if [[ "${cmd}" == *"ps --all --format json"* || "${cmd}" == *"ps -a --format json"* ]]; then
    echo '[{"Name":"hada-m1-postgres-1","State":"running","Health":"healthy"},{"Name":"hada-m1-valkey-1","State":"running","Health":"healthy"},{"Name":"hada-m1-orchestrator-1","State":"running","Health":"healthy"},{"Name":"hada-m1-caddy-1","State":"running","Health":"healthy"}]'
    exit 0
fi

# git ls-remote acceptance (Gate 10). Independently assert BOTH the return
# code AND the success marker. The configured/verified Hermesctl URL succeeds;
# any other URL fails closed (non-zero exit, no marker).
if [[ "${cmd}" == *"git ls-remote"* ]]; then
    if [[ "${cmd}" == *"mdyerapis-coder/hermesctl.git"* ]]; then
        if [[ "${cmd}" == *"exec -T orchestrator"* ]]; then
            echo "LS_REMOTE_CONTAINER_OK"
        else
            echo "LS_REMOTE_HOST_OK"
        fi
        exit 0
    else
        # Failure fixture: do NOT emit a success marker; exit non-zero.
        echo "FAIL: git ls-remote failed" >&2
        exit 1
    fi
fi

# Health / liveness success markers (no long sleeps, no real network)
if [[ "${cmd}" == *"pg_isready"* ]]; then exit 0; fi
if [[ "${cmd}" == *"valkey-cli ping"* ]]; then echo "PONG"; exit 0; fi
if [[ "${cmd}" == *"urlopen"* || "${cmd}" == *"readyz"* ]]; then exit 0; fi
if [[ "${cmd}" == *"ss -lntp"* || "${cmd}" == *"ss -ltnp"* ]]; then
    echo "LISTEN 0 128 127.0.0.1:80 users:((\"caddy\",pid=1,fd=3))"
    exit 0
fi

# Everything else: execute via bash -c with the mocked PATH (install/verify
# copy/touch/stat/sha256sum etc. run for real in the sandbox).
if [[ -n "${HADA_MOCK_SHIMS:-}" ]]; then
    PATH="${HADA_MOCK_SHIMS}:${PATH}" bash -c "${cmd}"
else
    bash -c "${cmd}"
fi
rc=$?
rm -rf "${XD:-}" 2>/dev/null || true
exit "${rc}"
