from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str
    sql: str


def discover_migrations(directory: Path) -> list[Migration]:
    if not directory.is_dir():
        raise MigrationError(f"migration directory does not exist: {directory}")
    migrations: list[Migration] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=path.name.split("_", maxsplit=1)[0],
                path=path,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    if not migrations:
        raise MigrationError(f"no migrations found in {directory}")
    versions = [migration.version for migration in migrations]
    if versions != sorted(set(versions)):
        raise MigrationError("migration versions must be unique and monotonically ordered")
    return migrations


class MigrationRunner:
    def __init__(self, dsn: str, directory: Path, connect_timeout_seconds: int = 10) -> None:
        self.dsn = dsn
        self.directory = directory
        self.connect_timeout_seconds = connect_timeout_seconds

    def apply(self) -> list[str]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise MigrationError("psycopg is required to apply PostgreSQL migrations") from exc

        applied_now: list[str] = []
        with psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout_seconds,
            row_factory=dict_row,
        ) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('hada_schema_migrations'))"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        checksum TEXT NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                rows: list[dict[str, Any]] = list(
                    connection.execute(
                        "SELECT version, checksum FROM schema_migrations ORDER BY version"
                    ).fetchall()
                )
                applied = {str(row["version"]): str(row["checksum"]) for row in rows}
                for migration in discover_migrations(self.directory):
                    existing = applied.get(migration.version)
                    if existing is not None:
                        if existing != migration.checksum:
                            raise MigrationError(
                                f"checksum mismatch for applied migration {migration.version}"
                            )
                        continue
                    connection.execute(migration.sql)
                    connection.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (migration.version, migration.checksum),
                    )
                    applied_now.append(migration.version)
        return applied_now
