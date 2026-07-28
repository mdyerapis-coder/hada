import subprocess
from pathlib import Path

import pytest

from hada.workspaces.manager import RepositoryPolicy, WorkspaceError, WorkspaceManager


def _git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_repository_policy_rejects_unapproved_host() -> None:
    policy = RepositoryPolicy(["github.com"])
    with pytest.raises(WorkspaceError):
        policy.validate("https://example.invalid/project.git")
    with pytest.raises(WorkspaceError):
        policy.validate("https://token@example.com/project.git")


def test_workspace_is_created_from_pinned_commit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    (source / "README.md").write_text("governed\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "initial")
    commit = _git(source, "rev-parse", "HEAD")

    manager = WorkspaceManager(
        workspace_root=tmp_path / "workspaces",
        state_root=tmp_path / "state",
        repository_policy=RepositoryPolicy([], allow_local_paths=True),
    )
    record = manager.create(
        milestone_id="M1",
        task_id="task-1",
        repository_url=str(source),
        requested_ref="HEAD",
    )
    assert record.resolved_commit == commit
    assert (record.path / "README.md").read_text(encoding="utf-8") == "governed\n"
    assert _git(record.path, "rev-parse", "HEAD") == commit


def test_repository_policy_rejects_embedded_ssh_password() -> None:
    policy = RepositoryPolicy(["github.com"])
    with pytest.raises(WorkspaceError, match="passwords"):
        policy.validate("ssh://git:secret@github.com/owner/project.git")


def test_workspace_rejects_option_like_ref(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manager = WorkspaceManager(
        workspace_root=tmp_path / "workspaces",
        state_root=tmp_path / "state",
        repository_policy=RepositoryPolicy([], allow_local_paths=True),
    )
    with pytest.raises(WorkspaceError, match="malformed"):
        manager.create(
            milestone_id="M1",
            task_id="task-1",
            repository_url=str(source),
            requested_ref="--upload-pack=attacker",
        )
