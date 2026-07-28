from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceHealth:
    service: str
    healthy: bool
    status: str


def compose_health(compose_files: list[str] | str) -> list[ServiceHealth]:
    if isinstance(compose_files, str):
        compose_files = [compose_files]
    cmd: list[str] = ["docker", "compose"]
    for path in compose_files:
        cmd.extend(["-f", path])
    cmd.extend(["ps", "--format", "json"])
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    import json

    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    health: list[ServiceHealth] = []
    for row in rows:
        state = str(row.get("State", "unknown"))
        status = str(row.get("Status", state))
        healthy = state.lower() == "running" and "unhealthy" not in status.lower()
        health.append(ServiceHealth(str(row.get("Service", "unknown")), healthy, status))
    return health
