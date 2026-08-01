import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.fundamental_analysis import (
    FACT_COLUMNS, INDICATOR_COLUMNS, RAW_COLUMNS, SUMMARY_COLUMNS, VALUATION_COLUMNS,
)
from akshare_data_test.storage.fundamental_repository import (
    AUDIT_COLUMNS, QUALITY_COLUMNS, stage10_counts, write_stage10_run,
)


ROOT = Path(__file__).resolve().parents[1]
CREATED = pd.Timestamp("2026-07-27", tz="UTC")


def _frames(run_id="run-one", created=CREATED, status="PASS"):
    raw = pd.DataFrame([{
        "run_id": run_id, "symbol": "000001", "statement_type": "balance_sheet",
        "report_period": pd.Timestamp("2025-12-31"), "announcement_date": pd.Timestamp("2026-03-01"),
        "update_time": pd.NaT, "source_name": "AKShare", "source_reference": "fixture",
        "source_run_id": "source", "source_column": "TOTAL_ASSETS",
        "source_item_code": "hash", "source_item_name": "TOTAL_ASSETS",
        "source_value": 100.0, "source_unit": "CNY_yuan", "cumulative_flag": False,
        "version": "source", "version_key": "version-key",
    }], columns=RAW_COLUMNS)
    facts = pd.DataFrame([{
        "run_id": run_id, "symbol": "000001", "statement_type": "balance_sheet",
        "report_period": pd.Timestamp("2025-12-31"), "announcement_date": pd.Timestamp("2026-03-01"),
        "update_time": pd.NaT, "item_code": "total_assets", "item_value": 100.0,
        "source_field": "TOTAL_ASSETS", "selected_source": "TOTAL_ASSETS",
        "conflict_flag": False, "conflict_value_mismatch": False,
        "cumulative_value": None, "single_quarter_value": 100.0, "period_type": "FY",
        "conversion_status": "not_applicable", "unit": "CNY_yuan", "cumulative_flag": False,
        "source_name": "AKShare", "source_reference": "fixture", "source_run_id": "source",
        "version": "source", "version_key": "version-key",
    }], columns=FACT_COLUMNS)
    indicators = pd.DataFrame([{
        "run_id": run_id, "symbol": "000001", "report_period": pd.Timestamp("2025-12-31"),
        "indicator_code": "total_assets", "indicator_value": 100.0,
        "calculation_status": "calculated", "calculation_version": "v1",
        "source_period_start": pd.Timestamp("2025-12-31"),
        "source_period_end": pd.Timestamp("2025-12-31"), "created_at": created,
    }], columns=INDICATOR_COLUMNS)
    summaries = pd.DataFrame([{
        "run_id": run_id, "symbol": "000001", "as_of_date": pd.Timestamp("2026-07-27"),
        "revenue_growth": None, "profit_growth": None, "profitability_score": 0.0,
        "financial_health_score": 0.0, "valuation_status": "current valuation snapshot unavailable",
        "summary_explanation": "真实指标不可用；不构成投资建议。", "model_version": "v1",
        "config_version": "1.0", "publication_status": "formal", "created_at": created,
    }], columns=SUMMARY_COLUMNS)
    valuations = pd.DataFrame([{
        "run_id": run_id, "snapshot_time": created, "symbol": "000001", "pe": None,
        "pb": None, "market_cap": 1000.0, "source": "AKShare", "valuation_type": "snapshot",
        "pe_status": "unavailable", "pb_status": "unavailable",
        "valuation_status": "current valuation snapshot; PE unavailable; PB unavailable",
        "source_run_id": "spot",
        "created_at": created,
    }], columns=VALUATION_COLUMNS)
    quality = pd.DataFrame([{
        "run_id": run_id, "check_name": "fixture", "severity": "ERROR", "status": "PASS",
        "observed_value": "0", "expected_value": "0", "numerator": 1, "denominator": 1,
        "message": "", "checked_at": created,
    }], columns=QUALITY_COLUMNS)
    manifest = {"run_id": run_id, "run_status": status}
    audit = pd.DataFrame([{
        "run_id": run_id, "run_status": status, "publication_status": "formal" if status == "PASS" else "blocked",
        "started_at": created, "completed_at": created, "input_database": "input.duckdb",
        "output_database": "output.duckdb", "as_of_date": pd.Timestamp("2026-07-27"),
        "symbol_count": 1, "raw_row_count": 1, "fact_row_count": 1,
        "indicator_row_count": 1, "summary_row_count": 1, "valuation_row_count": 1,
        "quality_passed": 1, "quality_failed": 0,
        "blocking_reasons_json": "[]", "config_hash": "a" * 64,
        "calculation_version": "v1", "model_version": "v1", "output_type": "fixture",
        "manifest_json": json.dumps(manifest), "created_at": created,
    }], columns=AUDIT_COLUMNS)
    return raw, facts, indicators, summaries, valuations, quality, audit


def _write(path, frames, run_id):
    raw, facts, indicators, summaries, valuations, quality, audit = frames
    write_stage10_run(
        path, ROOT / "sql/stage10_schema.sql", run_id=run_id, raw=raw, facts=facts,
        indicators=indicators, summaries=summaries, valuations=valuations,
        quality=quality, audit=audit,
    )


def test_same_run_idempotent_and_cross_run_history_preserved(tmp_path):
    database = tmp_path / "stage10.duckdb"
    first = _frames("run-one", pd.Timestamp("2026-07-26", tz="UTC"))
    _write(database, first, "run-one")
    _write(database, first, "run-one")
    assert stage10_counts(database) == {
        "raw": 1, "facts": 1, "indicators": 1, "summaries": 1,
        "valuations": 1, "quality": 1, "audit": 1,
    }
    second = _frames("run-two", pd.Timestamp("2026-07-27", tz="UTC"))
    _write(database, second, "run-two")
    counts = stage10_counts(database)
    assert all(count == 2 for count in counts.values())
    with duckdb.connect(str(database), read_only=True) as connection:
        latest = connection.execute(
            "SELECT DISTINCT run_id FROM analysis.v_latest_fundamental_summary"
        ).fetchall()
    assert latest == [("run-two",)]


def test_failed_run_does_not_replace_latest_success(tmp_path):
    database = tmp_path / "stage10.duckdb"
    _write(database, _frames("pass-run", pd.Timestamp("2026-07-26", tz="UTC")), "pass-run")
    _write(database, _frames("failed-run", pd.Timestamp("2026-07-27", tz="UTC"), "FAIL"), "failed-run")
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT DISTINCT run_id FROM analysis.v_latest_fundamental_summary"
        ).fetchone()[0] == "pass-run"


def test_primary_key_rejects_duplicate(tmp_path):
    database = tmp_path / "stage10.duckdb"
    _write(database, _frames(), "run-one")
    with duckdb.connect(str(database)) as connection:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO clean.financial_fact SELECT * FROM clean.financial_fact LIMIT 1"
            )


def test_transaction_failure_rolls_back_same_run_replacement(tmp_path):
    database = tmp_path / "stage10.duckdb"
    original = _frames()
    _write(database, original, "run-one")
    broken = list(_frames())
    broken[3] = pd.concat([broken[3], broken[3]], ignore_index=True)
    with pytest.raises(duckdb.ConstraintException):
        _write(database, tuple(broken), "run-one")
    counts = stage10_counts(database)
    assert counts["summaries"] == counts["audit"] == 1


def test_output_database_contains_all_required_schemas_and_views(tmp_path):
    database = tmp_path / "stage10.duckdb"
    _write(database, _frames(), "run-one")
    with duckdb.connect(str(database), read_only=True) as connection:
        schemas = {row[0] for row in connection.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()}
        views = {row[0] for row in connection.execute(
            "SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_latest_%'"
        ).fetchall()}
    assert {"raw", "clean", "feature", "analysis", "quality", "audit"}.issubset(schemas)
    assert "v_latest_fundamental_summary" in views
    assert "v_latest_valuation_snapshot" in views
