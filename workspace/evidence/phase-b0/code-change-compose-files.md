# HADA Code Change: compose_file → compose_files (Multi-File Support)

Generated: 2026-07-25
Status: Implemented and tested locally

## Problem

The `InfrastructureConfig` model in `src/hada/models.py` declared:

    compose_file: Path

This is a single filesystem path. The production GCP deployment uses TWO
compose files (base + override):

    docker compose -f deploy/compose/compose.yaml -f deploy/compose/compose.gcp.yaml ...

The Phase A deployment plan proposed stuffing shell arguments into the
`compose_file` YAML value:

    compose_file: /opt/hada/deploy/compose/compose.yaml -f /opt/hada/deploy/compose/compose.gcp.yaml

This is incorrect because:
1. Pydantic's `Path` type cannot parse a string containing spaces and `-f`
   flags — it would create a single path with spaces in the filename.
2. The `compose_health()` function in `src/hada/supervisor/health.py` passes
   the value as a single `-f` argument:
       ["docker", "compose", "-f", compose_file, "ps", "--format", "json"]
   This would produce a single invalid file path rather than two `-f` flags.

## Solution

### 1. models.py — compose_files: list[Path]

Changed `InfrastructureConfig`:

    compose_files: list[Path] = Field(min_length=1)

Added a `model_validator(mode="before")` that accepts the legacy single
`compose_file` string and wraps it into a one-element list. This provides
backward compatibility with existing hada.yaml files that have not been
migrated yet.

### 2. supervisor/health.py — multi-file compose_health()

Changed `compose_health()` to accept `list[str] | str`:

    def compose_health(compose_files: list[str] | str) -> list[ServiceHealth]:
        if isinstance(compose_files, str):
            compose_files = [compose_files]
        cmd: list[str] = ["docker", "compose"]
        for path in compose_files:
            cmd.extend(["-f", path])
        cmd.extend(["ps", "--format", "json"])

This builds the correct `docker compose -f A -f B ps --format json` command
with each file as a separate `-f` flag. A single string is still accepted
for backward compatibility.

### 3. config/hada.yaml — compose_files list

Updated the shipped config:

    infrastructure:
      compose_files:
        - /opt/hada/deploy/compose/compose.yaml
        - /opt/hada/deploy/compose/compose.gcp.yaml

### 4. Tests — tests/unit/test_compose_files.py

Created 5 tests:
- test_compose_files_list_accepted — list of two paths is accepted
- test_legacy_compose_file_backward_compat — single string auto-wrapped
- test_compose_files_min_length_one — empty list rejected
- test_compose_health_builds_multi_f_command — correct docker command
- test_compose_health_backward_compat_single_string — single string still works

All 5 new tests pass. All 4 existing tests in test_cli_config_runtime.py
also pass (the shipped hada.yaml now uses compose_files, and the config
loads correctly).

## Files changed locally (not on hada-control)

- src/hada/models.py
- src/hada/supervisor/health.py
- config/hada.yaml
- tests/unit/test_compose_files.py (new)

## Verification

    cd /opt/hada
    PYTHONPATH=src python3 -m pytest tests/unit/test_compose_files.py tests/unit/test_cli_config_runtime.py -v

Result: 9 passed (5 new + 4 existing).

## Deployment note

The updated hada.yaml with `compose_files` list is the production config for
GCP. The backward-compatible validator means that if the old `compose_file`
key is still present (e.g., from the shipped archive before the change), the
config will still load correctly with a single-element list.

On the VM, the config update is done by replacing the file, not by sed
patching. The production scripts (supervisor.gcp.sh, validate-host.gcp.sh)
hardcode both `-f` flags and do not depend on the hada.yaml compose_files
value for their compose commands.
