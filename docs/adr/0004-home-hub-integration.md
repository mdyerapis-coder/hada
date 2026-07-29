# ADR 0004 — Home Hub Integration Architecture (Phase 4)

- Status: Proposed
- Date: 2026-07-29
- Phase: 4 (Home Hub Integration)
- Supersedes: —
- Prerequisites: Phase 3 complete (ADR 0003 Hermes CTL base)

## Context

Phase 3 (Personal Intelligence — 11 offline modules, 294 tests) is complete
and merged to `main`. The roadmap now advances to Phase 4: integrating
household services (shopping, inventory, pantry, calendar, family tasks,
smart home, cameras, notifications, dashboards, household automation).

Phase 4 is distinct from Phase 3 in two ways:

1. **External services.** Most integrations connect to real third-party
   systems (grocery APIs, calendar providers, IoT hubs, camera streams).
   These require live creds, network access, and human authorization —
   they are governance-boundary items, not pure stdlib modules.
2. **Existing seams.** Several Phase 4 domains already have foundation code
   in Hermes CTL: shopping (Phase 3), calendar/tasks (Phase 2 Productivity),
   notifications (Phase 2 Communications Channels), dashboards (deployed
   Command Centre). The work is wiring, not rebuilding.

## Decision

Phase 4 integrations follow a three-layer pattern:

```
External Service  →  Adapter (thin, in-repo)  →  Hermes CTL Seam
                                                   (MemoryStore, Channel,
                                                    CLI, Intelligence)
```

### Layer 1: External services (not in-repo)
- Live APIs (Grocy for pantry, Home Assistant for IoT, Google Calendar,
  camera RTSP streams, etc.).
- Credentials managed via env/SecretStore, never committed.
- Configuration loaded at request time.

### Layer 2: Adapters (in-repo, stdlib + requests)
- One Python module per integration under `hermes_ctl/integrations/`.
- Implements an ABC from the existing Hermes CTL seam.
- Offline-testable via monkeypatched HTTP layer.
- Manifest-loaded: `integrations.yaml` declares which adapters are
  enabled and their env-var bindings.

### Layer 3: Existing Hermes CTL seams (no change to foundation)
- `Productivity` (Tasks, Notes, Calendar, CRM) for household planning.
- `Channel` ABC for notification delivery.
- `MemoryStore` for persistence across services.
- `Intelligence` (Brain/Router) for cross-domain reasoning.
- `CLI` (`hermesctl`) for query and control.

### First-build order (inside the autonomous build loop)

| Step | Item | Offline-testable | Gate |
|------|------|-----------------|------|
| 1 | Inventory module (stdlib) | ✅ | Phase 3 pattern |
| 2 | Pantry module (stdlib) | ✅ | Phase 3 pattern |
| 3 | Calendar sync adapter (HTTP) | ⚠️ (monkeypatch) | Creds |
| 4 | Smart home adapter (HTTP) | ⚠️ (monkeypatch) | Creds |
| 5 | Camera health adapter | ⚠️ (monkeypatch) | Creds |
| 6 | Dashboards & notifications wiring | ⚠️ | Bot token |
| 7 | Household automation rules | ✅ (in-memory) | — |

Items 1–2 are pure stdlib modules following the Phase 3 5-layer pattern
(dataclass → scan → deliver → CLI → tests). Items 3–6 are gated on
secrets/infra and may be deferred to a human-authorized batch.

### Non-goals
- No embedded IoT hub, camera NVR, or appliance control logic in HADA.
- No cloud dependency added to the core Hermes CTL package.
- No credential storage on disk in the repo.

## Consequences

1. **Pros:** Clear separation — foundation code stays pure and testable;
   adapters are thin and replaceable; existing seams are reused.
2. **Cons:** External integrations will lag behind adapter definitions
   (gated on human authorization for live creds).
3. **Mitigation:** Offline-testable adapters with monkeypatch verify
   integration logic without network; live verification is a separate
   authorized step.

## Status

Proposed. To become Accepted after at least one Phase 4 adapter is
delivered, verified, and its PR reaches draft-plus-review state.
