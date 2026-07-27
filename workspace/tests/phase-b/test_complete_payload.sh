#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2115,SC2155
# (intentional patterns in test/mock/evidence scripts; reviewed for CI lint compliance)
#
# HADA M1 Phase B — Complete runtime payload test (correction 1)
#
# Proves the installed build context is COMPLETE:
#   - every Dockerfile COPY/ADD source exists in the installed tree;
#   - every Compose host-bind source exists;
#   - omitting pyproject.toml, README.md or a monitoring file fails
#     validate_build_context;
#   - Gate 6 (image pull + build) can reach a valid complete build context.
#
# LOCAL-ONLY, fully mocked against the v2 candidate.

set -Eeuo pipefail

PASS_COUNT=0
FAIL_COUNT=0
TEMP_DIR="$(mktemp -d /tmp/hada-payload-test-XXXXXX)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

assert_pass() { printf 'PASS: %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
assert_fail() { printf 'FAIL: %s\n' "$1" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${HERE}/../.." && pwd)"
RUNNER="${DEPLOY_ROOT}/scripts/run-phase-b-deploy.sh"
[[ -f "${RUNNER}" ]] || { echo "FAIL: runner not found" >&2; exit 1; }

# shellcheck source=lib_mock_remote.sh
source "${HERE}/lib_mock_remote.sh"
mock_remote_init "${TEMP_DIR}"

export HADA_PHASE_B_TEST_LIB=1
export HADA_PHASE_B_NO_CLEANUP_TRAP=1
export HADA_PHASE_B_DEPLOY_DIR="${DEPLOY_ROOT}"
export HADA_PHASE_B_EVIDENCE_DIR="${TEMP_DIR}/evidence"
export HADA_PHASE_B_TIMESTAMP="55555555555555"
export HADA_PHASE_B_CANDIDATE_ARCHIVE="${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip"
export HADA_PHASE_B_CANDIDATE_SHA256="$(awk '{print $1}' "${DEPLOY_ROOT}/deploy-v4/HADA-M1-gcp-candidate-v4.zip.sha256")"
mkdir -p "${HADA_PHASE_B_EVIDENCE_DIR}"
# shellcheck source=../../scripts/run-phase-b-deploy.sh
source "${RUNNER}"

# Extract the candidate so CANDIDATE_ROOT is populated for install_full_tree.
verify_and_extract_candidate >/dev/null 2>&1 || {
    echo "FAIL: could not extract candidate" >&2; exit 1;
}

SB_OPT="${HADA_SANDBOX}/opt/hada"

# Build a full installed tree from the v2 candidate (mirrors Gate 3 atomic
# install of the complete payload).
install_full_tree() {
    rm -rf "${SB_OPT}"
    mkdir -p "${SB_OPT}"
    cp -a "${CANDIDATE_ROOT}/pyproject.toml" "${SB_OPT}/pyproject.toml"
    cp -a "${CANDIDATE_ROOT}/README.md" "${SB_OPT}/README.md"
    cp -a "${CANDIDATE_ROOT}/Dockerfile" "${SB_OPT}/Dockerfile"
    cp -a "${CANDIDATE_ROOT}/src" "${SB_OPT}/src"
    cp -a "${CANDIDATE_ROOT}/config" "${SB_OPT}/config"
    cp -a "${CANDIDATE_ROOT}/deploy" "${SB_OPT}/deploy"
    cp -a "${CANDIDATE_ROOT}/scripts" "${SB_OPT}/scripts"
}

# ---------------------------------------------------------------------------
# Dockerfile COPY/ADD source coverage
# ---------------------------------------------------------------------------
install_full_tree
all_dockerfile_present=1
for s in "${dockerfile_srcs[@]}"; do
    if [[ ! -e "${SB_OPT}/$s" ]]; then
        assert_fail "Dockerfile source missing in installed tree: $s"
        all_dockerfile_present=0
    fi
done
if (( all_dockerfile_present == 1 )); then
    assert_pass "every Dockerfile COPY/ADD source present in installed /opt/hada"
fi

# Dockerfile COPY/ADD sources (parsed from the v2 Dockerfile, excluding the
# multistage `COPY --from=build /wheels /wheels` which is internal).
dockerfile_srcs=(
    pyproject.toml
    README.md
    src
    config
    src/hada/db/migrations
    deploy
    scripts/container-entrypoint.sh
)

# ---------------------------------------------------------------------------
# Compose host-bind source coverage
# ---------------------------------------------------------------------------
install_full_tree
bind_missing=0
while IFS= read -r line; do
    # host-bind volumes look like:  - ../path:/container/path[:ro]
    if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*\.\./ ]]; then
        host="${line#*-}"
        host="${host#* }"
        host="${host%%:*}"
        # resolve relative to deploy/compose (../X -> deploy/X)
        resolved="${CANDIDATE_ROOT}/deploy/${host#../}"
        if [[ ! -e "${resolved}" ]]; then
            assert_fail "Compose host-bind source missing: ${host}"
            bind_missing=1
        fi
    fi
done < "${CANDIDATE_ROOT}/deploy/compose/compose.yaml"
if (( bind_missing == 0 )); then
    assert_pass "every Compose host-bind source present in candidate"
fi

# ---------------------------------------------------------------------------
# validate_build_context: complete tree passes
# ---------------------------------------------------------------------------
install_full_tree
set +e
out="$(validate_build_context 2>&1)"; rc=$?
set -e
if (( rc == 0 )); then
    assert_pass "validate_build_context passes on a complete installed tree"
else
    assert_fail "validate_build_context failed on complete tree: $(tail -3 <<<"$out")"
fi

# ---------------------------------------------------------------------------
# validate_build_context: omitting pyproject.toml / README.md / monitoring fails
# ---------------------------------------------------------------------------
for missing in pyproject.toml README.md deploy/prometheus/prometheus.yml deploy/loki/config.yml deploy/alloy/config.alloy; do
    install_full_tree
    rm -rf "${SB_OPT}/${missing}"
    set +e
    if validate_build_context >/dev/null 2>&1; then
        assert_fail "validate_build_context should FAIL when ${missing} is omitted"
    else
        assert_pass "validate_build_context fails when ${missing} is omitted"
    fi
    set -e
done

# ---------------------------------------------------------------------------
# Gate 6 can reach a valid complete build context (mocked build)
# ---------------------------------------------------------------------------
install_full_tree
set +e
if pull_build_images >/dev/null 2>&1; then
    assert_pass "Gate 6 (pull/build) reaches a valid complete build context"
else
    assert_fail "Gate 6 failed to reach a valid build context"
fi
set -e

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Complete runtime payload test results"
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
