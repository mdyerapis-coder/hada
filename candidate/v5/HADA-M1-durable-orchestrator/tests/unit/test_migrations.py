from pathlib import Path

import pytest

from hada.db.migrate import MigrationError, discover_migrations


def test_migrations_are_ordered_and_hashed() -> None:
    directory = Path(__file__).parents[2] / "src" / "hada" / "db" / "migrations"
    migrations = discover_migrations(directory)
    assert [migration.version for migration in migrations] == ["0001", "0002", "0003", "0004"]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_empty_migration_directory_rejected(tmp_path: Path) -> None:
    with pytest.raises(MigrationError):
        discover_migrations(tmp_path)


def test_missing_psycopg_is_reported_cleanly(tmp_path: Path) -> None:
    from hada.db.migrate import MigrationRunner

    (tmp_path / "0001_test.sql").write_text("SELECT 1;", encoding="utf-8")
    runner = MigrationRunner("postgresql://invalid", tmp_path)
    try:
        import psycopg  # noqa: F401
    except ImportError:
        with pytest.raises(MigrationError, match="psycopg"):
            runner.apply()


def test_migrations_enforce_audit_and_governance_in_database() -> None:
    directory = Path(__file__).parents[2] / "src" / "hada" / "db" / "migrations"
    sql = "\n".join(migration.sql for migration in discover_migrations(directory))
    assert "hada_enforce_audit_continuity" in sql
    assert "NEW.sequence := expected_sequence" in sql
    assert "hada_validate_gate_insert" in sql
    assert "hada_apply_gate_stop_reason" in sql
    assert "assigned_party IN (1, 2)" in sql
    assert "hada_valid_evidence_refs" in sql
