from pathlib import Path

from hada.models import ExecutionConfig, ToolRuleConfig
from hada.policy.broker import PolicyEngine, ToolRequest


def _config() -> ExecutionConfig:
    return ExecutionConfig(
        require_bubblewrap=False,
        trusted_binary_roots=[Path("/usr/bin"), Path("/bin")],
        readonly_bind_paths=[Path("/usr"), Path("/bin")],
        maximum_output_bytes=4096,
        maximum_arguments=10,
        maximum_argument_length=256,
        rules=[
            ToolRuleConfig(
                executable="git",
                allowed_subcommands=["status", "diff"],
                allowed_parties=[1, 2],
                maximum_timeout_seconds=30,
                network_access=False,
                read_only=True,
            )
        ],
    )


def test_shell_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = PolicyEngine(_config(), workspace)
    decision = engine.evaluate(
        ToolRequest(
            milestone_id="M1",
            task_id="1",
            workspace_id="w1",
            actor_party=1,
            executable="bash",
            arguments=["-c", "echo unsafe"],
            cwd=workspace,
        )
    )
    assert decision.allowed is False
    assert decision.rule_id == "exec.no-shell"


def test_cwd_escape_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = PolicyEngine(_config(), workspace)
    decision = engine.evaluate(
        ToolRequest(
            milestone_id="M1",
            task_id="1",
            workspace_id="w1",
            actor_party=1,
            executable="git",
            arguments=["status"],
            cwd=tmp_path,
        )
    )
    assert decision.allowed is False
    assert decision.rule_id == "exec.cwd-boundary"


def test_allowlisted_read_only_git_command(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = PolicyEngine(_config(), workspace)
    decision = engine.evaluate(
        ToolRequest(
            milestone_id="M1",
            task_id="1",
            workspace_id="w1",
            actor_party=2,
            executable="git",
            arguments=["status", "--short"],
            cwd=workspace,
            timeout_seconds=20,
        )
    )
    assert decision.allowed is True
    assert decision.read_only is True


def test_git_configuration_override_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = PolicyEngine(_config(), workspace)
    decision = engine.evaluate(
        ToolRequest(
            milestone_id="M1",
            task_id="1",
            workspace_id="w1",
            actor_party=1,
            executable="git",
            arguments=["status", "-c", "core.pager=evil"],
            cwd=workspace,
        )
    )
    assert decision.allowed is False
    assert decision.rule_id == "exec.git-hardening"


def test_sandboxed_executor_and_broker_without_bubblewrap(tmp_path: Path) -> None:
    import subprocess

    from hada.policy.broker import SandboxedExecutor, ToolBroker

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    config = _config()
    policy = PolicyEngine(config, workspace)
    executor = SandboxedExecutor(config, workspace)

    class Recorder:
        def __init__(self) -> None:
            self.decisions: list[dict[str, object]] = []

        def record_policy_decision(self, **kwargs: object) -> str:
            self.decisions.append(kwargs)
            return "decision-1"

    class Audit:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def append_audit(self, **kwargs: object) -> object:
            self.events.append(kwargs)
            return object()

    recorder = Recorder()
    audit = Audit()
    broker = ToolBroker(policy, executor, recorder, audit)
    outcome = broker.handle(
        ToolRequest(
            milestone_id="M1",
            task_id="1",
            workspace_id="w1",
            actor_party=1,
            executable="git",
            arguments=["status", "--short"],
            cwd=workspace,
            timeout_seconds=20,
        )
    )
    assert outcome.decision.allowed is True
    assert outcome.result is not None and outcome.result.exit_code == 0
    assert recorder.decisions[0]["allowed"] is True
    assert audit.events[0]["event_type"] == "tool.execution_result"


def test_agent_environment_is_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = PolicyEngine(_config(), workspace)
    decision = engine.evaluate(
        ToolRequest(
            milestone_id="M1",
            task_id="1",
            workspace_id="w1",
            actor_party=1,
            executable="git",
            arguments=["status"],
            cwd=workspace,
            timeout_seconds=20,
            environment={"SAFE_VALUE": "still-not-accepted"},
        )
    )
    assert decision.allowed is False
    assert decision.rule_id == "exec.environment-closed"
