from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceError(RuntimeError):
    pass


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")


class WorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(default_factory=lambda: str(uuid4()))
    milestone_id: str
    task_id: str
    owner_party: int = Field(default=1, ge=1, le=1)
    path: Path
    repository_url: str
    requested_ref: str
    resolved_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    status: str = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RepositoryPolicy:
    def __init__(self, allowed_hosts: list[str], *, allow_local_paths: bool = False) -> None:
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.allow_local_paths = allow_local_paths

    def validate(self, repository_url: str) -> None:
        if not repository_url or any(character in repository_url for character in "\r\n\0"):
            raise WorkspaceError("repository URL is empty or malformed")
        local_candidate = Path(repository_url).expanduser()
        if local_candidate.is_absolute() or repository_url.startswith("./"):
            if not self.allow_local_paths:
                raise WorkspaceError("local repository paths are disabled")
            if not local_candidate.resolve().exists():
                raise WorkspaceError("local repository path does not exist")
            return

        host: str | None = None
        parsed = urlparse(repository_url)
        if parsed.scheme:
            if parsed.scheme not in {"https", "ssh"}:
                raise WorkspaceError(f"unsupported repository URL scheme: {parsed.scheme}")
            if parsed.password is not None:
                raise WorkspaceError("passwords may not be embedded in repository URLs")
            if parsed.username and parsed.scheme == "https":
                raise WorkspaceError("credentials may not be embedded in HTTPS repository URLs")
            host = parsed.hostname
        elif re.match(r"^[^/@:]+@[^/:]+:.+$", repository_url):
            host = repository_url.split("@", maxsplit=1)[1].split(":", maxsplit=1)[0]
        else:
            raise WorkspaceError("repository URL must use HTTPS, SSH, or approved SCP syntax")

        if host is None or host.lower() not in self.allowed_hosts:
            raise WorkspaceError(f"repository host is not approved: {host or 'unknown'}")


class GitRunner:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)

    def run(self, arguments: list[str], *, cwd: Path | None = None, timeout: int = 300) -> str:
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_PAGER": "cat",
        }
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            error = result.stderr.strip()[-4000:]
            raise WorkspaceError(f"git command failed ({result.returncode}): {error}")
        return result.stdout.strip()


class WorkspaceManager:
    def __init__(
        self,
        *,
        workspace_root: Path,
        state_root: Path,
        repository_policy: RepositoryPolicy,
        git: GitRunner | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.state_root = state_root.resolve()
        self.repository_policy = repository_policy
        self.git = git or GitRunner(self.state_root / "git-home")
        self.mirror_root = self.state_root / "repositories"
        self.metadata_root = self.state_root / "workspace-metadata"
        for directory in (self.workspace_root, self.mirror_root, self.metadata_root):
            directory.mkdir(parents=True, exist_ok=True, mode=0o750)

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not _SAFE_IDENTIFIER.fullmatch(value):
            raise WorkspaceError(f"invalid {label}: {value!r}")

    def _mirror_path(self, repository_url: str) -> Path:
        digest = hashlib.sha256(repository_url.encode("utf-8")).hexdigest()
        return self.mirror_root / f"{digest}.git"

    def _prepare_mirror(self, repository_url: str) -> Path:
        mirror = self._mirror_path(repository_url)
        if mirror.exists():
            if mirror.is_symlink() or not (mirror / "HEAD").is_file():
                raise WorkspaceError("repository mirror is not a valid bare Git repository")
            self.git.run(["--git-dir", str(mirror), "remote", "set-url", "origin", repository_url])
            self.git.run(
                ["--git-dir", str(mirror), "fetch", "--prune", "--tags", "--force", "origin"]
            )
        else:
            temporary = Path(tempfile.mkdtemp(prefix="mirror-", dir=self.mirror_root))
            try:
                shutil.rmtree(temporary)
                self.git.run(["clone", "--mirror", repository_url, str(temporary)], timeout=900)
                os.replace(temporary, mirror)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)
        self.git.run(["--git-dir", str(mirror), "worktree", "prune"])
        return mirror

    def create(
        self,
        *,
        milestone_id: str,
        task_id: str,
        repository_url: str,
        requested_ref: str,
    ) -> WorkspaceRecord:
        self._validate_identifier(milestone_id, "milestone identifier")
        self._validate_identifier(task_id, "task identifier")
        if (
            not requested_ref
            or requested_ref.startswith("-")
            or any(character in requested_ref for character in "\r\n\0")
        ):
            raise WorkspaceError("requested Git ref is malformed")
        self.repository_policy.validate(repository_url)

        workspace_path = (self.workspace_root / milestone_id / task_id).resolve()
        if not workspace_path.is_relative_to(self.workspace_root):
            raise WorkspaceError("workspace path escapes configured root")
        if workspace_path.exists():
            raise WorkspaceError(f"workspace already exists: {workspace_path}")

        mirror = self._prepare_mirror(repository_url)
        resolved_commit = self.git.run(
            [
                "--git-dir",
                str(mirror),
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{requested_ref}^{{commit}}",
            ]
        )
        if not _COMMIT.fullmatch(resolved_commit):
            raise WorkspaceError("Git resolved an invalid commit identifier")

        workspace_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        try:
            self.git.run(
                [
                    "--git-dir",
                    str(mirror),
                    "worktree",
                    "add",
                    "--detach",
                    str(workspace_path),
                    resolved_commit,
                ],
                timeout=900,
            )
            os.chmod(workspace_path, 0o750)
            record = WorkspaceRecord(
                milestone_id=milestone_id,
                task_id=task_id,
                path=workspace_path,
                repository_url=repository_url,
                requested_ref=requested_ref,
                resolved_commit=resolved_commit,
            )
            self._write_metadata(record)
            return record
        except Exception:
            if workspace_path.exists():
                shutil.rmtree(workspace_path, ignore_errors=True)
            raise

    def _write_metadata(self, record: WorkspaceRecord) -> None:
        path = self.metadata_root / f"{record.workspace_id}.json"
        data = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o440)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def retire(self, record: WorkspaceRecord) -> None:
        workspace_path = record.path.resolve()
        if not workspace_path.is_relative_to(self.workspace_root):
            raise WorkspaceError("workspace path escapes configured root")
        mirror = self._mirror_path(record.repository_url)
        if workspace_path.exists():
            self.git.run(
                ["--git-dir", str(mirror), "worktree", "remove", "--force", str(workspace_path)]
            )
        self.git.run(["--git-dir", str(mirror), "worktree", "prune"])
