from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.stage12_analysis import analyze_stage12
from akshare_data_test.storage.stage12_repository import stage12_counts
from test_stage12_analysis import AS_OF, fundamental_fixture, price_fixture


ROOT = Path(__file__).resolve().parents[1]


def test_repository_reports_idempotency_and_conflict(tmp_path):
    database = tmp_path / "stage12.duckdb"
    reports = tmp_path / "reports"
    kwargs = dict(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(),
        fundamental_frame=fundamental_fixture(), config_path=ROOT / "config/stage12.yml",
        output_database=database, run_id="repo-run", reports_dir=reports,
    )
    first, code = analyze_stage12(**kwargs)
    assert code == 0 and first["status"] == "READY"
    expected = {"active": 2, "breakouts": 2, "ranges": 2, "combined": 2, "quality": 17}
    assert stage12_counts(database, "repo-run") == expected
    second, second_code = analyze_stage12(**kwargs)
    assert second_code == 0 and first == second
    assert stage12_counts(database, "repo-run") == expected
    required = {
        "stage12_run.json", "stage12_analysis.md", "stage12_active_stocks.csv",
        "stage12_volume_breakouts.csv", "stage12_range_bound.csv",
        "stage12_fundamental_price_volume.csv", "stage12_quality.csv",
    }
    assert required == {path.name for path in reports.iterdir()}
    changed = price_fixture()
    changed.loc[changed.index[-1], "volume"] += 1
    with pytest.raises(ValueError, match="different input"):
        analyze_stage12(**{**kwargs, "price_frame": changed})
    assert stage12_counts(database, "repo-run") == expected


def test_transaction_failure_does_not_destroy_existing_run(tmp_path, monkeypatch):
    database = tmp_path / "stage12.duckdb"
    kwargs = dict(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(),
        fundamental_frame=fundamental_fixture(), config_path=ROOT / "config/stage12.yml",
        output_database=database, run_id="stable", reports_dir=tmp_path / "reports",
    )
    analyze_stage12(**kwargs)
    before = stage12_counts(database, "stable")
    original = duckdb.DuckDBPyConnection.register
    calls = {"count": 0}

    def fail_once(self, name, frame):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected failure")
        return original(self, name, frame)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "register", fail_once)
    with pytest.raises(RuntimeError, match="injected"):
        analyze_stage12(**kwargs)
    assert stage12_counts(database, "stable") == before


def test_cli_outputs_json_and_dry_run_is_read_only(tmp_path):
    price = tmp_path / "prices.csv"
    fundamental = tmp_path / "fundamentals.csv"
    price_fixture().to_csv(price, index=False)
    fundamental_fixture().to_csv(fundamental, index=False)
    database = tmp_path / "cli.duckdb"
    reports = tmp_path / "reports"
    command = [
        sys.executable, str(ROOT / "run_pipeline.py"), "analyze-stage12",
        "--as-of-date", "2026-07-27", "--price-input", str(price),
        "--fundamental-input", str(fundamental), "--reports-dir", str(reports),
        "--output-database", str(database), "--run-id", "cli-run", "--dry-run",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "READY"
    assert payload["network_calls"] == 0
    assert not database.exists()
    assert not reports.exists()


def test_cli_invalid_argument_is_nonzero_and_stdout_clean(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "run_pipeline.py"), "analyze-stage12",
         "--as-of-date", "2026-07-27", "--price-input", str(tmp_path / "missing.csv")],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "does not exist" in completed.stderr


def test_cli_invalid_fundamental_is_structured_block_and_writes_nothing(tmp_path):
    price = tmp_path / "prices.csv"
    fundamental = tmp_path / "fundamentals.csv"
    price_fixture().to_csv(price, index=False)
    invalid = fundamental_fixture().drop(columns=["growth_score"])
    invalid["revenue_growth"] = float("inf")
    invalid["profit_growth"] = 0.1
    invalid.to_csv(fundamental, index=False)
    database = tmp_path / "blocked.duckdb"
    reports = tmp_path / "reports"
    completed = subprocess.run([
        sys.executable, str(ROOT / "run_pipeline.py"), "analyze-stage12",
        "--as-of-date", "2026-07-27", "--price-input", str(price),
        "--fundamental-input", str(fundamental), "--reports-dir", str(reports),
        "--output-database", str(database), "--run-id", "cli-invalid", "--dry-run",
    ], cwd=ROOT, text=True, capture_output=True, check=False)
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "BLOCKED"
    assert any("revenue_growth" in reason for reason in payload["blocking_reasons"])
    assert payload["database_write_status"] == "not_written_blocked"
    assert completed.stderr == ""
    assert not database.exists()
    assert not reports.exists()
