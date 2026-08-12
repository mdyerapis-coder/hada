#!/usr/bin/env python3
"""Inventory HADA source copies and report tracked-file divergence.

This is intentionally read-only: it hashes only pyproject.toml and Dockerfile
inside directories named HADA-M1-durable-orchestrator and never edits archives.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import zipfile


PROJECT = "HADA-M1-durable-orchestrator"
CHECKED_FILES = ("pyproject.toml", "Dockerfile")
DEFAULT_CANONICAL = Path("workspace/deploy-v4") / PROJECT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def discover(root: Path) -> list[Path]:
    """Return HADA trees containing both source-of-truth files."""
    trees = []
    for path in root.rglob(PROJECT):
        if not path.is_dir() or ".git" in path.parts:
            continue
        if all((path / name).is_file() for name in CHECKED_FILES):
            trees.append(path)
    return sorted(set(trees))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--canonical", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    canonical = (args.canonical or root / DEFAULT_CANONICAL).resolve()
    trees = discover(root)
    archives = sorted(
        path for path in root.rglob("*.zip")
        if ".git" not in path.parts and PROJECT in path.name
    )
    print(f"Canonical: {canonical.relative_to(root) if canonical.is_relative_to(root) else canonical}")
    print(f"HADA source copies ({len(trees)}):")
    for tree in trees:
        relative = tree.relative_to(root)
        print(f"  {relative}")
        for name in CHECKED_FILES:
            print(f"    {name}: {sha256(tree / name)}")
    print(f"HADA archives ({len(archives)}):")
    for archive in archives:
        members = []
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if member.endswith(CHECKED_FILES):
                    members.append(member)
        relative = archive.relative_to(root)
        print(f"  {relative} ({len(members)} checked-file entries)")
        for member in members:
            print(f"    {member}")

    if canonical not in trees:
        print(f"ERROR: canonical tree is missing required files: {canonical}")
        return 2

    canonical_hashes = {name: sha256(canonical / name) for name in CHECKED_FILES}
    divergences = []
    for tree in trees:
        for name, expected in canonical_hashes.items():
            actual = sha256(tree / name)
            if actual != expected:
                divergences.append((tree.relative_to(root), name, expected, actual))

    if divergences:
        print("DIVERGENCE:")
        for tree, name, expected, actual in divergences:
            print(f"  {tree}/{name}: canonical={expected} actual={actual}")
        return 1

    print("No divergence detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
