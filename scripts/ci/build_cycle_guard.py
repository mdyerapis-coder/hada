#!/usr/bin/env python3
"""Deterministic, fail-closed controller for one autonomous HADA build cycle."""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

BUSY = 75
SCHEMA = 3
DEFAULT_STATE = Path(
    os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
) / "hada-build"


class LeaseBusy(RuntimeError):
    """A healthy owner or another controller invocation holds the cycle."""


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        argv, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=env
    )
    if result.returncode:
        detail = "\n".join(x for x in (result.stdout.strip(), result.stderr.strip()) if x)
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n{detail}".rstrip()
        )
    return result.stdout.strip()


def _run_optional(
    argv: list[str], *, cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False
    )


@contextmanager
def _locked(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = state_dir / "guard.lock"
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LeaseBusy("controller state is locked by another invocation") from exc
        yield


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid state file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid state file {path}: expected object")
    return value


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _pid_start_time(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        remainder = raw.rsplit(")", 1)[1].strip().split()
        return remainder[19]
    except (OSError, IndexError, ValueError):
        return None


def _owner_is_live(lease: dict[str, Any]) -> bool:
    if str(lease.get("host", "")) != socket.gethostname():
        return False
    try:
        pid = int(lease["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    current_start = _pid_start_time(pid)
    return bool(current_start and current_start == str(lease.get("pid_start_time", "")))


def _validate_lease(lease: dict[str, Any]) -> None:
    required = {
        "schema",
        "run_id",
        "token",
        "mirror",
        "worktree",
        "branch",
        "base_sha",
        "allowed_paths",
        "pid",
        "pid_start_time",
        "host",
        "heartbeat_at",
        "ttl",
        "status",
    }
    missing = sorted(required.difference(lease))
    if missing:
        raise RuntimeError("lease missing fields: " + ", ".join(missing))
    if int(lease["schema"]) != SCHEMA:
        raise RuntimeError(f"unsupported lease schema: {lease['schema']}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(lease["base_sha"])):
        raise RuntimeError("invalid lease base SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", str(lease["token"])):
        raise RuntimeError("invalid lease token")
    allowed_paths = lease["allowed_paths"]
    if not isinstance(allowed_paths, list) or not allowed_paths:
        raise RuntimeError("lease allowed_paths must be a non-empty list")
    if not all(isinstance(pattern, str) and pattern for pattern in allowed_paths):
        raise RuntimeError("lease contains an invalid allowed path pattern")


def _validated_allow_paths(patterns: list[str]) -> list[str]:
    allowed = sorted(set(patterns))
    if not allowed:
        raise RuntimeError("at least one --allow-path is required")
    for pattern in allowed:
        parts = pattern.split("/")
        if (
            pattern.startswith("/")
            or "\\" in pattern
            or "\x00" in pattern
            or ".." in parts
            or any(part == "" for part in parts)
        ):
            raise RuntimeError(f"unsafe allow-path pattern: {pattern}")
    return allowed


def _assert_allowed_paths(
    worktree: Path, base_sha: str, head: str, patterns: list[str]
) -> None:
    changed = _run(
        [
            "git",
            "diff",
            "--no-renames",
            "--name-only",
            f"{base_sha}..{head}",
        ],
        cwd=worktree,
    ).splitlines()
    for relative in changed:
        if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns):
            raise RuntimeError(f"candidate path outside allowlist: {relative}")


def _validate_token(lease: dict[str, Any], token: str) -> None:
    _validate_lease(lease)
    if not secrets.compare_digest(str(lease["token"]), token):
        raise RuntimeError("lease token mismatch")


def _paths(lease: dict[str, Any], state_dir: Path) -> tuple[Path, Path, Path]:
    _validate_lease(lease)
    run_id = str(lease["run_id"])
    run_dir = (state_dir / "runs" / run_id).resolve()
    worktree = Path(str(lease["worktree"])).resolve()
    mirror = Path(str(lease["mirror"])).resolve()
    if run_dir.parent != (state_dir / "runs").resolve():
        raise RuntimeError(f"unsafe run directory: {run_dir}")
    if worktree != run_dir / "worktree":
        raise RuntimeError(f"unsafe worktree path in lease: {worktree}")
    if mirror != (state_dir / "repository.git").resolve():
        raise RuntimeError(f"unsafe mirror path in lease: {mirror}")
    return run_dir, worktree, mirror


def _remove_worktree(lease: dict[str, Any], state_dir: Path) -> None:
    _, worktree, mirror = _paths(lease, state_dir)
    if worktree.exists() and mirror.exists():
        result = _run_optional(
            ["git", "--git-dir", str(mirror), "worktree", "remove", "--force", str(worktree)],
            cwd=state_dir,
            timeout=30,
        )
        if result.returncode and worktree.exists():
            raise RuntimeError(f"git worktree removal failed: {result.stderr.strip()}")
    if worktree.exists():
        shutil.rmtree(worktree)


def _archive(
    lease_path: Path, lease: dict[str, Any], state_dir: Path, category: str
) -> None:
    run_dir, worktree, _ = _paths(lease, state_dir)
    archive = (state_dir / category / str(lease["run_id"])).resolve()
    expected_parent = (state_dir / category).resolve()
    if archive.parent != expected_parent:
        raise RuntimeError(f"unsafe archive path: {archive}")
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    if worktree.exists():
        for name, command in {
            "head.txt": ["git", "rev-parse", "HEAD"],
            "status.txt": ["git", "status", "--short"],
            "changed-files.txt": [
                "git",
                "diff",
                "--name-status",
                f"{lease['base_sha']}..HEAD",
            ],
        }.items():
            result = _run_optional(command, cwd=worktree, timeout=20)
            _atomic_write(archive / name, (result.stdout or result.stderr).strip() + "\n")
    _write_json(archive / "manifest.json", lease)
    if run_dir.exists():
        for evidence in run_dir.glob("*.log"):
            shutil.copy2(evidence, archive / evidence.name)
    _remove_worktree(lease, state_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    lease_path.unlink(missing_ok=True)


def _ensure_mirror(source_repo: Path, mirror: Path, timeout: int) -> None:
    origin = _run(["git", "remote", "get-url", "origin"], cwd=source_repo)
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _run(["git", "clone", "--bare", origin, str(mirror)], cwd=mirror.parent, timeout=timeout)
    elif not (mirror / "HEAD").exists():
        raise RuntimeError(f"controller mirror is corrupt: {mirror}")
    _run(["git", "--git-dir", str(mirror), "remote", "set-url", "origin", origin], cwd=mirror.parent)
    _run(
        [
            "git",
            "--git-dir",
            str(mirror),
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ],
        cwd=mirror.parent,
        timeout=timeout,
    )


def _current_base(mirror: Path, timeout: int) -> str:
    sha = _run(
        ["git", "--git-dir", str(mirror), "rev-parse", "refs/remotes/origin/main^{commit}"],
        cwd=mirror.parent,
        timeout=timeout,
    )
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"origin/main did not resolve to a full SHA: {sha}")
    return sha


def _quarantine(
    lease_path: Path, lease: dict[str, Any], state_dir: Path, reason: str
) -> None:
    lease["status"] = "quarantined"
    lease["failure_class"] = "verification"
    lease["quarantine_reason"] = reason[:2000]
    lease["updated_at"] = int(time.time())
    _write_json(lease_path, lease)
    run_dir, _, _ = _paths(lease, state_dir)
    _write_json(run_dir / "manifest.json", lease)


def prepare(args: argparse.Namespace) -> int:
    source_repo = Path(args.repo).resolve()
    state_dir = Path(args.state_dir).resolve()
    allowed_paths = _validated_allow_paths(args.allow_path)
    if not (source_repo / ".git").exists():
        raise RuntimeError(f"not a Git checkout: {source_repo}")
    if args.ttl < 60 or args.ttl > 7200:
        raise RuntimeError("ttl must be between 60 and 7200 seconds")
    owner_pid = int(args.owner_pid)
    owner_start = _pid_start_time(owner_pid)
    if not owner_start:
        raise RuntimeError(f"owner PID is not live: {owner_pid}")

    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        existing = _read_json(lease_path)
        recovered = False
        now = int(time.time())
        if existing:
            _validate_lease(existing)
            status = str(existing["status"])
            healthy_until = int(existing["heartbeat_at"]) + int(existing["ttl"])
            if status in {"active", "verified", "publishing"} and (
                _owner_is_live(existing) and healthy_until > now
            ):
                raise LeaseBusy("active build-cycle lease")
            existing["recovered_at"] = now
            existing["recovery_reason"] = (
                f"terminal state {status}" if status not in {"active", "verified", "publishing"}
                else "dead owner and expired heartbeat"
            )
            _archive(lease_path, existing, state_dir, "quarantine")
            recovered = True

        mirror = (state_dir / "repository.git").resolve()
        _ensure_mirror(source_repo, mirror, args.command_timeout)
        base_sha = _current_base(mirror, args.command_timeout)
        token = secrets.token_hex(32)
        run_id = f"{now}-{token[:12]}"
        branch = f"agent/build-cycle-{run_id}"
        run_dir = state_dir / "runs" / run_id
        worktree = run_dir / "worktree"
        run_dir.mkdir(parents=True, mode=0o700)
        _run(
            ["git", "--git-dir", str(mirror), "worktree", "add", "--detach", str(worktree), base_sha],
            cwd=state_dir,
            timeout=args.command_timeout,
        )
        _run(["git", "switch", "-c", branch], cwd=worktree, timeout=args.command_timeout)
        if _run(["git", "rev-parse", "HEAD"], cwd=worktree) != base_sha:
            raise RuntimeError("prepared worktree does not match immutable base")
        if _run(["git", "status", "--porcelain"], cwd=worktree):
            raise RuntimeError("prepared worktree is not clean")
        lease = {
            "schema": SCHEMA,
            "run_id": run_id,
            "token": token,
            "mirror": str(mirror),
            "worktree": str(worktree),
            "branch": branch,
            "base_sha": base_sha,
            "allowed_paths": allowed_paths,
            "pid": owner_pid,
            "pid_start_time": owner_start,
            "host": socket.gethostname(),
            "acquired_at": now,
            "heartbeat_at": now,
            "ttl": args.ttl,
            "expires_at": now + args.ttl,
            "status": "active",
        }
        _write_json(lease_path, lease)
        _write_json(run_dir / "manifest.json", lease)
        print(json.dumps({**lease, "recovered_stale_lease": recovered}, sort_keys=True))
        return 0


def heartbeat(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            raise RuntimeError("no active lease")
        _validate_token(lease, args.token)
        if lease["status"] not in {"active", "verified"}:
            raise RuntimeError(f"lease cannot heartbeat in state {lease['status']}")
        now = int(time.time())
        lease["heartbeat_at"] = now
        lease["expires_at"] = now + int(lease["ttl"])
        _write_json(lease_path, lease)
        run_dir, _, _ = _paths(lease, state_dir)
        _write_json(run_dir / "manifest.json", lease)
        print(json.dumps({"status": lease["status"], "heartbeat_at": lease["heartbeat_at"]}))
        return 0


def _conflict_markers(worktree: Path) -> list[str]:
    files = _run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=worktree
    ).splitlines()
    marker = re.compile(r"^(?:<<<<<<< .+|=======|>>>>>>> .+)$")
    hits: list[str] = []
    for relative in files:
        path = worktree / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if marker.fullmatch(line):
                hits.append(f"{relative}:{number}")
    return hits


def _assert_candidate(lease: dict[str, Any], state_dir: Path, timeout: int) -> tuple[Path, Path, str]:
    _, worktree, mirror = _paths(lease, state_dir)
    _run(
        [
            "git",
            "--git-dir",
            str(mirror),
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ],
        cwd=state_dir,
        timeout=timeout,
    )
    current = _current_base(mirror, timeout)
    if current != lease["base_sha"]:
        raise RuntimeError(
            f"origin/main moved: prepared {lease['base_sha']}, current {current}"
        )
    if _run(["git", "status", "--porcelain"], cwd=worktree):
        raise RuntimeError("worktree is dirty; commit the bounded change first")
    if _run(["git", "symbolic-ref", "--short", "HEAD"], cwd=worktree) != lease["branch"]:
        raise RuntimeError("candidate branch identity changed")
    head = _run(["git", "rev-parse", "HEAD"], cwd=worktree)
    if head == lease["base_sha"]:
        raise RuntimeError("cycle has no committed change")
    merge_base = _run(["git", "merge-base", lease["base_sha"], head], cwd=worktree)
    if merge_base != lease["base_sha"]:
        raise RuntimeError("candidate is not based on the recorded immutable base")
    merges = _run(
        ["git", "rev-list", "--merges", f"{lease['base_sha']}..{head}"], cwd=worktree
    )
    if merges:
        raise RuntimeError("merge commits are forbidden in a build cycle")
    _assert_allowed_paths(
        worktree, str(lease["base_sha"]), head, list(lease["allowed_paths"])
    )
    if _run(["git", "ls-files", "-u"], cwd=worktree):
        raise RuntimeError("unmerged Git index entries remain")
    markers = _conflict_markers(worktree)
    if markers:
        raise RuntimeError("unresolved conflict markers: " + ", ".join(markers[:20]))
    return worktree, mirror, head


def verify(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    if args.command_timeout < 1 or args.command_timeout > 3600:
        raise RuntimeError("command-timeout must be between 1 and 3600 seconds")
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            raise RuntimeError("no active lease")
        _validate_token(lease, args.token)
        if lease["status"] != "active":
            raise RuntimeError(f"lease is not active: {lease['status']}")
        try:
            worktree, _, head = _assert_candidate(lease, state_dir, args.command_timeout)
            injected = os.environ.get("HADA_BUILD_VERIFY_COMMAND")
            if injected:
                command = Path(injected).resolve()
                if not command.is_file() or not os.access(command, os.X_OK):
                    raise RuntimeError(f"verification command is not executable: {command}")
                output = _run([str(command)], cwd=worktree, timeout=args.command_timeout)
            else:
                env = os.environ.copy()
                env["HADA_BUILD_BASE_SHA"] = str(lease["base_sha"])
                output = _run(
                    ["bash", "scripts/ci/full_green_gate.sh"],
                    cwd=worktree,
                    timeout=args.command_timeout,
                    env=env,
                )
            run_dir, _, _ = _paths(lease, state_dir)
            log = output + ("\n" if output else "")
            _atomic_write(run_dir / "full-gate.log", log)
            gate_hash = hashlib.sha256(log.encode()).hexdigest()
            # Recheck after the potentially long gate.
            _, _, final_head = _assert_candidate(lease, state_dir, args.command_timeout)
            if final_head != head:
                raise RuntimeError("candidate HEAD changed during verification")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            _quarantine(lease_path, lease, state_dir, str(exc))
            raise
        lease.update(
            {
                "status": "verified",
                "verified_head": head,
                "verified_at": int(time.time()),
                "heartbeat_at": int(time.time()),
                "gate_log_sha256": gate_hash,
            }
        )
        _write_json(lease_path, lease)
        run_dir, _, _ = _paths(lease, state_dir)
        _write_json(run_dir / "manifest.json", lease)
        print(json.dumps({"status": "verified", "head": head, "gate_log_sha256": gate_hash}))
        return 0


def _parse_json(text: str, description: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from {description}: {exc}") from exc


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
        _validate_token(lease, args.token)
        if lease["status"] != "verified":
            raise RuntimeError(f"lease is not verified: {lease['status']}")
        try:
            worktree, mirror, head = _assert_candidate(lease, state_dir, args.command_timeout)
            if head != lease.get("verified_head"):
                raise RuntimeError("HEAD changed after verification")
            run_dir, _, _ = _paths(lease, state_dir)
            gate_log = (run_dir / "full-gate.log").read_bytes()
            if hashlib.sha256(gate_log).hexdigest() != lease.get("gate_log_sha256"):
                raise RuntimeError("verification evidence hash mismatch")
            lease["status"] = "publishing"
            _write_json(lease_path, lease)
            verified_head = str(lease["verified_head"])
            remote_ref = f"refs/heads/{lease['branch']}"
            _run(
                ["git", "push", "origin", f"{verified_head}:{remote_ref}"],
                cwd=worktree,
                timeout=args.command_timeout,
            )
            remote_raw = _run(
                ["git", "ls-remote", "--refs", "origin", remote_ref],
                cwd=worktree,
                timeout=args.command_timeout,
            )
            remote_lines = remote_raw.splitlines()
            if (
                len(remote_lines) != 1
                or remote_lines[0].split() != [verified_head, remote_ref]
            ):
                raise RuntimeError("remote branch is not bound to the verified SHA")
            # Close the push-to-PR race before publication.
            _run(
                [
                    "git",
                    "--git-dir",
                    str(mirror),
                    "fetch",
                    "origin",
                    "+refs/heads/main:refs/remotes/origin/main",
                ],
                cwd=state_dir,
                timeout=args.command_timeout,
            )
            if _current_base(mirror, args.command_timeout) != lease["base_sha"]:
                raise RuntimeError("origin/main moved after push; draft PR creation blocked")

            existing_raw = _run(
                [
                    "gh", "pr", "list", "--state", "open", "--head", lease["branch"],
                    "--json", "url,isDraft,headRefName,baseRefName,headRefOid",
                ],
                cwd=worktree,
                timeout=args.command_timeout,
            )
            existing = _parse_json(existing_raw or "[]", "gh pr list")
            if not isinstance(existing, list):
                raise RuntimeError("gh pr list did not return an array")
            if len(existing) > 1:
                raise RuntimeError("multiple open PRs exist for cycle branch")
            if existing:
                pr = existing[0]
                pr_url = str(pr.get("url", ""))
            else:
                provenance = (
                    "\n\n<!-- hada-build-cycle\n"
                    f"run-id: {lease['run_id']}\n"
                    f"base-sha: {lease['base_sha']}\n"
                    f"head-sha: {head}\n"
                    "-->\n"
                )
                governed_body = run_dir / "pr-body.md"
                _atomic_write(governed_body, body_file.read_text(encoding="utf-8") + provenance)
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
                        str(governed_body),
                    ],
                    cwd=worktree,
                    timeout=args.command_timeout,
                )
                view_raw = _run(
                    [
                        "gh", "pr", "view", pr_url, "--json",
                        "url,isDraft,headRefName,baseRefName,headRefOid",
                    ],
                    cwd=worktree,
                    timeout=args.command_timeout,
                )
                pr = _parse_json(view_raw, "gh pr view")
            if not isinstance(pr, dict):
                raise RuntimeError("PR verification did not return an object")
            if not pr.get("isDraft"):
                raise RuntimeError("published pull request is not draft")
            if pr.get("headRefName") != lease["branch"] or pr.get("baseRefName") != "main":
                raise RuntimeError("published pull request branch/base mismatch")
            if pr.get("headRefOid") != verified_head:
                raise RuntimeError("published pull request head is not the verified SHA")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            lease["status"] = "verified" if lease.get("verified_head") else "active"
            _quarantine(lease_path, lease, state_dir, str(exc))
            raise
        lease.update(
            {
                "status": "awaiting_human",
                "pr_url": pr_url,
                "published_at": int(time.time()),
            }
        )
        _write_json(lease_path, lease)
        run_dir, _, _ = _paths(lease, state_dir)
        _write_json(run_dir / "manifest.json", lease)
        print(json.dumps({"status": "awaiting_human", "pr_url": pr_url}))
        return 0


def release(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            raise RuntimeError("no active lease")
        _validate_token(lease, args.token)
        lease["status"] = args.status
        lease["finished_at"] = int(time.time())
        category = "quarantine" if args.status in {"failed", "quarantined"} else "history"
        _archive(lease_path, lease, state_dir, category)
        print(json.dumps({"status": args.status, "released": True}))
        return 0


def recover(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    with _locked(state_dir):
        lease_path = state_dir / "lease.json"
        lease = _read_json(lease_path)
        if not lease:
            print(json.dumps({"status": "idle", "recovered": False}))
            return 0
        _validate_lease(lease)
        now = int(time.time())
        healthy_until = int(lease["heartbeat_at"]) + int(lease["ttl"])
        if lease["status"] in {"active", "verified", "publishing"} and (
            _owner_is_live(lease) and healthy_until > now
        ):
            raise LeaseBusy("live owner with unexpired heartbeat cannot be recovered")
        lease["recovered_at"] = now
        lease["recovery_reason"] = "explicit dead-owner recovery"
        _archive(lease_path, lease, state_dir, "quarantine")
        print(json.dumps({"status": "idle", "recovered": True, "run_id": lease["run_id"]}))
        return 0


def status(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve()
    with _locked(state_dir):
        lease = _read_json(state_dir / "lease.json")
        if not lease:
            print(json.dumps({"status": "idle"}))
            return 0
        _validate_lease(lease)
        safe = {k: v for k, v in lease.items() if k != "token"}
        safe["owner_live"] = _owner_is_live(lease)
        safe["expired"] = int(time.time()) >= int(
            lease.get("expires_at", int(lease["heartbeat_at"]) + int(lease["ttl"]))
        )
        print(json.dumps(safe, sort_keys=True))
        return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare")
    prep.add_argument("--repo", required=True)
    prep.add_argument("--state-dir", default=str(DEFAULT_STATE))
    prep.add_argument("--ttl", type=int, default=900)
    prep.add_argument("--owner-pid", type=int, default=os.getppid())
    prep.add_argument("--command-timeout", type=int, default=180)
    prep.add_argument(
        "--allow-path",
        action="append",
        default=[],
        help="allowed Git path glob for this cycle (repeatable; required)",
    )
    prep.set_defaults(func=prepare)

    beat = sub.add_parser("heartbeat")
    beat.add_argument("--state-dir", default=str(DEFAULT_STATE))
    beat.add_argument("--token", required=True)
    beat.set_defaults(func=heartbeat)

    check = sub.add_parser("verify")
    check.add_argument("--state-dir", default=str(DEFAULT_STATE))
    check.add_argument("--token", required=True)
    check.add_argument("--command-timeout", type=int, default=1800)
    check.set_defaults(func=verify)

    pub = sub.add_parser("publish")
    pub.add_argument("--state-dir", default=str(DEFAULT_STATE))
    pub.add_argument("--token", required=True)
    pub.add_argument("--title", required=True)
    pub.add_argument("--body-file", required=True)
    pub.add_argument("--command-timeout", type=int, default=180)
    pub.set_defaults(func=publish)

    rel = sub.add_parser("release")
    rel.add_argument("--state-dir", default=str(DEFAULT_STATE))
    rel.add_argument("--token", required=True)
    rel.add_argument("--status", choices=("complete", "failed", "quarantined"), required=True)
    rel.set_defaults(func=release)

    rec = sub.add_parser("recover")
    rec.add_argument("--state-dir", default=str(DEFAULT_STATE))
    rec.set_defaults(func=recover)

    stat = sub.add_parser("status")
    stat.add_argument("--state-dir", default=str(DEFAULT_STATE))
    stat.set_defaults(func=status)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except LeaseBusy as exc:
        print(json.dumps({"status": "busy", "message": str(exc)}), file=sys.stderr)
        return BUSY
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"BUILD_GUARD_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
