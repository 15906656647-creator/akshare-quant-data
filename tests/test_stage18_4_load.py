from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.stage18_4_config import EXPECTED_CATEGORIES, load_stage18_4_config
from akshare_data_test.stage18_4_load import (
    _validation_frames, run_stage18_4_load,
)
from akshare_data_test.stage18_audit import Stage18Blocked


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUN = "66bebf1c-8b64-42a6-a970-1dbf1ecb395f"


def test_stage184_config_freezes_upstream_tables_counts_and_boundaries():
    config = load_stage18_4_config(ROOT / "config/stage18_4.yml")
    assert config.source_run_id == SOURCE_RUN
    assert config.source_stage18_2_run_id == "df86486a-9a54-4920-a4db-2553f907af92"
    assert config.expected_history_rows == 468986
    assert config.expected_total_rows == 469009
    assert tuple(config.tables) == EXPECTED_CATEGORIES
    assert sum(config.expected_rows.values()) == 469009


def test_wrong_upstream_blocks_before_database_write():
    before = sorted((ROOT / "database/stage18").rglob("*")) if (ROOT / "database/stage18").exists() else []
    with pytest.raises(Stage18Blocked, match="upstream run id"):
        run_stage18_4_load(
            root=ROOT, as_of_date=date(2026, 7, 27),
            upstream_run_id="00000000-0000-4000-8000-000000000000",
        )
    after = sorted((ROOT / "database/stage18").rglob("*")) if (ROOT / "database/stage18").exists() else []
    assert before == after


def test_validate_only_verifies_formal_upstream_without_database_write():
    report, code = run_stage18_4_load(
        root=ROOT, as_of_date=date(2026, 7, 27), validate_only=True,
    )
    assert code == 0 and report["status"] == "VALIDATED"
    assert report["database_writes"] == 0


def _history(category: str) -> pd.DataFrame:
    symbols = [f"{index:06d}" for index in range(16)] + [f"{index:05d}.HK" for index in range(7)]
    markets = ["A"] * 16 + ["HK"] * 7
    return pd.DataFrame({
        "symbol": symbols, "market": markets, "data_category": category,
        "provider": "mock", "source_interface": "mock_history", "source_variant": "default",
        "report_date": pd.to_datetime(["2025-12-31"] * 23),
        "announcement_date": pd.to_datetime([None] + ["2026-01-31"] * 22),
        "update_date": pd.to_datetime([None] + ["2026-02-01"] * 22),
        "fiscal_year": [2025] * 23, "fiscal_period": "FY", "period_type": "ANNUAL",
        "currency": ["CNY"] * 16 + ["HKD"] * 7, "currency_status": "reported",
        "source_field": "metric", "source_metric_name": "metric", "source_section": "section",
        "canonical_name": "metric", "mapping_status": "MAPPED", "value": range(23),
        "source_unit": "ratio", "canonical_unit": "ratio", "scale_factor": 1.0,
        "normalized_value": range(23),
        "pit_status": ["ANNOUNCEMENT_DATE_UNAVAILABLE"] + ["PIT_ELIGIBLE"] * 22,
        "eligible_for_as_of_date_analysis": [False] + [True] * 22,
        "dedup_status": "unique", "canonical_key": [f"{category}:{symbol}" for symbol in symbols],
        "source_run_id": "raw-run", "clean_run_id": SOURCE_RUN,
        "source_dataset_id": [f"dataset:{symbol}" for symbol in symbols], "source_sha256": "a" * 64,
        "source_variants": '["default"]', "source_sections": '["section"]',
        "source_dataset_ids": '["dataset"]', "source_sha256s": '["hash"]',
        "schema_version": "fundamental_clean_v1",
    })


def _valuation() -> pd.DataFrame:
    symbols = [f"{index:06d}" for index in range(16)] + [f"{index:05d}.HK" for index in range(7)]
    return pd.DataFrame({
        "symbol": symbols, "market": ["A"] * 16 + ["HK"] * 7,
        "data_category": "valuation_snapshot", "provider": "mock",
        "source_interface": "mock_spot", "source_variant": "default",
        "snapshot_time": pd.to_datetime(["2026-08-27T00:00:00Z"] * 23, utc=True),
        "analysis_as_of_date": pd.to_datetime(["2026-07-27"] * 23),
        "eligible_for_as_of_date_analysis": [False] * 23,
        "pit_status": "SNAPSHOT_AFTER_AS_OF_DATE", "currency": ["CNY"] * 16 + ["HKD"] * 7,
        "currency_status": "reported", "pe": 10.0, "pb": 1.0,
        "total_market_cap": 100.0, "floating_market_cap": 80.0,
        "pe_source_interface": "mock_pe", "pb_source_interface": "mock_pb",
        "market_cap_source_interface": "mock_cap", "source_component_count": 2,
        "source_interfaces": '["mock_pe","mock_cap"]', "source_variants": '["default"]',
        "source_dataset_ids": '["dataset"]', "source_sha256s": '["hash"]',
        "source_run_id": "raw-run", "clean_run_id": SOURCE_RUN,
        "schema_version": "fundamental_clean_v1",
    })


def _mini_database(tmp_path: Path):
    config = load_stage18_4_config(ROOT / "config/stage18_4.yml")
    expected = {category: 23 for category in EXPECTED_CATEGORIES}
    config = replace(config, expected_rows=expected, expected_history_rows=115, expected_total_rows=138)
    datasets = {}
    connection = duckdb.connect(str(tmp_path / "mini.duckdb"))
    for category in EXPECTED_CATEGORIES:
        path = tmp_path / f"{category}.parquet"
        frame = _valuation() if category == "valuation_snapshot" else _history(category)
        frame.to_parquet(path, index=False)
        datasets[category] = {"data_file": path}
        relation = str(path).replace("'", "''")
        connection.execute(f'CREATE TABLE "{config.tables[category]}" AS SELECT * FROM read_parquet(\'{relation}\', hive_partitioning=false)')
    return connection, config, datasets


def test_schema_rows_lineage_pit_valuation_and_filters_validate(tmp_path):
    connection, config, datasets = _mini_database(tmp_path)
    try:
        row_counts, schemas, lineage, pit, integrity, failures = _validation_frames(connection, config, datasets)
    finally:
        connection.close()
    assert failures == []
    assert row_counts["database_rows"].sum() == 138
    assert (schemas["status"] == "PASS").all()
    assert (lineage["status"] == "PASS").all()
    assert (pit["status"] == "PASS").all()
    assert (integrity["status"] == "PASS").all()
    assert "run_id" not in set(schemas["database_column"])


def test_pit_or_valuation_mutation_is_detected(tmp_path):
    connection, config, datasets = _mini_database(tmp_path)
    try:
        connection.execute("UPDATE fact_income_statement SET pit_status='CHANGED' WHERE symbol='000000'")
        connection.execute("UPDATE fact_valuation_snapshot SET eligible_for_as_of_date_analysis=true WHERE symbol='000000'")
        _rows, _schemas, lineage, pit, integrity, failures = _validation_frames(connection, config, datasets)
    finally:
        connection.close()
    assert failures
    assert (lineage["status"] == "FAIL").any()
    assert (pit["status"] == "FAIL").any()
    assert integrity.loc[integrity["check_name"] == "valuation_eligibility_false", "status"].iloc[0] == "FAIL"


def test_existing_run_paths_are_append_only(monkeypatch, tmp_path):
    config = load_stage18_4_config(ROOT / "config/stage18_4.yml")
    config = replace(config, database_root=tmp_path / "db", reports_root=tmp_path / "reports")
    monkeypatch.setattr("akshare_data_test.stage18_4_load.load_stage18_4_config", lambda _path: config)
    monkeypatch.setattr("akshare_data_test.stage18_4_load._verify_upstream", lambda *_args: ({"ok": True}, {}))
    monkeypatch.setattr("akshare_data_test.stage18_4_load._protected_state", lambda *_args: {})
    monkeypatch.setattr("akshare_data_test.stage18_4_load.frozen_hashes", lambda *_args: {})
    run_id = "99999999-9999-4999-8999-999999999999"
    (config.database_root / f"run_id={run_id}").mkdir(parents=True)
    with pytest.raises(Stage18Blocked, match="append-only"):
        run_stage18_4_load(root=ROOT, config_path=ROOT / "config/stage18_4.yml", as_of_date=date(2026, 7, 27), run_id=run_id)
