from __future__ import annotations

import os
import socket
from pathlib import Path

import typer
from rich.console import Console

from hada.audit.chain import AuditChain
from hada.config import load_config
from hada.crypto.signing import Ed25519Signer, Ed25519Verifier
from hada.db.migrate import MigrationRunner
from hada.db.postgres import PostgresStore
from hada.evidence.store import EvidenceStore
from hada.models import HadaConfig
from hada.orchestrator.publisher import OutboxPublisher
from hada.queue.broker import DurableQueue, RedisStreamBackend
from hada.runtime import OrchestratorRuntime
from hada.workspaces.manager import GitRunner, RepositoryPolicy, WorkspaceManager

app = typer.Typer(no_args_is_help=True)
keys_app = typer.Typer(no_args_is_help=True)
db_app = typer.Typer(no_args_is_help=True)
evidence_app = typer.Typer(no_args_is_help=True)
audit_app = typer.Typer(no_args_is_help=True)
workspace_app = typer.Typer(no_args_is_help=True)
orchestrator_app = typer.Typer(no_args_is_help=True)
app.add_typer(keys_app, name="keys")
app.add_typer(db_app, name="db")
app.add_typer(evidence_app, name="evidence")
app.add_typer(audit_app, name="audit")
app.add_typer(workspace_app, name="workspace")
app.add_typer(orchestrator_app, name="orchestrator")
console = Console()


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        console.print(f"[red]missing environment variable[/red]: {name}")
        raise typer.Exit(code=2)
    return value


def _store(config_path: Path) -> tuple[PostgresStore, HadaConfig]:
    config = load_config(config_path)
    dsn = _required_environment(config.database.dsn_environment_variable)
    signer = Ed25519Signer.load(config.evidence.signing_private_key)
    store = PostgresStore(
        dsn,
        signer,
        connect_timeout_seconds=config.database.connect_timeout_seconds,
        statement_timeout_seconds=config.database.statement_timeout_seconds,
    )
    return store, config


@app.command("validate-config")
def validate_config(
    config: Path = typer.Option(..., exists=True, readable=True),
    require_target: bool = typer.Option(
        False, help="Require Hermesctl target and model configuration"
    ),
) -> None:
    loaded = load_config(config)
    console.print(f"[green]valid[/green]: {loaded.project.name} -> {loaded.project.target_name}")
    if require_target and not loaded.project.target_repository:
        console.print("[yellow]stop condition[/yellow]: target_repository is not configured")
        raise typer.Exit(code=2)
    missing_models = [
        name
        for name, agent in loaded.agents.items()
        if agent.party in {1, 2} and not agent.model
    ]
    if require_target and missing_models:
        console.print(
            f"[yellow]stop condition[/yellow]: models are missing for {', '.join(missing_models)}"
        )
        raise typer.Exit(code=2)


@app.command("doctor")
def doctor() -> None:
    import shutil

    required = ["docker", "git", "curl", "jq", "bwrap"]
    missing = [binary for binary in required if shutil.which(binary) is None]
    if missing:
        console.print(f"[red]missing[/red]: {', '.join(missing)}")
        raise typer.Exit(code=1)
    console.print("[green]host prerequisites detected[/green]")


@keys_app.command("generate")
def keys_generate(
    private_key: Path = typer.Option(...),
    public_key: Path = typer.Option(...),
    force: bool = typer.Option(False),
) -> None:
    if not force and (private_key.exists() or public_key.exists()):
        console.print("[red]refusing to overwrite existing signing keys[/red]")
        raise typer.Exit(code=2)
    signer = Ed25519Signer.generate()
    signer.save(private_key, public_key)
    console.print(f"[green]generated[/green] Ed25519 key {signer.key_id}")


@db_app.command("migrate")
def db_migrate(config: Path = typer.Option(..., exists=True, readable=True)) -> None:
    loaded = load_config(config)
    dsn = _required_environment(loaded.database.dsn_environment_variable)
    applied = MigrationRunner(
        dsn,
        loaded.database.migration_directory,
        loaded.database.connect_timeout_seconds,
    ).apply()
    if applied:
        console.print(f"[green]applied migrations[/green]: {', '.join(applied)}")
    else:
        console.print("[green]database schema is current[/green]")


@evidence_app.command("add")
def evidence_add(
    source: Path = typer.Argument(..., exists=True, readable=True),
    config: Path = typer.Option(..., exists=True, readable=True),
    logical_name: str | None = typer.Option(None),
    media_type: str = typer.Option("application/octet-stream"),
    register: bool = typer.Option(True),
) -> None:
    loaded = load_config(config)
    signer = Ed25519Signer.load(loaded.evidence.signing_private_key)
    store = EvidenceStore(loaded.evidence.root, signer)
    manifest = store.put_file(
        source,
        logical_name=logical_name,
        media_type=media_type,
    )
    if register:
        database, _ = _store(config)
        object_path = store.verify(manifest, signer.verifier())
        database.register_evidence(manifest, object_path)
    console.print(f"[green]evidence[/green]: sha256:{manifest.digest}")


@evidence_app.command("verify")
def evidence_verify(
    digest: str,
    config: Path = typer.Option(..., exists=True, readable=True),
) -> None:
    loaded = load_config(config)
    signer = Ed25519Signer.load(loaded.evidence.signing_private_key)
    verifier = Ed25519Verifier.load(loaded.evidence.signing_public_key)
    store = EvidenceStore(loaded.evidence.root, signer)
    manifest = store.load_manifest(digest)
    store.verify(manifest, verifier)
    console.print(f"[green]verified[/green]: sha256:{digest}")


@audit_app.command("verify")
def audit_verify(config: Path = typer.Option(..., exists=True, readable=True)) -> None:
    store, loaded = _store(config)
    verifier = Ed25519Verifier.load(loaded.evidence.signing_public_key)
    records = list(store.iter_audit())
    AuditChain.verify(records, verifier)
    console.print(f"[green]verified[/green]: {len(records)} audit records")


@workspace_app.command("create")
def workspace_create(
    milestone_id: str,
    task_id: str,
    config: Path = typer.Option(..., exists=True, readable=True),
    repository: str | None = typer.Option(None),
    ref: str | None = typer.Option(None),
) -> None:
    loaded = load_config(config)
    repository_url = repository or loaded.project.target_repository
    if not repository_url:
        console.print("[red]target repository is not configured[/red]")
        raise typer.Exit(code=2)
    state_root = Path(os.environ.get("HADA_STATE_DIR", "/var/lib/hada"))
    manager = WorkspaceManager(
        workspace_root=loaded.project.workspace_root,
        state_root=state_root,
        repository_policy=RepositoryPolicy(loaded.security.allowed_egress_hosts),
        git=GitRunner(state_root / "git-home"),
    )
    record = manager.create(
        milestone_id=milestone_id,
        task_id=task_id,
        repository_url=repository_url,
        requested_ref=ref or loaded.project.target_ref,
    )
    database, _ = _store(config)
    database.register_workspace(record)
    console.print(f"[green]workspace[/green]: {record.path} @ {record.resolved_commit}")


@orchestrator_app.command("run")
def orchestrator_run(config: Path = typer.Option(..., exists=True, readable=True)) -> None:
    store, loaded = _store(config)
    queue_url = _required_environment(loaded.queue.url_environment_variable)
    queue = DurableQueue(
        RedisStreamBackend(queue_url),
        namespace=loaded.queue.namespace,
        consumer_group=loaded.queue.consumer_group,
        maximum_delivery_attempts=loaded.queue.maximum_delivery_attempts,
        maximum_stream_length=loaded.queue.maximum_stream_length,
        visibility_timeout_seconds=loaded.queue.visibility_timeout_seconds,
    )
    publisher = OutboxPublisher(
        store,
        queue,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        maximum_attempts=loaded.queue.maximum_delivery_attempts,
        retry_delay_seconds=loaded.infrastructure.recovery_backoff_seconds,
    )
    runtime = OrchestratorRuntime(
        store,
        queue,
        publisher,
        listen_host=loaded.monitoring.listen_host,
        listen_port=loaded.monitoring.listen_port,
        probe_interval_seconds=loaded.monitoring.dependency_probe_interval_seconds,
        unhealthy_exit_threshold=loaded.monitoring.unhealthy_exit_threshold,
    )
    raise typer.Exit(code=runtime.run())


if __name__ == "__main__":
    app()
