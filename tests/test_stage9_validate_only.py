from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from akshare_data_test.stage9_build import validate_stage9_inputs
from test_stage9_database_integration import prepare


ROOT = Path(__file__).resolve().parents[1]


def validate(root, source, output):
    return validate_stage9_inputs(
        config_path=root / "config/stage9.yml", input_database=source,
        output_database=output, as_of_date=pd.Timestamp("2026-04-22"),
    )


def test_validate_only_is_read_only_and_ready(tmp_path):
    source = prepare(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "new" / "style.duckdb"
    result = validate(tmp_path, source, output)
    assert result["status"] == "READY"
    assert result["qfq_row_count"] == 80
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not output.exists() and not output.parent.exists()


def test_validate_rejects_missing_corrupt_schema_route_and_duplicate(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy2(ROOT / "config/stage9.yml", tmp_path / "config/stage9.yml")
    missing = validate(tmp_path, tmp_path / "missing.duckdb", tmp_path / "a.duckdb")
    assert missing["status"] == "FAILED"
    corrupt = tmp_path / "corrupt.duckdb"
    corrupt.write_bytes(b"broken")
    assert validate(tmp_path, corrupt, tmp_path / "b.duckdb")["status"] == "FAILED"
    for name, sql in {
        "missing-table": "CREATE TABLE other(x INTEGER)",
        "missing-field": "CREATE TABLE fact_stock_daily(symbol VARCHAR,trade_date DATE,adjust_type VARCHAR)",
        "raw-only": "CREATE TABLE fact_stock_daily(symbol VARCHAR,trade_date DATE,adjust_type VARCHAR,open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume_share DOUBLE,amount_cny DOUBLE,turnover_rate DOUBLE); INSERT INTO fact_stock_daily VALUES ('000001',DATE '2026-01-01','raw',1,1,1,1,1,1,1)",
    }.items():
        path = tmp_path / f"{name}.duckdb"
        with duckdb.connect(str(path)) as connection:
            connection.execute(sql)
        result = validate(tmp_path, path, tmp_path / f"{name}-out.duckdb")
        assert result["status"] in {"FAILED", "BLOCKED"}


def test_output_paths_protect_input_stage7_and_stage8(tmp_path):
    source = prepare(tmp_path)
    assert validate(tmp_path, source, source)["status"] == "FAILED"
    for name in ("akshare_features_stage7.duckdb", "akshare_limit_events_stage8.duckdb"):
        result = validate(tmp_path, source, tmp_path / name)
        assert result["status"] == "FAILED"
        assert "output_database_is_protected_baseline" in result["errors"]


def cli_root(tmp_path):
    source = prepare(tmp_path)
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy2(ROOT / "run_pipeline.py", tmp_path / "run_pipeline.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return source, env


def test_cli_help_validate_only_and_dry_run(tmp_path):
    source, env = cli_root(tmp_path)
    help_result = subprocess.run([sys.executable, "run_pipeline.py", "analyze-style", "--help"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert help_result.returncode == 0
    for option in ("--config", "--input-database", "--output-database", "--as-of-date", "--start-date", "--symbols", "--windows", "--validate-only", "--dry-run", "--debug"):
        assert option in help_result.stdout
    output = tmp_path / "style.duckdb"
    base = [sys.executable, "run_pipeline.py", "analyze-style", "--as-of-date", "2026-04-22", "--config", str(tmp_path / "config/stage9.yml"), "--input-database", str(source), "--output-database", str(output)]
    validated = subprocess.run([*base, "--validate-only"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert validated.returncode == 0 and json.loads(validated.stdout)["status"] == "READY"
    dry = subprocess.run([*base, "--dry-run", "--run-id", "cli-dry"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert dry.returncode == 0 and "Stage 9 style analysis: PASS" in dry.stdout
    assert not output.exists() and not (tmp_path / "reports").exists()


def test_cli_user_error_hides_traceback_unless_debug(tmp_path):
    _, env = cli_root(tmp_path)
    base = [sys.executable, "run_pipeline.py", "analyze-style", "--as-of-date", "bad-date", "--validate-only"]
    normal = subprocess.run(base, cwd=tmp_path, env=env, capture_output=True, text=True)
    debug = subprocess.run([*base, "--debug"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert normal.returncode == debug.returncode == 1
    assert "Stage 9 error:" in normal.stderr and "Traceback" not in normal.stderr
    assert "Traceback" in debug.stderr

