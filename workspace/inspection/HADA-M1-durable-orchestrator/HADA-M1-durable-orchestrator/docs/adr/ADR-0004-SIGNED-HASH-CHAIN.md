# ADR-0004: Ed25519-Signed Audit and Evidence Records

**Status:** Proposed

## Context

A reviewer must detect deleted, reordered or modified records and must be able to verify that an evidence manifest was produced by the configured appliance key.

## Decision

Canonical JSON is hashed with SHA-256. Audit records include the previous event hash, producing one ordered global chain. Event hashes and evidence manifests are signed using Ed25519. Public-key identifiers are derived from the SHA-256 digest of the raw public key.

## Consequences

A lost private key prevents new signed records but does not prevent verification with the retained public key. Key rotation requires a separately governed continuity record and is not automated in M1.
