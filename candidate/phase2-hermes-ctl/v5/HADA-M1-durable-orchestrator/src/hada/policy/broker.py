from __future__ import annotations

import hashlib
import os
import re
import resource
import shutil
import signal
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from hada.canonical import canonical_json
from hada.models import ExecutionConfig, ToolRuleConfig


class BrokerError(RuntimeError):
    pass


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    milestone_id: str
    task_id: str
    workspace_id: str
    actor_party: int = Field(ge=1, le=3)
    executable: str
    arguments: list[str] = Field(default_factory=list)
    cwd: Path
    environment: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self)).hexdigest()


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    rule_id: str
    reason: str
    resolved_executable: Path | None = None
    read_only: bool = False
    network_access: bool = False


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    started_at: datetime
    finished_at: datetime
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str
    output_truncated: bool


class BrokerOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_digest: str
    decision: PolicyDecision
    result: ExecutionResult | None = None


class PolicyDecisionRecorder(Protocol):
    def record_policy_decision(
        self,
        *,
        milestone_id: str,
        task_id: str | None,
        workspace_id: str | None,
        actor_party: int,
        rule_id: str,
        allowed: bool,
        reason: str,
        request_digest: str,
    ) -> str: ...


class AuditRecorder(Protocol):
    def append_audit(
        self,
        *,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        actor_party: int | None,
    ) -> Any: ...


_SECRET_NAME = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|API[_-]?KEY|AUTH|COOKIE)",
    re.IGNORECASE,
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_GIT_DANGEROUS = (
    "-c",
    "--config-env",
    "--exec-path",
    "--upload-pack",
    "--receive-pack",
    "--ext-diff",
    "--textconv",
)
_OUTPUT_SECRET = re.compile(
    r"(?i)(token|secret|password|api[_-]?key|authorization)(\s*[:=]\s*)([^\s,;]+)"
)


class PolicyEngine:
    def __init__(self, config: ExecutionConfig, workspace_path: Path) -> None:
        self.config = config
        self.workspace_path = workspace_path.resolve()

    def _deny(self, rule_id: str, reason: str) -> PolicyDecision:
        return PolicyDecision(allowed=False, rule_id=rule_id, reason=reason)

    def _matching_rule(self, request: ToolRequest) -> tuple[int, ToolRuleConfig] | None:
        for index, rule in enumerate(self.config.rules):
            if (
                rule.executable == request.executable
                and request.actor_party in rule.allowed_parties
            ):
                return index, rule
        return None

    def evaluate(self, request: ToolRequest) -> PolicyDecision:
        if "/" in request.executable or request.executable in {"sh", "bash", "dash", "zsh", "sudo"}:
            return self._deny("exec.no-shell", "shells, sudo, and executable paths are prohibited")
        if len(request.arguments) > self.config.maximum_arguments:
            return self._deny("exec.argument-count", "argument count exceeds configured maximum")
        if any(
            len(argument) > self.config.maximum_argument_length
            for argument in request.arguments
        ):
            return self._deny(
                "exec.argument-length",
                "an argument exceeds configured maximum length",
            )
        if any(
            any(character in argument for character in ("\0", "\r", "\n"))
            for argument in request.arguments
        ):
            return self._deny(
                "exec.argument-control",
                "arguments may not contain control separators",
            )
        if request.environment:
            invalid_names = [
                name
                for name in request.environment
                if not _ENVIRONMENT_NAME.fullmatch(name)
            ]
            secret_names = [name for name in request.environment if _SECRET_NAME.search(name)]
            if invalid_names or secret_names:
                return self._deny(
                    "exec.environment",
                    "agent-supplied environment contains prohibited or secret-like names",
                )
            return self._deny(
                "exec.environment-closed",
                "agent-supplied environment is disabled; use governed configuration instead",
            )

        try:
            cwd = request.cwd.resolve(strict=True)
        except OSError:
            return self._deny("exec.cwd-missing", "working directory does not exist")
        if not cwd.is_dir() or not cwd.is_relative_to(self.workspace_path):
            return self._deny("exec.cwd-boundary", "working directory escapes the workspace root")

        matched = self._matching_rule(request)
        if matched is None:
            return self._deny(
                "exec.allowlist",
                "executable and party combination is not allowlisted",
            )
        index, rule = matched
        rule_id = f"exec.rule.{index}.{rule.executable}"
        if request.executable == "git" and any(
            argument == dangerous or argument.startswith(f"{dangerous}=")
            for argument in request.arguments
            for dangerous in _GIT_DANGEROUS
        ):
            return self._deny(
                "exec.git-hardening",
                "Git configuration and helper overrides are prohibited",
            )
        if request.timeout_seconds > rule.maximum_timeout_seconds:
            return self._deny(rule_id, "requested timeout exceeds the rule maximum")
        if rule.allowed_subcommands:
            if not request.arguments or request.arguments[0] not in rule.allowed_subcommands:
                return self._deny(rule_id, "subcommand is not allowlisted")

        executable = shutil.which(request.executable)
        if executable is None:
            return self._deny(rule_id, "allowlisted executable is not installed")
        resolved = Path(executable).resolve()
        trusted = any(
            resolved.is_relative_to(root.resolve()) for root in self.config.trusted_binary_roots
        )
        if not trusted:
            return self._deny(rule_id, "resolved executable is outside trusted binary roots")
        if self.config.require_bubblewrap and shutil.which("bwrap") is None:
            return self._deny("exec.sandbox-required", "bubblewrap is required but unavailable")

        return PolicyDecision(
            allowed=True,
            rule_id=rule_id,
            reason="request satisfies the configured execution policy",
            resolved_executable=resolved,
            read_only=rule.read_only,
            network_access=rule.network_access,
        )


class SandboxedExecutor:
    def __init__(self, config: ExecutionConfig, workspace_path: Path) -> None:
        self.config = config
        self.workspace_path = workspace_path.resolve()

    @staticmethod
    def _limits(timeout_seconds: int, maximum_output_bytes: int) -> None:
        os.umask(0o077)
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds + 5, timeout_seconds + 5))
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (maximum_output_bytes * 2, maximum_output_bytes * 2),
        )
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        except (ValueError, OSError):
            pass

    def _sandbox_command(self, request: ToolRequest, decision: PolicyDecision) -> list[str]:
        if decision.resolved_executable is None:
            raise BrokerError("approved decision has no resolved executable")
        if not self.config.require_bubblewrap:
            return [str(decision.resolved_executable), *request.arguments]

        bwrap = shutil.which("bwrap")
        if bwrap is None:
            raise BrokerError("bubblewrap is required but unavailable")
        cwd = request.cwd.resolve(strict=True)
        workspace = self.workspace_path
        home = workspace / ".hada-home"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)

        command = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--clearenv",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        if decision.network_access:
            command.append("--share-net")
        seen: set[Path] = set()
        for configured_path in self.config.readonly_bind_paths:
            path = configured_path.resolve()
            if path in seen or not path.exists():
                continue
            seen.add(path)
            command.extend(["--ro-bind", str(path), str(path)])
        bind_option = "--ro-bind" if decision.read_only else "--bind"
        command.extend([bind_option, str(workspace), str(workspace)])
        command.extend(
            [
                "--chdir",
                str(cwd),
                "--setenv",
                "HOME",
                str(home),
                "--setenv",
                "PATH",
                "/opt/hada/.venv/bin:/usr/local/bin:/usr/bin:/bin",
                "--setenv",
                "LANG",
                "C.UTF-8",
                "--setenv",
                "LC_ALL",
                "C.UTF-8",
                "--setenv",
                "GIT_CONFIG_NOSYSTEM",
                "1",
                "--setenv",
                "GIT_CONFIG_GLOBAL",
                "/dev/null",
                "--setenv",
                "GIT_PAGER",
                "cat",
                "--",
                str(decision.resolved_executable),
                *request.arguments,
            ]
        )
        return command

    @staticmethod
    def _read_output(path: Path, maximum_bytes: int) -> tuple[str, bool]:
        data = path.read_bytes()
        truncated = len(data) > maximum_bytes
        selected = data[:maximum_bytes]
        text = selected.decode("utf-8", errors="replace")
        redacted = _OUTPUT_SECRET.sub(r"\1\2[REDACTED]", text)
        return redacted, truncated

    def execute(self, request: ToolRequest, decision: PolicyDecision) -> ExecutionResult:
        if not decision.allowed:
            raise BrokerError("a denied request may not be executed")
        command = self._sandbox_command(request, decision)
        started_at = datetime.now(UTC)
        timed_out = False
        with tempfile.TemporaryDirectory(prefix="hada-tool-") as temporary_directory:
            stdout_path = Path(temporary_directory) / "stdout"
            stderr_path = Path(temporary_directory) / "stderr"
            with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=request.cwd,
                    env={
                        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                        "LANG": "C.UTF-8",
                        "LC_ALL": "C.UTF-8",
                    },
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    start_new_session=True,
                    preexec_fn=lambda: self._limits(
                        request.timeout_seconds, self.config.maximum_output_bytes
                    ),
                )
                try:
                    exit_code = process.wait(timeout=request.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGKILL)
                    exit_code = process.wait(timeout=10)
            stdout, stdout_truncated = self._read_output(
                stdout_path, self.config.maximum_output_bytes
            )
            stderr, stderr_truncated = self._read_output(
                stderr_path, self.config.maximum_output_bytes
            )
        return ExecutionResult(
            request_id=request.request_id,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            output_truncated=stdout_truncated or stderr_truncated,
        )


class ToolBroker:
    def __init__(
        self,
        policy: PolicyEngine,
        executor: SandboxedExecutor,
        decision_recorder: PolicyDecisionRecorder,
        audit_recorder: AuditRecorder,
    ) -> None:
        self.policy = policy
        self.executor = executor
        self.decision_recorder = decision_recorder
        self.audit_recorder = audit_recorder

    def handle(self, request: ToolRequest) -> BrokerOutcome:
        decision = self.policy.evaluate(request)
        self.decision_recorder.record_policy_decision(
            milestone_id=request.milestone_id,
            task_id=request.task_id,
            workspace_id=request.workspace_id,
            actor_party=request.actor_party,
            rule_id=decision.rule_id,
            allowed=decision.allowed,
            reason=decision.reason,
            request_digest=request.digest,
        )
        if not decision.allowed:
            return BrokerOutcome(request_digest=request.digest, decision=decision)

        result = self.executor.execute(request, decision)
        self.audit_recorder.append_audit(
            stream=f"task:{request.task_id}",
            event_type="tool.execution_result",
            payload={
                "request_id": request.request_id,
                "request_digest": request.digest,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "output_truncated": result.output_truncated,
                "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
            },
            actor_party=request.actor_party,
        )
        return BrokerOutcome(request_digest=request.digest, decision=decision, result=result)
