#!/usr/bin/env python3
"""Local structural proof for the v4 Valkey durability correction."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=Loader)


def render(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    out.setdefault("services", {})
    for name, service_override in override.get("services", {}).items():
        service = out["services"].setdefault(name, {})
        for key, value in service_override.items():
            service[key] = copy.deepcopy(value)
    # Compose drops unused named volumes from its effective model. Model that
    # behavior explicitly so the regression fixture reproduces the B0 failure.
    declared = {**base.get("volumes", {}), **override.get("volumes", {})}
    used = set()
    for service in out["services"].values():
        for mount in service.get("volumes", []) or []:
            source = mount.get("source") if isinstance(mount, dict) else str(mount).split(":", 1)[0]
            if source in declared:
                used.add(source)
    out["volumes"] = {name: declared[name] for name in declared if name in used}
    return out


def mount_parts(mount):
    if isinstance(mount, dict):
        return mount.get("source"), mount.get("target"), bool(mount.get("read_only", False))
    parts = str(mount).split(":")
    return parts[0], parts[1] if len(parts) > 1 else None, len(parts) > 2 and "ro" in parts[2].split(",")


root = Path(sys.argv[1]).resolve()
base = load(root / "deploy/compose/compose.yaml")
gcp = load(root / "deploy/compose/compose.gcp.yaml")
effective = render(base, gcp)
errors: list[str] = []

volumes = effective.get("volumes", {})
if len(volumes) != 8:
    errors.append(f"expected exactly 8 effective durable volumes, got {len(volumes)}")
if "valkey-data" not in volumes:
    errors.append("valkey-data missing from effective top-level volume model")

valkey = effective["services"]["valkey"]
mounts = [mount_parts(m) for m in valkey.get("volumes", [])]
if ("valkey-data", "/data", False) not in mounts:
    errors.append("valkey must mount valkey-data at /data read-write")

opts = volumes.get("valkey-data", {}).get("driver_opts", {})
if opts.get("type") != "none" or opts.get("o") != "bind":
    errors.append("valkey-data must use type=none and o=bind")
if opts.get("device") != "/var/lib/hada/docker-volumes/valkey-data":
    errors.append("valkey-data device is not the exact protected host path")

secrets = valkey.get("secrets", [])
secret_ok = False
for secret in secrets:
    if isinstance(secret, str) and secret == "valkey_conf":
        definition = effective.get("secrets", {}).get("valkey_conf", {})
        secret_ok = definition.get("file") == "/var/lib/hada/secrets/valkey/valkey.conf"
    elif isinstance(secret, dict) and secret.get("source") == "valkey_conf":
        secret_ok = bool(secret.get("read_only", True))
if not secret_ok:
    errors.append("protected valkey.conf secret is not retained read-only")

serialized_args = json.dumps({"command": valkey.get("command"), "healthcheck": valkey.get("healthcheck")})
serialized_env = json.dumps(valkey.get("environment", {}))
for forbidden in ("VALKEY_PASSWORD", "${VALKEY_PASSWORD}", "--requirepass"):
    if forbidden in serialized_args or forbidden in serialized_env:
        errors.append(f"Valkey password material appears in args/environment: {forbidden}")

broken = copy.deepcopy(base)
broken["services"]["valkey"].pop("volumes", None)
broken_effective = render(broken, gcp)
if len(broken_effective.get("volumes", {})) != 7 or "valkey-data" in broken_effective.get("volumes", {}):
    errors.append("removing the service mount did not reproduce the seven-volume failure")

if errors:
    for error in errors:
        print(f"FAIL: {error}")
    raise SystemExit(1)
print("PASS: v4 effective Compose has eight durable volumes")
print("PASS: valkey-data is bound to /var/lib/hada/docker-volumes/valkey-data and mounted rw at /data")
print("PASS: removing the Valkey service mount reproduces seven-volume failure")
print("PASS: valkey.conf remains protected and password-free in Valkey args/environment")
