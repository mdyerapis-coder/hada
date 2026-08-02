# Evidence Signing & Tamper-Evident Hash Chain

**Status:** Operational
**Date:** 2026-08-02

Amplifies the existing evidence packaging conventions with a compact,
tamper-evident signing scheme so governed deployments and repair/audit
records can be proven unmodified.

## Design

1. **Sidecar** — `sign_evidence.sh <artifact> <stamp> [chain]` writes
   `<artifact>.sha256` (GNU `sha256sum` format) beside the artifact.
   A single artifact can therefore be checked without the chain.

2. **Hash chain** — the same invocation appends one TSV line to
   `<chain>` (default `hash-chain.tsv` beside the artifact):

       <stamp>\t<sha256>\t<prev_sha256>\t<path>

   - `<prev_sha256>` is the SHA-256 of the *previous raw line* (no trailing
     newline); the first entry links to `GENESIS`.
   - Tampering any prior line or artifact breaks every later link, which the
     verifier detects.

3. **Verifier** — `verify_evidence.sh <chain>` walks the whole chain, checking
   every link and every artifact (and its sidecar when present), and exits
   nonzero on the first violation. An empty chain is informational (nothing
   signed yet).

## Examples

    scripts/ci/sign_evidence.sh   value/diagnosis.json  run-20260802   evidence/hash-chain.tsv
    scripts/ci/verify_evidence.sh evidence/hash-chain.tsv
    # CHAIN OK (N entries)

## Integrity, not obscurity

Hashes are plain `sha256sum` so any toolchain can re-derive them. The value is
in the *chained* relationship and the sidecars, giving ordering + integrity
with no external dependency. Broken chains are never auto-resigned — a broken
chain is a human-investigation alert (consistent with the "never destroy
evidence" rule).

## Scope & boundary

- Pure bash + coreutils + python3 (verifier); no network, no new dependencies.
- Uses only paths passed on the command line — never writes into a repo's
  generated (`workspace/evidence`, `.ci-evidence`) roots unless directed.
- Intended to sign *final* committed artifacts; sign after the content is
  final, before it is archived/attested.