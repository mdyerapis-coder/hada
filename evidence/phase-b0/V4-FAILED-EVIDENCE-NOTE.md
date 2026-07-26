# Phase B0 preserved failure evidence

- `preflight-run-20260726205629`: local/sandbox DNS failure before any VM contact.
- `preflight-run-20260726205647`: valid remote v3 Phase B0 failure at the volume assertion because `valkey-data` was declared but unused.
- No Phase B deployment occurred in either run.

Both original evidence directories are preserved without deletion or overwrite.
