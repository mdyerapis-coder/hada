from __future__ import annotations

import socket
import urllib.error
import urllib.request
from pathlib import Path

from prometheus_client import CollectorRegistry
from typer.testing import CliRunner

from hada.cli import app
from hada.config import load_config
from hada.runtime import ProbeServer, RuntimeHealth


runner = CliRunner()


def test_load_and_validate_config() -> None:
    path = Path(__file__).parents[2] / "config" / "hada.yaml"
    config = load_config(path)
    assert config.project.name == "HADA"
    assert len(config.execution.rules) == 5
    result = runner.invoke(app, ["validate-config", "--config", str(path)])
    assert result.exit_code == 0
    assert "valid" in result.stdout


def test_validate_config_can_enforce_future_target_stop() -> None:
    path = Path(__file__).parents[2] / "config" / "hada.yaml"
    result = runner.invoke(
        app,
        ["validate-config", "--config", str(path), "--require-target"],
    )
    assert result.exit_code == 2
    assert "stop condition" in result.stdout


def test_key_generation_and_offline_evidence_cli(tmp_path: Path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    result = runner.invoke(
        app,
        [
            "keys",
            "generate",
            "--private-key",
            str(private_key),
            "--public-key",
            str(public_key),
        ],
    )
    assert result.exit_code == 0
    assert private_key.exists() and public_key.exists()
    second = runner.invoke(
        app,
        [
            "keys",
            "generate",
            "--private-key",
            str(private_key),
            "--public-key",
            str(public_key),
        ],
    )
    assert second.exit_code == 2


def test_probe_server_health_and_readiness() -> None:
    health = RuntimeHealth()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = ProbeServer("127.0.0.1", port, health, CollectorRegistry())
    server.start()
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz").status == 200
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz")
            raise AssertionError("unready probe unexpectedly succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 503
        health.update(database=True, queue=True)
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz").status == 200
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").status == 200
    finally:
        server.stop()
