#!/usr/bin/env bash
# verify_evidence.sh — verify a tamper-evident evidence hash chain.
#
# For every line of <chain_file> (format: stamp<TAB>sha256<TAB>prev_sha256<TAB>path):
#   1. the previous-link field must equal the sha256 of the raw previous line
#      (GENESIS for the first entry);
#   2. the sha256 of the artifact at <path> must equal the recorded sha256;
#   3. if a '<path>.sha256' sidecar exists it must match too (redundant check).
# Stops at the first violation. Empty/no chain is informational (nothing signed).
#
# Usage: verify_evidence.sh [chain_file]   (default: ./hash-chain.tsv)
# Exit: 0 = chain intact (or empty), 1 = corrupt / broken / tampered
set -uo pipefail

CHAIN="${1:-hash-chain.tsv}"

[[ -s "$CHAIN" ]] || { echo "CHAIN EMPTY (no entries yet)"; exit 0; }

python3 - "$CHAIN" <<'PYEOF'
import hashlib, os, sys, subprocess

chain_path = sys.argv[1]
with open(chain_path, "rb") as f:
    raw_lines = f.read().splitlines(keepends=True)

prev = "GENESIS"
entries = 0
for i, raw in enumerate(raw_lines):
    line = raw.decode("utf-8", "replace").rstrip("\n")
    fields = line.split("\t")
    if len(fields) != 4:
        print(f"BROKEN line {i+1}: expected 4 TSV fields, got {len(fields)}")
        sys.exit(1)
    stamp, sha, phash, path = fields
    if phash != prev:
        print(f"BROKEN link line {i+1} ({stamp}): prev {phash} != expected {prev}")
        sys.exit(1)
    if not os.path.isfile(path):
        print(f"BROKEN line {i+1} ({stamp}): artifact missing: {path}")
        sys.exit(1)
    with open(path, "rb") as f:
        actual = hashlib.sha256(f.read()).hexdigest()
    if actual != sha:
        print(f"BROKEN line {i+1} ({stamp}): artifact sha {actual} != recorded {sha}")
        sys.exit(1)
    side = path + ".sha256"
    if os.path.isfile(side):
        # sidecar '<sha>  <name>' — compare only the token before the name
        got = open(side, "rb").read().split(b" ", 1)[0].decode("ascii", "replace").strip()
        if got != sha:
            print(f"BROKEN line {i+1} ({stamp}): sidecar sha {got} != recorded {sha}")
            sys.exit(1)
    prev = hashlib.sha256(line.encode("utf-8")).hexdigest()
    entries += 1

print(f"CHAIN OK ({entries} entries)")
sys.exit(0)
PYEOF