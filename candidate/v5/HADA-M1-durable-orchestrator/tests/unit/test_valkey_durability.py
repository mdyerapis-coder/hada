"""Structural regression tests for durable Valkey storage."""
from __future__ import annotations

from pathlib import Path

import yaml


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict:
    with (ROOT / "deploy/compose" / name).open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=Loader)


def test_valkey_data_is_mounted_writable() -> None:
    valkey = _load("compose.yaml")["services"]["valkey"]
    assert "valkey-data:/data" in valkey["volumes"]
    assert all(not str(mount).endswith(":ro") for mount in valkey["volumes"] if str(mount).startswith("valkey-data:"))


def test_valkey_bind_definition_is_exact() -> None:
    opts = _load("compose.gcp.yaml")["volumes"]["valkey-data"]["driver_opts"]
    assert opts == {
        "type": "none",
        "o": "bind",
        "device": "/var/lib/hada/docker-volumes/valkey-data",
    }


def test_valkey_secret_and_password_absence_are_preserved() -> None:
    base = _load("compose.yaml")
    valkey = base["services"]["valkey"]
    assert "valkey_conf" in valkey["secrets"]
    assert base["secrets"]["valkey_conf"]["file"] == "/var/lib/hada/secrets/valkey/valkey.conf"
    assert "VALKEY_PASSWORD" not in valkey.get("environment", {})
    assert "--requirepass" not in repr(valkey.get("command", []))
