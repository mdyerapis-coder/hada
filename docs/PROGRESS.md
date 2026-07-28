# HADA Build Progress

Autonomous build loop log. Each cycle implements one bounded, verified change
on a feature branch, opens a draft PR, and records progress here. No merge,
deploy, secret/infra change, or governance bypass occurs.

## Cycle 1 — Repair-pipeline test suite + guardrail fix
- Branch: `agent/autofix-add-autonomous-repair-pipeline` (PR #5)
- Added `tests/ci/test_repair_pipeline.sh` (guardrail allow/deny + orchestrator
  contract); wired into `run_fast_tests.sh`.
- **Caught a critical guardrail bug**: the secret/merge content scan used
  `grep -v '^\+\+\+'` to strip diff headers, but GNU grep ERE treats `\+` as
  "1+", so `^\+\+\+` matched ANY `+` line — silently dropping secret/merge
  lines from the scan. Removed the filter. Secrets + `gh pr merge` now caught.
- Also fixed earlier: `verify_release_manifests.sh` pattern + corrupt v2 manifest.
- Verified: 7/7 repair tests pass; CI `Verify` + `E2E` green.
- Review: routed to agent-forge subagent (background).

## Cycle 2 — Roadmap + ADR 0001 status
- Branch: `agent/docs-roadmap-and-adr1-accepted` (PR this change)
- Created `ROADMAP.md` (explicit M1 phases, status, guardrails, backlog).
- Promoted `docs/adr/0001-governed-release-pipeline.md` Proposed → Accepted.
- Recorded progress (this file).

- **Cycle 16 — llmfit brain wiring (Phase 3 enabler).** Forked
  `AlexsJones/llmfit` -> `mdyerapis-coder/llmfit` (parent confirmed). Added
  `hermes_ctl/intelligence/brains.py`: `load_brains()` adapts the llmfit
  `brains.yaml` (`~/.config/hermes/brains.yaml`) into `Brain` descriptors for
  `HttpRouter`. Strips `/chat/completions` to base url; `HERMES_BRAIN_HOST` env
  rewrites loopback -> Mac Tailscale IP (`100.109.135.0`) so the hada box reaches
  brains served on Hermes-clean. `hermesctl brains` lists them. 75 tests pass.
  Live: load_brains + HttpRouter construct verified against real brains.yaml;
  actual inference gated on the Mac being online (Tailscale probe UNREACHABLE
  this turn). NOTE: `mdyerapis-coder` is a USER account, not an org — `gh repo
  fork` must target the user (no `--org`); forked llmfit lives at
  github.com/mdyerapis-coder/llmfit.

## Cycle 15 — outbound send (`hermesctl send`).
  subcommand: `hermesctl send <email|telegram> --to X --body Y [--subject Z]`.
  Reads creds from `SecretStore`, checks egress via `NetworkPolicy`
  (fail-closed) before sending. `EmailChannel.send` (Gmail SMTP) + `TelegramChannel.send`
  (getUpdates) wired. **Live-verified both directions**: Telegram -> chat
  7620778176 (ref 17), Email self-send OK. 2 new CLI tests (blocked-without-creds,
  routes-to-channel); suite 70 passed. `contact.env` values quoted for bash-source
  safety. All 3 channels now **inbound + outbound** live.

## Cycle 14 — governed secrets + network egress seams.
  `hermes_ctl/secrets/store.py` (fail-closed `SecretStore`: Env/Dict/Bitwarden
  backends) and `hermes_ctl/secrets/network.py` (default-deny egress
  `NetworkPolicy`; `default_contact_policy` permits only Telegram/IMAP/SMTP
  hosts, strict port). `contact_daemon.py` now starts each channel only if its
  secret is present AND its egress endpoint is permitted (fail-closed). 8 new
  tests; suite 68 passed. Live: daemon restarted, all 3 channels still feed inbox.
  This addresses the prior gap: secrets were read ad-hoc from `os.environ` with
  no allowlist on egress. Still unaddressed: LLM inference not reachable from the
  box (brains run on laptop Tailscale), outbound send path, secret-health alerts.

## Cycle 13 — Phase 2: Hermes CTL CLI (`hermesctl`)
- Branch: `agent/phase2-hermes-ctl-cli` (draft PR)
- Added `candidate/phase2-hermes-ctl/hermes_ctl/cli.py`: command-line surface
  exposing the Phase 2 foundation as offline, no-secret commands:
  - `hermesctl memory <search|remember|forget>` — long-term + working memory
  - `hermesctl inbox <list|show>` — inbound SMS/Email/Telegram (reads the
    MemoryStore inbox the contact daemon fills)
  - `hermesctl identity <show|set-pref>` — profile + preferences
  - `hermesctl tasks <list|add>` — productivity task store
- Aligned all calls to the real subsystem APIs (MemoryStore.Fact.id,
  Identity.get_profile/all_preferences/set_preference, ProductivityStore).
- Added `candidate/phase2-hermes-ctl/tests/test_cli.py` (5 tests).
- Verified: `pytest tests/` -> 57 passed. Live smoke: `inbox list` shows real
  `[sms]` entries from the running daemon; `tasks add`+`list` works.
- Run: `python3 -m hermes_ctl.cli <subcommand> [args]` (env `HERMES_CTL_STORE`).
- Next: Phase 3 (Personal Intelligence) daily-briefing surface — needs live LLM
  (gated: network + brains creds per Human Approval Boundary).

## Open / blocked
- Phase B0 deployment: human authorization required (not automated).
- Phase 3+ requires live LLM routing (brains :8080/:8081) + (for Telegram/Email
  send) creds — gated human work.

## Cycle 6 — Phase 2 start: Hermes CTL memory foundation
- Branch: `agent/phase2-hermes-ctl-memory-foundation` (draft PR)
- Scaffolded `candidate/phase2-hermes-ctl/hermes_ctl/` (Phase 2 package).
- `MemoryStore`: long-term (facts + tags + TTL), working (session scratch),
  knowledge graph (typed nodes + directed edges). Stdlib-only; JSON-file
  persistence backend. No network/secrets/infra.
- Added `tests/test_memory_store.py` (8 tests: remember/recall/forget, TTL
  expiry, tag search, working-memory lifecycle, graph edges, JSON roundtrip,
  serialization). All pass.
- Added `docs/adr/0003-hermes-ctl-architecture.md` (Proposed).
- Verified: `pytest tests/` → 8 passed.
- Next bounded tasks (in order): Identity layer (user profile/prefs/context
  on MemoryStore), then Communications adapters, Productivity, Intelligence.

## Cycle 7 — Phase 2: Identity layer
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/identity/profile.py`: `Identity` built on `MemoryStore` —
  profile (merge fields), preferences (key/value + defaults), volatile context
  (working memory). Stdlib-only.
- Added `tests/test_identity.py` (5 tests: profile merge, prefs + default, key
  validation, volatile context, persistence). All pass.
- Verified: `pytest tests/` → 13 passed (8 memory + 5 identity).
- Next: Communications adapters (Email / SMS / Telegram / Contacts).

## Cycle 8 — Phase 2: Communications layer (foundation)
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/communications/channels.py`: `Message` (content-hashable),
  `Channel` (ABC transport seam), `LocalChannel` (offline in-memory transport,
  no network/credentials), `Directory` (contacts on MemoryStore).
- Real Email/SMS/Telegram transports intentionally NOT here — they need
  network + secrets (governance boundary). The `Channel` ABC is the seam
  they implement later, gated.
- Added `tests/test_communications.py` (5 tests). All pass.
- Verified: `pytest tests/` → 18 passed.
- Next: Productivity (Calendar / Tasks / Notes / CRM).

## Cycle 9 — Phase 2: Productivity layer
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/productivity/store.py`: TaskStore + NoteStore + Calendar
  (events, upcoming-window query) + CRM (entities), all on MemoryStore.
  Stdlib-only dataclasses + query logic.
- Added `tests/test_productivity.py` (5 tests). All pass.
- Verified: `pytest tests/` → 23 passed.
- Next: Information (Files / Search / Knowledge management).

## Cycle 10 — Phase 2: Information layer
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `hermes_ctl/information/index.py`: FileIndex (metadata + sha256,
  read-only scan), SearchIndex (inverted term index, AND-query), KnowledgeBase
  (thin wrapper over MemoryStore graph). Stdlib-only.
- Added `tests/test_information.py` (4 tests). All pass.
- Verified: `pytest tests/` → 27 passed.
- Next: Intelligence (local LLM routing / cloud fallback / voice / mobile).

## Cycle 12 — Phase 2: gated integrations (Telegram + live LLM routing)
- Continues branch `agent/phase2-hermes-ctl-memory-foundation` (PR #13).
- Added `communications/telegram.py`: `TelegramChannel` (Bot API) implementing
  the `Channel` seam. Token read from env/`TELEGRAM_BOT_TOKEN` at runtime, never
  stored. `send`/`received` real HTTP; offline-testable via `_post` monkeypatch.
- Added `intelligence/http_router.py`: `HttpRouter` (real `chat/completions`
  against the running llmfit-gui brains). Auth header name from `Brain`; secret
  injected at request time from env via `token_resolver`, never persisted.
- Added `tests/test_integrations.py` (5 tests). All pass.
- Verified: `pytest tests/` → 36 passed.
- **Live verified (b)**: HttpRouter hit real `:8080` (qwen3b) + `:8081`
  (hermes-7b) → both responded. No secrets required (brains open on localhost).
- Live-verified (Telegram): valid bot token from Bitwarden (`Hermes CTL bot token`
  entry, @Hermesctlrbot id 8938657874) injected into gitignored `contact.env`;
  daemon polls getUpdates every 30s; verified inbound messages land in the
  inbox (tags `inbox`+`telegram`).
- Email inbound LIVE: valid 16-char Gmail app password set in gitignored
  `contact.env` (GMAIL_APP_PASSWORD). Daemon IMAP-polls INBOX every 30s;
  verified inbound mail (incl. real recent mail + test) lands in inbox
  (tags `inbox`+`email`). All three channels (SMS/Telegram/Email) now live.
- **Live verified (Email)**: `EmailChannel.send()` delivered a test email to dyer.mason1994@gmail.com via Gmail app password (smtp.gmail.com:465). Creds from env, never stored. 4 email tests; total 40.
- **SMS (handset gateway, Option B — capcom6 SMS Gateway for Android)**: `SmsChannel` rewritten to the REAL Local Server API (Basic Auth; `POST /message`, `GET /inbox`) + `webhook_receiver.py` (HMAC-validated `sms:received` -> MemoryStore inbox). Built + 3 tests (47 total). **Live-verify deferred**: needs (1) Local Server ON in the app (Settings > Local Server, you already have it open), (2) hada box reachable from phone — join phone to the same Tailscale tailnet, or expose the webhook receiver; (3) creds from env (SMS_GATEWAY_URL/USER/PASS, SMS_WEBHOOK_SECRET). Carrier email-to-SMS ruled out (Telstra consumer gateway dead; JB Hi-Fi = Telstra MVNO).
- **Design decision (user)**: route ALL contact via the Hermes CTL
  communications seam; HADA is invoked *behind* it as the governed engineering
  worker, not the contact receiver. Keeps personal chat responsive + independent
  of the appliance's read-only gating.

## Tier 1 engineering responsiveness (separate from Phase 2)
- Cron `hada-repair-scan` (every 2h, read-only `--scan` on `mdyerapis-coder/hada`)
  created. Lists + diagnoses failing PRs; NEVER `--continue`/open/merge/deploy.
- Verified: manual scan detected PR #13 failing CI, wrote worktree + diagnosis.

## Cycle 3 — Release-manifest gate regression test
- Branch: `agent/test-release-manifest-gate` (PR #7)
- Added `tests/ci/test_release_manifests.sh`: positive (real releases/ verifies)
  + two negative cases (corrupt checksum, missing-file reference both rejected).
- Wired into `run_fast_tests.sh`. 3/3 pass; ShellCheck clean.
- Guards the `*.sha256` pattern fix so the gate cannot silently regress.

## Cycle 4 — Hermetic test for --continue stage
- Branch: `agent/test-continue-stage` (PR #8)
- `tests/ci/test_continue_stage.sh` exercises `autonomous_repair.sh --continue`
  with a stubbed `gh` + local bare mirror (no network). Proves: happy path
  opens a DRAFT PR and never calls `gh pr merge`; guardrail abort opens no PR.
- Wired into `run_fast_tests.sh`. 5/5 pass; ShellCheck clean.
- Closes the verification gap on the only previously-untested stage (Stage B).

## Cycle 5 — Wire Phase B local suite into CI
- Branch: `agent/ci-phase-b-suite` (PR #9)
- `verify.yml` now runs `workspace/tests/phase-b/run_all.sh` (B0 evidence gate,
  Gate 0f, DEPLOY_EXECUTE=0 no-remote, all 10 phase gates) on every PR/push.
  Previously only `run_fast_tests.sh` ran, so the most important deployment
  gate tests were NOT exercised in CI.
- run_all.sh is local-only (mocked SSH, no docker daemon); 19/19 pass locally.
