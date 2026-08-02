#!/usr/bin/env bash
# sign_evidence.sh — sign an artifact with a sha256 sidecar and append a
# tamper-evident hash-chain entry.
#
# Chain line format (literal TABs):
#     <stamp>\t<sha256>\t<prev_sha256>\t<path>
# The first entry links to prev=GENESIS. Each subsequent entry links to the
# sha256 of the raw previous line (help text / binary-safe bytes). A sidecar
# <path>.sha256 is also written so a single artifact can be checked without
# the chain, and so the chain can be verified out-of-band.
#
# Usage:
#     sign_evidence.sh <artifact> <stamp> [chain_file]
#   <artifact>    file to sign (sha256 + '.sha256' sidecar written beside it)
#   <stamp>       unique id for this entry (e.g. a run/cycle timestamp)
#   [chain_file]  hash-chain file to append to (default: <dir-of-artifact>/hash-chain.tsv)
#
# Exit: 0 = signed, 1 = error (missing arg, unreadable artifact, bad chain)
set -euo pipefail

ART="${1:-}"
STAMP="${2:-}"
if [[ -z "$ART" || -z "$STAMP" ]]; then
  echo "ERROR: usage: sign_evidence.sh <artifact> <stamp> [chain_file]" >&2
  exit 1
fi
[[ -f "$ART" ]] || { echo "ERROR: artifact not found: $ART" >&2; exit 1; }

REAL="$(readlink -f -- "$ART")"
DIR="$(dirname -- "$REAL")"

CHAIN="${3:-$DIR/hash-chain.tsv}"

# 1) sha256 sidecar beside the artifact
SHA="$(sha256sum "$REAL" | awk '{print $1}')"
printf '%s  %s\n' "$SHA" "$(basename -- "$REAL")" > "$REAL.sha256"

# 2) previous chain hash (sha256 of the last raw line, or GENESIS for first)
if [[ -s "$CHAIN" ]]; then
  PREV_LINE="$(tail -n1 "$CHAIN")"
  PREV="$(printf '%s' "$PREV_LINE" | sha256sum | awk '{print $1}')"
else
  PREV="GENESIS"
fi

# 3) append <stamp>\t<sha>\t<prev>\t<path>  (real tab separators)
printf '%s\t%s\t%s\t%s\n' "$STAMP" "$SHA" "$PREV" "$REAL" >> "$CHAIN"

echo "SIGNED $REAL (stamp=$STAMP, chain=$CHAIN)"