#!/usr/bin/env python3
"""Fail-closed lease and isolated-worktree guard for HADA build cycles."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

BUSY = 75
DEFAULT_STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hada-build"


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        args, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=env
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{detail}")
    return result.stdout.strip()


@contextmanager
def _locked(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "guard.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid state file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid state file {path}: expected object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _remove_worktree(lease: dict[str, Any], state_dir: Path) -> None:
    token = str(lease.get("token", ""))
    raw_worktree = str(lease.get("worktree", ""))
    raw_repo = str(lease.get("repo", ""))
    if not token or not raw_worktree or not raw_repo:
        raise RuntimeError("lease is missing token/repo/worktree")
    worktree = Path(raw_worktree).resolve()
    worktree_root = (state_dir / "worktrees").resolve()
    if worktree.parent != worktree_root or worktree.name != token:
        raise RuntimeError(f"unsafe worktree path in lease: {worktree}")
    repo = Path(raw_repo).resolve()
    if worktree.exists() and repo.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    if worktree and worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)


def prepare(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state_dir = Path(args.state_dir).resolve()
    if args.ttl < 60 or args.ttl > 7200:
        raise RuntimeError("ttl must be between 60 and 7200 seconds")
    if not (repo / ".git").exists():
        raise RuntimeError(f"not a git checkout: {repo}")

    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        existing = _read_json(lease_path)
        recovered = False
        now = int(time.time())
        if existing:
            expires_at = int(existing.get("expires_at", 0))
            if expires_at > now:
                print(
                    json.dumps({"status": "busy", "message": "active lease", "expires_at": expires_at}),
                    file=sys.stderr,
                )
                return BUSY
            _remove_worktree(existing, state_dir)
            incidents = state_dir / "incidents"
            incidents.mkdir(exist_ok=True)
            _write_json(incidents / f"stale-{now}.json", existing)
            lease_path.unlink(missing_ok=True)
            recovered = True

        _run(["git", "fetch", "--prune", "origin", "main"], cwd=repo, timeout=args.command_timeout)
        base_sha = _run(["git", "rev-parse", "origin/main"], cwd=repo)
        token = secrets.token_hex(16)
        branch = f"agent/build-cycle-{now}-{token[:8]}"
        worktrees = state_dir / "worktrees"
        worktrees.mkdir(exist_ok=True)
        worktree = worktrees / token
        _run(["git", "worktree", "add", "--detach", str(worktree), base_sha], cwd=repo, timeout=args.command_timeout)
        _run(["git", "switch", "-c", branch], cwd=worktree)
        lease = {
            "version": 1,
            "token": token,
            "repo": str(repo),
            "worktree": str(worktree),
            "branch": branch,
            "base_sha": base_sha,
            "started_at": now,
            "expires_at": now + args.ttl,
            "status": "active",
        }
        _write_json(lease_path, lease)
        print(json.dumps({**lease, "recovered_stale_lease": recovered}, sort_keys=True))
        return 0


def _quarantine(lease_path: Path, lease: dict[str, Any], reason: str) -> None:
    lease["status"] = "quarantined"
    lease["quarantine_reason"] = reason[:2000]
    lease["updated_at"] = int(time.time())
    _write_json(lease_path, lease)


def _conflict_markers(worktree: Path) -> list[str]:
    files = _run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=worktree
    ).splitlines()
    marker = re.compile(r"^(?:<<<<<<< |=======$|>>>>>>> )")
    hits: list[str] = []
    for relative in files:
        path = worktree / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(errors="strict").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if marker.match(line):
                hits.append(f"{relative}:{number}")
    return hits


def _default_healthcheck(worktree: Path, timeout: int) -> None:
    env = os.environ.copy()
    env["HADA_REPAIR_VERIFY"] = "1"
    _run(["bash", "scripts/ci/run_fast_tests.sh"], cwd=worktree, timeout=timeout, env=env)
    candidate = worktree / "candidate/phase2-hermes-ctl"
    if candidate.exists():
        py = Path.home() / ".hermes/hermes-agent/venv/bin/python"
        python = str(py) if py.exists() else sys.executable
        _run(
            [python, "-m", "compileall", "-q", "hermes_ctl"],
            cwd=candidate,
            timeout=timeout,
            env=env,
        )
        test_env = env.copy()
        test_env["PYTHONPATH"] = str(candidate)
        _run(
            [python, "-m", "pytest", "tests", "-q"],
            cwd=candidate,
            timeout=timeout,
            env=test_env,
        )


def verify(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    if args.command_timeout < 1 or args.command_timeout > 1800:
        raise RuntimeError("command-timeout must be between 1 and 1800 seconds")
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            raise RuntimeError("no active lease")
        if not secrets.compare_digest(str(lease.get("token", "")), args.token):
            raise RuntimeError("lease token mismatch")
        if lease.get("status") != "active":
            raise RuntimeError(f"lease is not active: {lease.get('status')}")
        repo = Path(str(lease["repo"]))
        worktree = Path(str(lease["worktree"]))
        try:
            _run(["git", "fetch", "--prune", "origin", "main"], cwd=repo, timeout=args.command_timeout)
            current_base = _run(["git", "rev-parse", "origin/main"], cwd=repo)
            if current_base != lease["base_sha"]:
                raise RuntimeError(
                    f"origin/main moved: prepared {lease['base_sha']}, current {current_base}"
                )
            if _run(["git", "status", "--porcelain"], cwd=worktree):
                raise RuntimeError("worktree is dirty; commit the bounded change before verification")
            head = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
            if head == lease["base_sha"]:
                raise RuntimeError("cycle has no committed change")
            markers = _conflict_markers(worktree)
            if markers:
                raise RuntimeError("unresolved conflict markers: " + ", ".join(markers[:20]))
            injected = os.environ.get("HADA_BUILD_VERIFY_COMMAND")
            if injected:
                command = Path(injected).resolve()
                if not command.is_file() or not os.access(command, os.X_OK):
                    raise RuntimeError(f"verification command is not executable: {command}")
                _run([str(command)], cwd=worktree, timeout=args.command_timeout)
            else:
                _default_healthcheck(worktree, args.command_timeout)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            _quarantine(lease_path, lease, str(exc))
            raise
        lease["status"] = "verified"
        lease["verified_head"] = head
        lease["verified_at"] = int(time.time())
        _write_json(lease_path, lease)
        print(json.dumps({"status": "verified", "head": head}, sort_keys=True))
        return 0


def publish(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    body_file = Path(args.body_file).resolve()
    if not args.title.strip():
        raise RuntimeError("title must not be empty")
    if not body_file.is_file():
        raise RuntimeError(f"body file does not exist: {body_file}")
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            raise RuntimeError("no active lease")
        if not secrets.compare_digest(str(lease.get("token", "")), args.token):
            raise RuntimeError("lease token mismatch")
        if lease.get("status") != "verified":
            raise RuntimeError(f"lease is not verified: {lease.get('status')}")
        repo = Path(str(lease["repo"]))
        worktree = Path(str(lease["worktree"]))
        try:
            _run(["git", "fetch", "--prune", "origin", "main"], cwd=repo, timeout=args.command_timeout)
            current_base = _run(["git", "rev-parse", "origin/main"], cwd=repo)
            if current_base != lease["base_sha"]:
                raise RuntimeError(
                    f"origin/main moved after verification: prepared {lease['base_sha']}, current {current_base}"
                )
            if _run(["git", "status", "--porcelain"], cwd=worktree):
                raise RuntimeError("worktree changed after verification")
            head = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
            if head != lease.get("verified_head"):
                raise RuntimeError("HEAD changed after verification")
            _run(
                ["git", "push", "-u", "origin", lease["branch"]],
                cwd=worktree,
                timeout=args.command_timeout,
            )
            pr_url = _run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--draft",
                    "--base",
                    "main",
                    "--head",
                    lease["branch"],
                    "--title",
                    args.title,
                    "--body-file",
                    str(body_file),
                ],
                cwd=worktree,
                timeout=args.command_timeout,
            )
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            _quarantine(lease_path, lease, str(exc))
            raise
        lease["status"] = "published"
        lease["pr_url"] = pr_url
        lease["published_at"] = int(time.time())
        _write_json(lease_path, lease)
        print(json.dumps({"status": "published", "pr_url": pr_url}, sort_keys=True))
        return 0


def release(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            raise RuntimeError("no active lease")
        if not secrets.compare_digest(str(lease.get("token", "")), args.token):
            raise RuntimeError("lease token mismatch")
        lease["status"] = args.status
        lease["finished_at"] = int(time.time())
        history = state_dir / "history"
        history.mkdir(exist_ok=True)
        _write_json(history / f"{lease['finished_at']}-{args.status}.json", lease)
        _remove_worktree(lease, state_dir)
        lease_path.unlink(missing_ok=True)
        print(json.dumps({"status": args.status, "released": True}, sort_keys=True))
        return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--repo", required=True)
    prep.add_argument("--state-dir", default=str(DEFAULT_STATE))
    prep.add_argument("--ttl", type=int, default=2700)
    prep.add_argument("--command-timeout", type=int, default=120)
    prep.set_defaults(func=prepare)
    check = sub.add_parser("verify")
    check.add_argument("--state-dir", default=str(DEFAULT_STATE))
    check.add_argument("--token", required=True)
    check.add_argument("--command-timeout", type=int, default=600)
    check.set_defaults(func=verify)
    pub = sub.add_parser("publish")
    pub.add_argument("--state-dir", default=str(DEFAULT_STATE))
    pub.add_argument("--token", required=True)
    pub.add_argument("--title", required=True)
    pub.add_argument("--body-file", required=True)
    pub.add_argument("--command-timeout", type=int, default=120)
    pub.set_defaults(func=publish)
    rel = sub.add_parser("release")
    rel.add_argument("--state-dir", default=str(DEFAULT_STATE))
    rel.add_argument("--token", required=True)
    rel.add_argument("--status", choices=("complete", "failed", "quarantined"), required=True)
    rel.set_defaults(func=release)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"BUILD_GUARD_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
