# Hermes CTL — Phase 2 Personal AI Operating Environment

A stdlib-only personal AI operating environment that puts memory, communications,
productivity, identity, intelligence, and secrets management under a single
command-line interface — designed for governed, offline-testable autonomy.

## Quick Start

```bash
# Clone and install
git clone <repo> candidate/phase2-hermes-ctl
cd candidate/phase2-hermes-ctl

# Install (editable, recommended for development)
pip install -e .

# Or install with test deps
pip install -e ".[test]"

# Run tests
pytest

# Run the CLI
hermesctl --help
```

No external dependencies. Requires Python ≥ 3.11.

## CLI Reference

```
hermesctl <command> [subcommand] [options]
```

| Command         | Subcommands                              | Description                        |
|-----------------|------------------------------------------|------------------------------------|
| `memory`        | `search`, `remember`, `forget`           | Long-term + working memory         |
| `inbox`         | `list`, `show`                           | Inbound SMS / Email / Telegram     |
| `identity`      | `show`, `set-pref`                       | Profile + preferences              |
| `tasks`         | `list`, `add`                            | Productivity task store            |
| `notes`         | `add`, `list`                            | Knowledge notes                    |
| `calendar`      | `add`, `upcoming`                        | Events                             |
| `crm`           | `add`, `find`                            | Entity / contact management        |
| `brains`        | `load`, `status`                         | Intelligence brain modules         |
| `briefing`      | (built-in)                               | Daily briefing generation          |
| `finance`       | `scan`, `budget`, `expense`              | Financial snapshot & tracking      |
| `context`       | (built-in)                               | Session context management         |
| `curation`      | `list`, `schedule`                       | Content curation                   |
| `habit`         | `track`, `report`                        | Habit tracking                     |
| `health`        | `log`, `status`                          | Health metrics                     |
| `plan`          | `create`, `review`                       | Planning                           |
| `relationships` | `add`, `query`                           | Relationship modelling             |
| `remind`        | `set`, `list`                            | Reminders                          |
| `router`        | (built-in)                               | Intent routing                     |
| `shopping`      | `add`, `list`                            | Shopping list                      |
| `travel`        | `plan`, `status`                         | Travel planning                    |
| `send`          | `email`, `telegram`                      | Outbound messages (gated)          |

**Environment**:
- `HERMES_CTL_STORE` — path to the persistent store file
- `GMAIL_SMTP_USER` / `GMAIL_APP_PASSWORD` — SMTP credentials (outbound email)
- `TELEGRAM_BOT_TOKEN` — Telegram bot token (outbound messages)

## Architecture

Seven subsystems built on a common MemoryStore foundation:

```
┌─────────────────────────────────────────────────────┐
│                     hermesctl CLI                     │
│              (argparse, hermes_ctl/cli.py)            │
├──────────┬──────────┬──────────┬─────────────────────┤
│  Memory   │  Comms   │ Identity │   Productivity       │
│  Store    │  SMS     │ Profile  │   Tasks / Notes      │
│  Facts    │  Email   │ Prefs    │   Calendar / CRM     │
│  Graph    │ Telegram │          │                      │
├──────────┴──────────┴──────────┴─────────────────────┤
│  Intelligence                                         │
│  Brains · Briefing · Context · Curation · Finance     │
│  Habit · Health · Plan · Relationships · Remind       │
│  Router · Shopping · Travel · HTTP Router             │
├──────────────────────────────────────────────────────┤
│  Information                    │  Secrets             │
│  Full-text index                │  SecretStore         │
│  Knowledge retrieval            │  EnvSecretStore      │
│                                 │  Bitwarden support   │
│                                 │  Network policy      │
└─────────────────────────────────────────────────────┘
```

### 1. **Memory** (`hermes_ctl/memory/`)
Long-term memory (tagged facts with expiry), working memory (session-scoped scratch),
and knowledge graph (typed nodes + edges). Persistence via in-memory or JSON file.
Stdlib-only — no database dependency.

### 2. **Communications** (`hermes_ctl/communications/`)
Inbound/outbound message channels: SMS (CLI / file-based), Email (SMTP IMAP),
Telegram bot, webhook receiver, and the contact daemon that routes messages.
All egress is gated by NetworkPolicy (fail-closed default-deny).

### 3. **Identity** (`hermes_ctl/identity/`)
User profile with preference storage. Pluggable back-end for future sync.

### 4. **Productivity** (`hermes_ctl/productivity/`)
Tasks, Notes, Events, and CRM Entities backed by MemoryStore. Durable, queryable,
and offline-testable.

### 5. **Information** (`hermes_ctl/information/`)
Full-text indexing and knowledge retrieval — context-free search across stored facts.

### 6. **Intelligence** (`hermes_ctl/intelligence/`)
14 brain modules covering daily briefing, finance scanning, habit/health tracking,
content curation, planning, relationships, reminders, intent routing, shopping,
and travel. The `loader` (`brains.py`) discovers and registers all modules.

### 7. **Secrets & Network** (`hermes_ctl/secrets/`)
Multi-backend secret store (EnvSecretStore, DictSecretStore, BitwardenSecretStore)
and a fail-closed NetworkPolicy that defaults to deny all egress. Channels consult
NetworkPolicy before opening connections — the system is secure by default.

## State

**Phase 2 foundation** — all seven subsystems are scaffolded with working implementations.

- **34 source files** across the `hermes_ctl/` package
- **300+ tests** (24 test modules) covering all subsystems
- **259 tests passing**, 41 known failures tracked for resolution
- **Stdlib-only** — zero external dependencies
- **Fail-closed** — egress requires explicit allowlist registration
- **Offline-testable** — pure logic, no sockets opened during tests

## Development

```bash
# Run all tests
pytest

# Run a specific test module
pytest tests/test_memory_store.py -v

# Run with verbose output
pytest -v

# Show active failures
pytest --tb=short -q
```

No build steps. No external services required for local testing.
