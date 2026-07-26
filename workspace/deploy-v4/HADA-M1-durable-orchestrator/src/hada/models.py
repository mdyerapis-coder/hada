from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GateName(StrEnum):
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    TEST = "test"
    DOCUMENTATION = "documentation"
    MILESTONE_REPORT = "milestone_report"
    EXTERNAL_REVIEW = "external_review"


class GateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class StopReason(StrEnum):
    NONE = "none"
    HUMAN_INPUT_REQUIRED = "human_input_required"
    EXTERNAL_REVIEW_REQUIRED = "external_review_required"
    CRITICAL_SECURITY_FINDING = "critical_security_finding"
    RECOVERY_EXHAUSTED = "recovery_exhausted"
    GOVERNANCE_VIOLATION = "governance_violation"
    MILESTONE_COMPLETE = "milestone_complete"


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: GateName
    status: GateStatus
    reviewer_party: int = Field(ge=1, le=3)
    subject_party: int = Field(ge=1, le=3)
    evidence: list[Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]] = Field(
        default_factory=list
    )
    findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def prevent_self_approval(self) -> "GateDecision":
        if self.status == GateStatus.APPROVED and self.reviewer_party == self.subject_party:
            raise ValueError("an agent may not approve its own work")
        if self.status == GateStatus.APPROVED and not self.evidence:
            raise ValueError("an approval requires at least one evidence reference")
        return self


class MilestoneState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone_id: str
    title: str
    scope: list[str]
    out_of_scope: list[str]
    implementation_party: Literal[1] = 1
    gates: dict[GateName, GateDecision | None] = Field(
        default_factory=lambda: {gate: None for gate in GateName}
    )
    recovery_attempts: int = 0
    stop_reason: StopReason = StopReason.NONE

    def is_complete(self) -> bool:
        return all(
            decision is not None and decision.status == GateStatus.APPROVED
            for decision in self.gates.values()
        )


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    target_name: str
    target_repository: str
    target_ref: str
    workspace_root: Path


class GovernanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_architecture_review: bool
    require_security_review: bool
    require_test_review: bool
    require_documentation_update: bool
    require_milestone_report: bool
    require_external_review: bool
    prohibit_self_approval: bool
    prohibit_scope_expansion: bool
    maximum_recovery_attempts: int = Field(ge=0, le=10)
    maximum_agent_iterations_per_gate: int = Field(ge=1, le=20)
    stop_on_critical_security_finding: bool
    stop_on_external_review_unavailable: bool


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party: int = Field(ge=1, le=3)
    role: str
    model: str = ""
    endpoint: str | None = None
    mode: str | None = None


class InfrastructureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compose_files: list[Path] = Field(min_length=1)
    health_check_interval_seconds: int = Field(ge=5, le=3600)
    startup_timeout_seconds: int = Field(ge=30, le=3600)
    recovery_backoff_seconds: int = Field(ge=1, le=3600)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_compose_file(cls, data: object) -> object:
        """Accept a single ``compose_file`` string and wrap it into ``compose_files``."""
        if isinstance(data, dict) and "compose_file" in data and "compose_files" not in data:
            value = data.pop("compose_file")
            if isinstance(value, str | Path):
                data["compose_files"] = [value]
            elif isinstance(value, list):
                data["compose_files"] = value
        return data


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dsn_environment_variable: str = "HADA_DATABASE_DSN"
    migration_directory: Path = Path("/opt/hada/src/hada/db/migrations")
    connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    statement_timeout_seconds: int = Field(default=30, ge=1, le=3600)


class QueueConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url_environment_variable: str = "HADA_VALKEY_URL"
    namespace: str = "hada"
    consumer_group: str = "orchestrator"
    visibility_timeout_seconds: int = Field(default=300, ge=10, le=86400)
    maximum_delivery_attempts: int = Field(default=5, ge=1, le=100)
    maximum_stream_length: int = Field(default=10000, ge=100, le=10000000)


class EvidenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path
    signing_private_key: Path
    signing_public_key: Path


class ToolRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: str
    allowed_subcommands: list[str] = Field(default_factory=list)
    allowed_parties: list[int] = Field(default_factory=lambda: [1])
    maximum_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    network_access: bool = False
    read_only: bool = False


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_bubblewrap: bool = True
    trusted_binary_roots: list[Path]
    readonly_bind_paths: list[Path]
    maximum_output_bytes: int = Field(default=1048576, ge=1024, le=104857600)
    maximum_arguments: int = Field(default=128, ge=1, le=1024)
    maximum_argument_length: int = Field(default=4096, ge=32, le=65536)
    rules: list[ToolRuleConfig]


class MonitoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listen_host: str = "0.0.0.0"
    listen_port: int = Field(default=9108, ge=1024, le=65535)
    dependency_probe_interval_seconds: int = Field(default=15, ge=5, le=3600)
    unhealthy_exit_threshold: int = Field(default=4, ge=1, le=100)


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_egress_hosts: list[str]
    secrets_file: Path
    require_non_root_runtime: bool
    require_tls: bool
    redact_logs: bool


class HadaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig
    governance: GovernanceConfig
    agents: dict[str, AgentConfig]
    infrastructure: InfrastructureConfig
    database: DatabaseConfig
    queue: QueueConfig
    evidence: EvidenceConfig
    execution: ExecutionConfig
    monitoring: MonitoringConfig
    security: SecurityConfig

    @model_validator(mode="after")
    def validate_parties(self) -> "HadaConfig":
        parties = [agent.party for agent in self.agents.values()]
        if len(parties) != len(set(parties)):
            raise ValueError("each configured agent must use a distinct party number")
        if sorted(parties) != [1, 2, 3]:
            raise ValueError("parties 1, 2 and 3 must all be configured")
        return self
