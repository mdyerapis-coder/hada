# Hermes CTL Unified App Surface — Integration PR

## Summary

This PR delivers Phase 2 **integrated app surface** for Hermes CTL. The codebase has been stabilized (41 test failures fixed), packaged for pip install, refactored into a modular CLI architecture, and extended with the missing Information subsystem integration and cross-module integration tests.

**Branch:** `agent/hermes-ctl-integration` (from `main`)
**No merge without approval — draft only.**

---

## What was done

### 1. Package infrastructure (`pyproject.toml`, `README.md`, `MANIFEST.in`)
- Created `candidate/phase2-hermes-ctl/pyproject.toml` with setuptools build, version `0.2.0`, `hermesctl` CLI entry point, pytest config
- Wrote comprehensive `README.md` with Quick Start, CLI reference, architecture overview (7 subsystems), and test status
- Added `MANIFEST.in` for source distributions

### 2. Fixed 41 failing tests (300 → 300 passing)
**Root causes:**
- **CLI parser duplication** (lines 768-769 in `cli.py`): `curate` and `consolidate` subparsers registered twice → `ArgumentError` killed `build_parser()`. Removed duplicate definitions.
- **Relationships free-function data model mismatch**: `scan_relationships()`, `update_relationship()`, `record_interaction()` returned `dict`/`list` but tests expected rich dataclass instances (`Relationship` with `person_id`, `relationship_type`, `strength`, `contact_count`, etc.)
- **Missing `Relationships.interactions()` method**: The class only had `interactions_for(person)`; tests called the bare `interactions()`
- **Missing graph node creation**: `Relationships.add()` stored facts but didn't create `MemoryStore.add_node()` entries

**Fix approach** (minimal, non-breaking):
- Added `StoredRelationship` dataclass with all fields tests expect (person_id, name, relationship_type, strength, contact_count, last_contacted, channels, tags, notes)
- Added `RelationshipSnapshot` dataclass (total_count, by_type, relationships, recent_contacts, timestamp)
- Rewrote free functions to return these dataclasses, delegating to MemoryStore
- Added `interactions(person=None, limit=20)` dispatching to `interactions_for()`
- Added graph node creation to `Relationships.add()`
- Kept the modern `Relationships` class and its `Relationship(person, relation, ...)` dataclass completely unchanged

### 3. CLI refactored into modular architecture (952-line file → 14 module files)

The monolithic `cli.py` was split into a `hermes_ctl/cli/` package:

```
cli/
  __init__.py              # Re-exports for monkeypatch compat (0 inserted, 5 lines)
  __main__.py              # python3 -m support
  main.py                  # build_parser() + main() assembler
  store.py                 # Shared _store() helper
  memory_commands.py       # memory search/remember/forget/curate/consolidate
  inbox_commands.py        # inbox list/show
  identity_commands.py     # identity show/set-pref
  productivity_commands.py # tasks, notes, calendar
  crm_commands.py          # CRM entities + rel-add/rel-list/rel-log/rel-recent/rel-dates
  comms_commands.py        # send email/telegram
  intel_commands.py        # brains, context, briefing, plan, remind
  lifestyle_commands.py    # shopping, travel, finance
  information_commands.py  # NEW — information index/search/status
```

`cli.py` is now an 11-line backward-compat re-export stub.

### 4. Information subsystem CLI integration (NEW)

The existing `FileIndex` and `SearchIndex` classes (`hermes_ctl/information/`) now have CLI commands:

```
hermesctl information index <path>    # Index files into MemoryStore
hermesctl information search <query>  # Search indexed file records
hermesctl information status          # Show file index stats
```

Directory indexing auto-lists files (non-recursive by default, `--recursive` for subdirectories). Each file gets a `FileRecord` (path, size, sha256, mtime) in MemoryStore.

### 5. Cross-module integration tests (12 new tests)

`tests/test_integration_workflow.py` validates:
- MemoryStore ↔ ProductivityStore: tasks/notes queryable via MemoryStore.search()
- Relationships ↔ MemoryStore: facts + graph nodes shared
- FileIndex ↔ MemoryStore: indexed files persist and are searchable
- CLI end-to-end: memory → tasks → notes via command line
- CLI information: status → index → search
- Shared persistence: same JSON file backed by all modules
- CLI help: confirms all 18 subcommands registered

---

## Files changed

### New files (14)
- `candidate/phase2-hermes-ctl/pyproject.toml`
- `candidate/phase2-hermes-ctl/README.md`
- `candidate/phase2-hermes-ctl/MANIFEST.in`
- `candidate/phase2-hermes-ctl/hermes_ctl/cli/` (12 files)
- `candidate/phase2-hermes-ctl/tests/test_integration_workflow.py`

### Modified files (3)
- `hermes_ctl/cli.py` — 952 lines → 11-line re-export stub
- `hermes_ctl/intelligence/relationships.py` — added `StoredRelationship`, `RelationshipSnapshot` dataclasses + rewritten free functions + `interactions()` method + graph node creation
- `.ci-evidence/guardrail-scan.txt` — auto-updated by git status

---

## Test suite status

```
312 passed in 3.98s
  - 300 original tests
  - 12 new integration tests
  - 0 failures, 0 errors
```

---

## Next steps (unblocks)

With this integration surface in place, the following can proceed:

1. **TUI dashboard** — A Textual-based terminal UI using the modular `cli/` modules as backend
2. **Web API** — FastAPI/Starlette wrapper over the same modules, served as REST + WebSocket
3. **Mobile companion** — React Native or Flutter app consuming the web API
4. **pip-installable deployment** — `pip install hermes-ctl` for any Linux box
5. **CI workflow** — GitHub Actions matrix test on the now-clean 312-pass suite
