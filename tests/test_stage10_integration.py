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
import pytest

from akshare_data_test.quality.fundamental_checks import verify_stage10_persistence
from akshare_data_test.stage10_build import analyze_stage10, validate_stage10_inputs


ROOT = Path(__file__).resolve().parents[1]


def _input_frames():
    statements = []
    quarters = [
        ("2024-03-31", 100), ("2024-06-30", 220),
        ("2024-09-30", 360), ("2024-12-31", 520),
        ("2025-03-31", 130), ("2025-06-30", 280),
        ("2025-09-30", 450), ("2025-12-31", 640),
    ]
    row_number = 0
    for period, revenue in quarters:
        flow_values = {
            "TOTAL_OPERATE_INCOME": revenue,
            "TOTAL_OPERATE_COST": revenue * 0.6,
            "OPERATE_PROFIT": revenue * 0.15,
            "TOTAL_PROFIT": revenue * 0.14,
            "NETPROFIT": revenue * 0.12,
            "PARENT_NETPROFIT": revenue * 0.11,
            "DEDUCT_PARENT_NETPROFIT": revenue * 0.10,
            "BASIC_EPS": revenue / 100,
        }
        balance_values = {
            "TOTAL_ASSETS": 1000 + revenue,
            "TOTAL_LIABILITIES": 400 + revenue * 0.2,
            "TOTAL_EQUITY": 600 + revenue * 0.8,
        }
        for statement_type, values in [
            ("profit_statement", flow_values),
            ("balance_sheet", balance_values),
            ("cash_flow_statement", {"NETCASH_OPERATE": revenue * 0.13}),
        ]:
            for column, value in values.items():
                row_number += 1
                statements.append({
                    "transform_run_id": "transform", "source_run_id": "finance-source",
                    "symbol": "000001", "exchange": "SZ", "statement_type": statement_type,
                    "report_period": pd.Timestamp(period),
                    "announcement_date": pd.Timestamp(period) + pd.Timedelta(days=45),
                    "line_item_code": "hash", "line_item_name_source": column,
                    "line_item_value": value, "line_item_value_raw": str(value),
                    "unit_source": "CNY_yuan", "unit_canonical": "CNY_per_share" if column == "BASIC_EPS" else "CNY_yuan",
                    "potential_lookahead": False, "announcement_date_status": "available",
                    "source_column": column, "source_file": "fixture/financial.parquet",
                    "source_row_number": row_number,
                })
    spot = pd.DataFrame([{
        "transform_run_id": "transform", "source_run_id": "spot-source",
        "snapshot_at": pd.Timestamp("2026-07-27T01:00:00Z"),
        "snapshot_scope": "target_16", "symbol": "000001", "exchange": "SZ",
        "name": "fixture", "latest_price": 10.0, "pct_change": 0.0,
        "price_change": 0.0, "volume_lot": 1.0, "volume_share": 100.0,
        "amount_cny": 1000.0, "amplitude": 0.0, "turnover_rate": 0.01,
        "volume_ratio": 1.0, "pe_dynamic": 12.0, "pb": 2.0,
        "market_cap_cny": 100000.0, "float_market_cap_cny": 80000.0,
        "source_payload_json": "{}", "source_file": "fixture/spot.parquet",
    }])
    return pd.DataFrame(statements), spot


def prepare_input(tmp_path: Path) -> Path:
    statements, spot = _input_frames()
    database = tmp_path / "input.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.register("statements", statements)
        connection.execute("CREATE TABLE fact_financial_statement AS SELECT * FROM statements")
        connection.register("spot", spot)
        connection.execute("CREATE TABLE fact_stock_spot AS SELECT * FROM spot")
        connection.execute("CREATE TABLE etl_run(transform_run_id VARCHAR, status VARCHAR)")
        connection.execute("INSERT INTO etl_run VALUES ('transform', 'PASS')")
    database.with_suffix(database.suffix + ".manifest.json").write_text(
        json.dumps({
            "stage": "stage5", "validation_status": "PASS",
            "verified_tag": "stage5-verified-fixture", "run_id": "transform",
        }),
        encoding="utf-8",
    )
    return database


def prepare_root(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "sql").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "config/stage10.yml", tmp_path / "config/stage10.yml")
    shutil.copy2(ROOT / "config/universe.yml", tmp_path / "config/universe.yml")
    shutil.copy2(ROOT / "config/metric_definition.yml", tmp_path / "config/metric_definition.yml")
    shutil.copy2(ROOT / "sql/stage10_schema.sql", tmp_path / "sql/stage10_schema.sql")


def test_validate_only_is_read_only_and_does_not_create_output(tmp_path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "new" / "stage10.duckdb"
    result = validate_stage10_inputs(
        config_path=tmp_path / "config/stage10.yml", input_database=source,
        output_database=output, as_of_date=pd.Timestamp("2026-07-27"),
        symbols=["000001"],
    )
    assert result["status"] == "READY"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not output.exists() and not output.parent.exists()


def test_validation_rejects_missing_database_same_output_and_protected_baselines(tmp_path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    missing = validate_stage10_inputs(
        config_path=tmp_path / "config/stage10.yml", input_database=tmp_path / "missing.duckdb",
        output_database=tmp_path / "out.duckdb", as_of_date=pd.Timestamp("2026-07-27"),
        symbols=["000001"],
    )
    assert missing["status"] == "BLOCKED"
    same = validate_stage10_inputs(
        config_path=tmp_path / "config/stage10.yml", input_database=source,
        output_database=source, as_of_date=pd.Timestamp("2026-07-27"), symbols=["000001"],
    )
    assert same["status"] == "BLOCKED"
    for name in (
        "akshare_features_stage7.duckdb", "akshare_limit_events_stage8.duckdb",
        "akshare_style_stage9.duckdb",
    ):
        result = validate_stage10_inputs(
            config_path=tmp_path / "config/stage10.yml", input_database=source,
            output_database=tmp_path / name, as_of_date=pd.Timestamp("2026-07-27"),
            symbols=["000001"],
        )
        assert result["status"] == "BLOCKED"
        assert "output_database_is_protected_baseline" in result["blocking_reasons"]


def test_dry_run_calculates_without_database_or_reports(tmp_path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    output = tmp_path / "stage10.duckdb"
    report, exit_code = analyze_stage10(
        root=tmp_path, config_path=tmp_path / "config/stage10.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-07-27"), symbols=["000001"],
        run_id="dry-run", dry_run=True,
    )
    assert exit_code == 0
    assert report["run_status"] == "PASS"
    assert report["valuation_scope"] == "current valuation snapshot"
    assert not output.exists()
    assert not (tmp_path / "reports").exists()


def test_full_run_writes_database_and_seven_consistent_reports(tmp_path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    output = tmp_path / "stage10.duckdb"
    report, exit_code = analyze_stage10(
        root=tmp_path, config_path=tmp_path / "config/stage10.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-07-27"), symbols=["000001"],
        run_id="formal-run", dry_run=False,
    )
    assert exit_code == 0 and report["run_status"] == "PASS"
    expected = {
        "stage10_validation.md", "stage10_independent_audit.md", "stage10_run.json",
        "stage10_data_quality.csv", "stage10_fundamental_summary.csv",
        "stage10_fundamental_indicator.csv", "stage10_valuation_snapshot.csv",
    }
    assert {path.name for path in (tmp_path / "reports").iterdir()} == expected
    payload = json.loads((tmp_path / "reports/stage10_run.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "formal-run"
    with duckdb.connect(str(output), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM analysis.fundamental_summary WHERE run_id='formal-run'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT valuation_type FROM analysis.valuation_snapshot"
        ).fetchone()[0] == "snapshot"


def _cli_root(tmp_path: Path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy2(ROOT / "run_pipeline.py", tmp_path / "run_pipeline.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return source, env


def test_cli_help_validate_only_and_dry_run(tmp_path):
    source, env = _cli_root(tmp_path)
    help_result = subprocess.run(
        [sys.executable, "run_pipeline.py", "analyze-fundamental", "--help"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert help_result.returncode == 0
    for option in (
        "--config", "--input-database", "--output-database", "--as-of-date",
        "--input-manifest", "--symbols", "--validate-only", "--dry-run", "--debug",
    ):
        assert option in help_result.stdout
    output = tmp_path / "stage10.duckdb"
    base = [
        sys.executable, "run_pipeline.py", "analyze-fundamental",
        "--as-of-date", "2026-07-27", "--config", str(tmp_path / "config/stage10.yml"),
        "--input-database", str(source), "--output-database", str(output),
        "--input-manifest", str(source.with_suffix(source.suffix + ".manifest.json")),
        "--symbols", "000001",
    ]
    validated = subprocess.run(
        [*base, "--validate-only"], cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert validated.returncode == 0
    assert json.loads(validated.stdout)["status"] == "READY"
    dry = subprocess.run(
        [*base, "--dry-run", "--run-id", "cli-dry"], cwd=tmp_path,
        env=env, capture_output=True, text=True,
    )
    assert dry.returncode == 0
    assert "Stage 10 fundamental analysis: PASS" in dry.stdout
    assert not output.exists() and not (tmp_path / "reports").exists()


def test_cli_errors_hide_traceback_unless_debug(tmp_path):
    _, env = _cli_root(tmp_path)
    base = [
        sys.executable, "run_pipeline.py", "analyze-fundamental",
        "--as-of-date", "bad-date", "--validate-only",
    ]
    normal = subprocess.run(base, cwd=tmp_path, env=env, capture_output=True, text=True)
    debug = subprocess.run([*base, "--debug"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert normal.returncode == debug.returncode == 1
    assert "Stage 10 error:" in normal.stderr and "Traceback" not in normal.stderr
    assert "Traceback" in debug.stderr


def test_cli_validate_only_missing_manifest_exits_two(tmp_path):
    source, env = _cli_root(tmp_path)
    manifest = source.with_suffix(source.suffix + ".manifest.json")
    manifest.unlink()
    output = tmp_path / "stage10.duckdb"
    result = subprocess.run([
        sys.executable, "run_pipeline.py", "analyze-fundamental",
        "--as-of-date", "2026-07-27", "--config", str(tmp_path / "config/stage10.yml"),
        "--input-database", str(source), "--input-manifest", str(manifest),
        "--output-database", str(output), "--symbols", "000001", "--validate-only",
    ], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "BLOCKED"
    assert not output.exists()


def test_validate_only_blocks_missing_manifest_without_writing_database(tmp_path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    source.with_suffix(source.suffix + ".manifest.json").unlink()
    output = tmp_path / "stage10.duckdb"
    result = validate_stage10_inputs(
        config_path=tmp_path / "config/stage10.yml", input_database=source,
        output_database=output, as_of_date=pd.Timestamp("2026-07-27"), symbols=["000001"],
    )
    assert result["status"] == "BLOCKED"
    assert any("manifest does not exist" in reason for reason in result["blocking_reasons"])
    assert not output.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "stage4"},
        {"validation_status": "FAIL"},
        {"run_id": "unverified-run"},
    ],
)
def test_validate_only_blocks_invalid_or_unverified_stage5_manifest(tmp_path, changes):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    manifest_path = source.with_suffix(source.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(changes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "stage10.duckdb"
    result = validate_stage10_inputs(
        config_path=tmp_path / "config/stage10.yml", input_database=source,
        output_database=output, as_of_date=pd.Timestamp("2026-07-27"), symbols=["000001"],
    )
    assert result["status"] == "BLOCKED"
    assert not output.exists()


def _formal_run(tmp_path: Path):
    prepare_root(tmp_path)
    source = prepare_input(tmp_path)
    output = tmp_path / "stage10.duckdb"
    report, exit_code = analyze_stage10(
        root=tmp_path, config_path=tmp_path / "config/stage10.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-07-27"), symbols=["000001"],
        run_id="formal-run", dry_run=False,
    )
    assert exit_code == 0
    return output, report


@pytest.mark.parametrize("target", ["csv", "json", "markdown", "duckdb"])
def test_artifact_consistency_detects_field_tampering(tmp_path, target):
    output, report = _formal_run(tmp_path)
    reports = tmp_path / "reports"
    if target == "csv":
        path = reports / "stage10_fundamental_summary.csv"
        frame = pd.read_csv(path)
        frame.loc[0, "profitability_score"] += 0.25
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    elif target == "json":
        path = reports / "stage10_run.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["publication_status"] = "tampered"
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif target == "markdown":
        path = reports / "stage10_validation.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nTAMPERED\n", encoding="utf-8")
    else:
        with duckdb.connect(str(output)) as connection:
            connection.execute(
                "UPDATE analysis.fundamental_summary SET profitability_score=profitability_score+0.25 "
                "WHERE run_id='formal-run'"
            )
    result = verify_stage10_persistence(
        output, reports, run_id="formal-run",
        expected_counts={
            "raw": report["raw_row_count"], "facts": report["fact_row_count"],
            "indicators": report["indicator_row_count"],
            "summaries": report["summary_row_count"],
            "valuations": report["valuation_row_count"],
        },
        checked_at=pd.Timestamp("2026-07-27", tz="UTC"),
    )
    check = result.loc[result["check_name"].eq("database_report_consistent")].iloc[0]
    assert check["status"] == "FAIL"
    assert check["severity"] == "ERROR"
