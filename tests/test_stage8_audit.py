from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = [
    ROOT / "src/akshare_data_test/limit_rules.py",
    ROOT / "src/akshare_data_test/limit_event_detection.py",
    ROOT / "src/akshare_data_test/stage8_analysis.py",
    ROOT / "src/akshare_data_test/stage8_build.py",
    ROOT / "src/akshare_data_test/storage/limit_event_repository.py",
    ROOT / "src/akshare_data_test/quality/limit_event_checks.py",
]


def test_stage8_runtime_has_no_network_clients():
    text = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME)
    prohibited = [
        r"\bimport\s+akshare(?:\s|$)",
        r"\bfrom\s+akshare(?:\s|$)",
        r"\bimport\s+requests(?:\s|$)",
        r"\bimport\s+httpx(?:\s|$)",
        r"\burllib\.request\b",
    ]
    assert not any(re.search(pattern, text, flags=re.MULTILINE) for pattern in prohibited)


def test_default_config_is_fail_closed_and_contains_no_guessed_rules():
    config = yaml.safe_load((ROOT / "config/stage8.yml").read_text(encoding="utf-8"))
    assert config["price_adjust_type"] == "raw"
    assert config["rule_records"] == []
    assert config["security_status_records"] == []
    assert config["source_notes"]["gap_proxy_usage"].endswith("not_formal_event")


def test_cli_help_exposes_stage8_parameters():
    result = subprocess.run(
        [sys.executable, "run_pipeline.py", "analyze-limit-events", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for option in (
        "--config", "--source-database", "--output-database", "--as-of-date",
        "--start-date", "--dry-run", "--validate-only", "--run-id",
    ):
        assert option in result.stdout


def test_validate_only_rejects_empty_database_without_traceback(tmp_path):
    source = tmp_path / "placeholder.duckdb"
    source.touch()
    output = tmp_path / "must-not-exist.duckdb"
    result = subprocess.run(
        [
            sys.executable, "run_pipeline.py", "analyze-limit-events",
            "--as-of-date", "2026-07-27", "--validate-only",
            "--source-database", str(source), "--output-database", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert '"status": "FAILED"' in result.stdout
    assert "source_database_empty_file" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_missing_source_returns_nonzero_without_output(tmp_path):
    output = tmp_path / "must-not-exist.duckdb"
    result = subprocess.run(
        [
            sys.executable, "run_pipeline.py", "analyze-limit-events",
            "--as-of-date", "2026-07-27", "--validate-only",
            "--source-database", str(tmp_path / "missing.duckdb"),
            "--output-database", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert '"status": "FAILED"' in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not output.exists()


def test_forbidden_runtime_artifacts_are_not_staged():
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    staged = [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]
    forbidden_parts = (
        "database/", "data/", "logs/", ".duckdb", ".parquet", ".env",
        "__pycache__", ".pytest_cache",
    )
    assert not [
        path for path in staged if any(part in path for part in forbidden_parts)
    ]


def test_required_stage8_audit_reports_exist_and_do_not_report_zero_as_no_data():
    required = [
        "stage8_validation.md", "stage8_independent_audit.md",
        "stage8_rule_coverage.csv", "stage8_security_status_coverage.csv",
        "stage8_event_sample.csv", "stage8_annual_event_summary.csv",
        "stage8_data_quality.csv", "stage8_run.json",
    ]
    for name in required:
        assert (ROOT / "reports" / name).is_file()
    run = (ROOT / "reports/stage8_run.json").read_text(encoding="utf-8")
    assert '"formal_event_count": null' in run
    assert '"publication_status": "blocked"' in run
