from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_hada_consistency.py"


def test_consistency_check_reports_existing_divergence():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(SCRIPT.parents[1])],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "DIVERGENCE" in result.stdout
    assert "workspace/deploy-v4/HADA-M1-durable-orchestrator" in result.stdout
    assert "archives/HADA-M1-durable-orchestrator.zip" in result.stdout


def test_consistency_check_passes_when_all_copies_match(tmp_path):
    canonical = tmp_path / "canonical" / "HADA-M1-durable-orchestrator"
    copy = tmp_path / "copy" / "HADA-M1-durable-orchestrator"
    for tree in (canonical, copy):
        tree.mkdir(parents=True)
        (tree / "pyproject.toml").write_text("[project]\nname='hada'\n")
        (tree / "Dockerfile").write_text("FROM python:3.12\n")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--canonical",
            str(canonical),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "一致" not in result.stdout
    assert "No divergence detected" in result.stdout
