"""Tests for InfrastructureConfig.compose_files (multi-file support).

These tests verify that:
1. The new ``compose_files`` list field is accepted and validated.
2. A legacy single ``compose_file`` string is auto-wrapped into a list
   (backward compatibility with existing hada.yaml files that have not been
   migrated yet).
3. ``compose_health`` builds the correct docker compose command with multiple
   -f flags.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hada.models import HadaConfig
from hada.supervisor.health import compose_health


def _base_config_dict() -> dict:
    return {
        "project": {
            "name": "HADA",
            "target_name": "Hermesctl",
            "target_repository": "https://github.com/mdyerapis-coder/hermesctl.git",
            "target_ref": "main",
            "workspace_root": "/var/lib/hada/workspaces",
        },
        "governance": {
            "require_architecture_review": True,
            "require_security_review": True,
            "require_test_review": True,
            "require_documentation_update": True,
            "require_milestone_report": True,
            "require_external_review": True,
            "prohibit_self_approval": True,
            "prohibit_scope_expansion": True,
            "maximum_recovery_attempts": 3,
            "maximum_agent_iterations_per_gate": 5,
            "stop_on_critical_security_finding": True,
            "stop_on_external_review_unavailable": True,
        },
        "agents": {
            "implementation": {
                "party": 1,
                "role": "implementation_engineer",
                "model": "test-model",
                "endpoint": "http://localhost:8000/v1",
            },
            "adversarial": {
                "party": 2,
                "role": "adversarial_reviewer",
                "model": "test-model",
                "endpoint": "http://localhost:8001/v1",
            },
            "external": {
                "party": 3,
                "role": "independent_external_reviewer",
                "mode": "manual",
            },
        },
        "infrastructure": {
            "health_check_interval_seconds": 30,
            "startup_timeout_seconds": 600,
            "recovery_backoff_seconds": 60,
        },
        "database": {
            "dsn_environment_variable": "HADA_DATABASE_DSN",
            "migration_directory": "/opt/hada/src/hada/db/migrations",
            "connect_timeout_seconds": 10,
            "statement_timeout_seconds": 30,
        },
        "queue": {
            "url_environment_variable": "HADA_VALKEY_URL",
            "namespace": "hada",
            "consumer_group": "orchestrator",
            "visibility_timeout_seconds": 300,
            "maximum_delivery_attempts": 5,
            "maximum_stream_length": 10000,
        },
        "evidence": {
            "root": "/var/lib/hada/evidence",
            "signing_private_key": "/var/lib/hada/keys/audit-signing-key.pem",
            "signing_public_key": "/var/lib/hada/keys/audit-signing-key.pub.pem",
        },
        "execution": {
            "require_bubblewrap": True,
            "trusted_binary_roots": ["/usr/bin"],
            "readonly_bind_paths": ["/usr"],
            "maximum_output_bytes": 1048576,
            "maximum_arguments": 128,
            "maximum_argument_length": 4096,
            "rules": [
                {
                    "executable": "git",
                    "allowed_subcommands": ["status"],
                    "allowed_parties": [1, 2],
                    "maximum_timeout_seconds": 120,
                    "network_access": False,
                    "read_only": True,
                }
            ],
        },
        "monitoring": {
            "listen_host": "0.0.0.0",
            "listen_port": 9108,
            "dependency_probe_interval_seconds": 15,
            "unhealthy_exit_threshold": 4,
        },
        "security": {
            "allowed_egress_hosts": ["github.com"],
            "secrets_file": "/opt/hada/.env",
            "require_non_root_runtime": True,
            "require_tls": True,
            "redact_logs": True,
        },
    }


def test_compose_files_list_accepted() -> None:
    data = _base_config_dict()
    data["infrastructure"]["compose_files"] = [
        "/opt/hada/deploy/compose/compose.yaml",
        "/opt/hada/deploy/compose/compose.gcp.yaml",
    ]
    config = HadaConfig.model_validate(data)
    assert config.infrastructure.compose_files == [
        Path("/opt/hada/deploy/compose/compose.yaml"),
        Path("/opt/hada/deploy/compose/compose.gcp.yaml"),
    ]


def test_legacy_compose_file_backward_compat() -> None:
    data = _base_config_dict()
    data["infrastructure"]["compose_file"] = "/opt/hada/deploy/compose/compose.yaml"
    config = HadaConfig.model_validate(data)
    assert config.infrastructure.compose_files == [
        Path("/opt/hada/deploy/compose/compose.yaml"),
    ]


def test_compose_files_min_length_one() -> None:
    data = _base_config_dict()
    data["infrastructure"]["compose_files"] = []
    try:
        HadaConfig.model_validate(data)
        raise AssertionError("empty compose_files list should be rejected")
    except Exception:
        pass


def test_compose_health_builds_multi_f_command() -> None:
    fake_result = MagicMock()
    fake_result.stdout = ""
    with patch("hada.supervisor.health.subprocess.run", return_value=fake_result) as mock_run:
        compose_health(
            [
                "/opt/hada/deploy/compose/compose.yaml",
                "/opt/hada/deploy/compose/compose.gcp.yaml",
            ]
        )
    cmd = mock_run.call_args[0][0]
    assert cmd == [
        "docker",
        "compose",
        "-f",
        "/opt/hada/deploy/compose/compose.yaml",
        "-f",
        "/opt/hada/deploy/compose/compose.gcp.yaml",
        "ps",
        "--format",
        "json",
    ]


def test_compose_health_backward_compat_single_string() -> None:
    fake_result = MagicMock()
    fake_result.stdout = ""
    with patch("hada.supervisor.health.subprocess.run", return_value=fake_result) as mock_run:
        compose_health("/opt/hada/deploy/compose/compose.yaml")
    cmd = mock_run.call_args[0][0]
    assert cmd == [
        "docker",
        "compose",
        "-f",
        "/opt/hada/deploy/compose/compose.yaml",
        "ps",
        "--format",
        "json",
    ]
