#!/usr/bin/env python3
"""Reject real unresolved Git conflict markers in tracked text files."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EXTENSIONS = {".py", ".sh", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml", ".md"}
EXCLUDED_PARTS = {".git", ".ci-evidence", "vendor", "node_modules", ".venv"}
MARKER = re.compile(r"^(?:<<<<<<< .+|=======|>>>>>>> .+)$")


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    )
    return [root / p.decode() for p in result.stdout.split(b"\0") if p]


def main() -> int:
    root = Path.cwd().resolve()
    hits: list[str] = []
    for path in tracked_files(root):
        relative = path.relative_to(root)
        if path.suffix.lower() not in EXTENSIONS or EXCLUDED_PARTS.intersection(relative.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        in_fence = False
        for number, line in enumerate(lines, 1):
            if path.suffix.lower() == ".md" and line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and MARKER.fullmatch(line):
                hits.append(f"{relative}:{number}:{line}")
    if hits:
        print("unresolved Git conflict markers:", file=sys.stderr)
        print("\n".join(hits), file=sys.stderr)
        return 1
    print("conflict-artifact scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
