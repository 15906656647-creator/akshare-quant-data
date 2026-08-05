from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from akshare_data_test.stage14_automation import PipelineContext, _task_arguments


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "run_pipeline.py"), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_quality_control_help():
    result = run_cli("quality-control", "--help")
    assert result.returncode == 0
    assert "usage: akshare-data-test quality-control" in result.stdout
    assert "--validate-only" in result.stdout


def test_quality_control_dry_run_writes_nothing(tmp_path: Path):
    reports = tmp_path / "reports"
    database = tmp_path / "out.duckdb"
    result = run_cli(
        "quality-control",
        "--as-of-date",
        "2026-07-27",
        "--dry-run",
        "--input-database",
        str(tmp_path / "missing.duckdb"),
        "--reports-dir",
        str(reports),
        "--output-database",
        str(database),
    )
    assert result.returncode == 0
    assert "Stage 15 dry-run" in result.stdout
    assert not reports.exists()
    assert not database.exists()


def test_quality_control_validate_only_missing_input_is_blocked(tmp_path: Path):
    result = run_cli(
        "quality-control",
        "--as-of-date",
        "2026-07-27",
        "--validate-only",
        "--input-database",
        str(tmp_path / "missing.duckdb"),
        "--reports-dir",
        str(tmp_path / "reports"),
    )
    assert result.returncode == 2
    assert "BLOCKED" in result.stdout
    assert "input database does not exist" in result.stdout


def test_quality_control_real_run(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
    stage15_elapsed_evidence: None,
):
    run_id = str(uuid.uuid4())
    reports = tmp_path / "cli_reports"
    database = tmp_path / "cli_db.duckdb"
    result = run_cli(
        "quality-control",
        "--as-of-date",
        "2026-07-27",
        "--run-id",
        run_id,
        "--config",
        str(stage15_test_config),
        "--input-database",
        str(stage15_synthetic_db),
        "--output-database",
        str(database),
        "--reports-dir",
        str(reports),
    )
    assert result.returncode == 0, result.stderr
    assert "Stage 15 quality control: PASS_WITH_UNAVAILABLE_ITEMS" in result.stdout
    assert "unavailable_items: 6" in result.stdout
    assert "blocked_risks: 2" in result.stdout
    summary = reports / run_id / "quality_summary.json"
    assert summary.is_file()
    assert database.is_file()


def test_quality_control_invalid_date_is_rejected(tmp_path: Path):
    result = run_cli(
        "quality-control",
        "--as-of-date",
        "2026-99-99",
        "--validate-only",
        "--input-database",
        str(tmp_path / "missing.duckdb"),
    )
    assert result.returncode == 1
    assert "Stage 15 error" in result.stderr


def test_stage14_quality_check_mapping_unchanged(tmp_path: Path):
    context = PipelineContext(
        root=tmp_path,
        run_id=str(uuid.uuid4()),
        start_date="2025-01-01",
        end_date="2025-01-31",
    )
    arguments = _task_arguments("quality-check", context)
    assert arguments is not None
    assert "validate-stage5" in arguments
    assert "quality-control" not in arguments
