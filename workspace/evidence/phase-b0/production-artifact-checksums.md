# HADA M1 — Production Artifact Checksums (Final B0)

Generated: 2026-07-25
Status: Final B0 candidate correction pass complete

## Production artifacts

8382764dd8e91c017268ed0303c0cf10e2fdad7f2ad10c27fd136dcb41aa5827  deploy/compose/compose.gcp.yaml
4d84fa0e2f17db1e66943d0affcdd17259646928507b760ea7d31174a438ca5d  deploy/caddy/Caddyfile.gcp
ff134520eb5c619e1757a70fc0ff1709599d53c244309c6b61a08bc2abd3f313  scripts/provision-secrets.sh
e113db93940ddac6312e6e2c388d54f477d5cc498d4050c79665eaac75f503b5  scripts/supervisor.gcp.sh
30a98d37f9e28d207de6c6d31c02c75d9426783ea613dd6bc3b8caf40d04ae8e  scripts/validate-host.gcp.sh
462f80bea8d6e7993b380bb761ed6e4afc2ea3f943b11541c419a342475cc9c8  scripts/run-phase-b0-preflight.sh

## Candidate archive

9da95a53eac87d6b2f2860f2b3944d39d66f85882848f9a69b88f06909c14371  HADA-M1-gcp-candidate.zip

## Evidence files (Phase B0)

d6fe175a1179334b63fe01a30f639d091f3a754b0d32608e59649930aad512ac  evidence/phase-b0/code-change-compose-files.md
1fe27799ec0889939c9886928b474c4e2a04aa4f1647c40b7289c2ef4a17d902  evidence/phase-b0/compose-validation-status.md
c647cf1750f93c85fcdb00afd6989c74a6b5c2d6b92770df50f006314a7329e2  evidence/phase-b0/destructive-cleanup-plan.md
3cdb7e222de623a5f1208eec2961411d667b3e06adfe6003dc4a17112fe04026  evidence/phase-b0/preflight-plan.md
caca322c37a181ae80e7231a795b7584e1d4e85bc58b41aa4e557ea6dc8cdb63  evidence/phase-b0/production-artifact-checksums.md
34e9ea15cd8461f8794b6d1b350284d59f5f57260a10db9725437b60c4730e06  evidence/phase-b0/candidate-manifest.txt

## Shell syntax checks

PASS: run-phase-b0-preflight.sh
PASS: supervisor.gcp.sh
PASS: validate-host.gcp.sh
PASS: provision-secrets.sh
PASS: proposed-commands.sh

## Code change tests (from inside the candidate tree)

cd /tmp/hada-candidate-build/HADA-M1-durable-orchestrator
PYTHONPATH=src python3 -m pytest tests/unit/test_compose_files.py tests/unit/test_cli_config_runtime.py -v

Result: 9 passed (5 new + 4 existing)

## Docker Compose version (hada-control)

Docker Compose version v5.3.1
(>= 2.24.4 required for !override — satisfied)

## Compose config local validation

NOT VALIDATED — Docker is not installed on the local Fedora workstation.
See compose-validation-status.md for details.
Preflight script uses docker compose config --format json + stdlib json (no PyYAML dependency).
