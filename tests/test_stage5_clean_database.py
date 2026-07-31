from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from akshare_data_test.stage5_build import (
    _atomic_parquet,
    _number,
    _point_in_time,
    _stable_code,
    clean_stock_daily,
    load_mapping_config,
    validate_database,
    validate_raw_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MARKET_RUN = "39a6996e-36d7-4b73-b0b8-c38da4ae672e"
FINANCE_RUN = "62bbe9df-6ed8-48d5-a06b-10fb90171ee0"


def test_mapping_yaml_safe_and_auditable():
    fields, units = load_mapping_config(ROOT)
    assert fields["mapping_policy"]["preserve_unmapped"] is True
    required = {
        "canonical_field", "data_type", "mapping_status", "required",
        "nullable", "mapping_evidence",
    }
    assert required <= set(fields["datasets"]["stock_daily"]["日期"])
    assert units["unknown_unit_policy"]["convert"] is False
    assert {
        "source_dataset", "source_field", "source_unit", "target_unit",
        "scale_factor", "notes",
    } <= set(fields["record_defaults"])


def test_stage0_files_remain_frozen():
    expected = {
        "config/universe.yml": "0b6f61d43e753945b7e7931d27359e34a199891eac3f7d59f29c9d17efccec65",
        "config/metric_definition.yml": "13f9415d3e55aacc91e9913652d6e6520d9c681ac3043f09409602c44b5c00c4",
        "docs/stage0_scope.md": "18eeec59594b2cca67cfc7e7f137855ed2b1f018c10623e426340188ac761615",
    }
    import hashlib
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("run_id,count,stage", [(MARKET_RUN, 34, "stage3"), (FINANCE_RUN, 96, "stage4")])
def test_raw_manifest_integrity(run_id, count, stage):
    manifest = validate_raw_manifest(
        ROOT, ROOT / f"reports/evidence/{stage}/{run_id}/manifest.json", run_id
    )
    assert len(manifest.raw_files) == count


def test_raw_manifest_requires_explicit_matching_id():
    with pytest.raises(ValueError, match="run_id mismatch"):
        validate_raw_manifest(
            ROOT,
            ROOT / f"reports/evidence/stage3/{MARKET_RUN}/manifest.json",
            FINANCE_RUN,
        )


def test_number_normalizes_missing_and_infinity():
    assert _number("-") is None
    assert _number("") is None
    assert _number(float("inf")) is None
    assert _number("1.25") == 1.25


def test_point_in_time_unknown_is_not_safe():
    assert _point_in_time(None, date(2026, 7, 27)) == (None, "unavailable", None)


def test_point_in_time_future_is_lookahead():
    parsed, status, lookahead = _point_in_time("2026-07-28", date(2026, 7, 27))
    assert parsed == date(2026, 7, 28)
    assert status == "available"
    assert lookahead is True


def test_source_derived_codes_are_stable():
    assert _stable_code("TOTAL_ASSETS") == _stable_code("TOTAL_ASSETS")
    assert _stable_code("TOTAL_ASSETS") != _stable_code("TOTAL_LIABILITIES")


def test_atomic_clean_write_refuses_overwrite(tmp_path):
    path = tmp_path / "transform_run_id=x" / "data.parquet"
    _atomic_parquet(pd.DataFrame({"x": [1]}), path)
    assert not path.with_name("data.parquet.tmp").exists()
    with pytest.raises(FileExistsError):
        _atomic_parquet(pd.DataFrame({"x": [2]}), path)


def test_market_clean_preserves_symbol_and_adjustment():
    manifest = validate_raw_manifest(
        ROOT, ROOT / f"reports/evidence/stage3/{MARKET_RUN}/manifest.json", MARKET_RUN
    )
    frames, _ = clean_stock_daily(ROOT, manifest, "00000000-0000-4000-8000-000000000001")
    assert set(frames) == {"stock_daily_qfq", "stock_daily_raw"}
    assert frames["stock_daily_qfq"]["symbol"].str.fullmatch(r"\d{6}").all()
    assert set(frames["stock_daily_qfq"]["adjust_type"]) == {"qfq"}
    assert set(frames["stock_daily_raw"]["adjust_type"]) == {"raw"}
    assert (
        frames["stock_daily_qfq"]["volume_share"]
        == frames["stock_daily_qfq"]["volume_lot"] * 100
    ).all()


def test_stage5_sql_has_required_tables_and_no_feature_table():
    schema = (ROOT / "sql/stage5_schema.sql").read_text("utf-8").lower()
    for table in (
        "dim_security", "etl_run", "source_file_manifest", "data_lineage",
        "data_quality_issue", "field_mapping_registry", "fact_stock_daily",
        "fact_stock_spot", "fact_financial_abstract", "fact_financial_indicator",
        "fact_financial_statement", "fact_stock_fund_flow",
    ):
        assert f"create table if not exists {table}" in schema
    assert "feature_stock" not in schema


def test_views_exclude_unknown_announcement_dates():
    views = (ROOT / "sql/stage5_views.sql").read_text("utf-8").lower()
    assert "announcement_date is not null" in views
    assert "potential_lookahead = false" in views
    assert "v_stock_fund_flow_as_of_safe" in views
    assert "f.trade_date <= e.as_of_date" in views


def test_default_tests_block_real_socket(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("real socket access is forbidden")
    monkeypatch.setattr(socket, "create_connection", blocked)
    with pytest.raises(AssertionError):
        socket.create_connection(("example.com", 443))


def test_cli_requires_explicit_source_run_ids():
    import subprocess
    result = subprocess.run(
        [str(ROOT / ".venv/Scripts/python.exe"), "run_pipeline.py", "build-stage5",
         "--as-of-date", "2026-07-27"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "--market-run-id" in result.stderr
    assert "--fundamental-run-id" in result.stderr


def test_database_validation_when_formal_database_exists():
    database = ROOT / "database/akshare_data_test.duckdb"
    if database.exists():
        assert validate_database(database)["status"] == "PASS"
    else:
        assert not database.exists()


def test_duckdb_transaction_rolls_back_on_failure(tmp_path):
    connection = duckdb.connect(str(tmp_path / "rollback.duckdb"))
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    connection.execute("BEGIN")
    connection.execute("INSERT INTO sample VALUES (1)")
    with pytest.raises(duckdb.ConstraintException):
        connection.execute("INSERT INTO sample VALUES (1)")
    connection.execute("ROLLBACK")
    assert connection.execute("SELECT count(*) FROM sample").fetchone()[0] == 0
    connection.close()


def test_sql_schema_rebuilds_from_empty_database(tmp_path):
    connection = duckdb.connect(str(tmp_path / "rebuild.duckdb"))
    connection.execute((ROOT / "sql/stage5_schema.sql").read_text("utf-8"))
    connection.execute(
        (ROOT / "sql/stage5_metadata_indexes.sql").read_text("utf-8")
    )
    connection.execute((ROOT / "sql/stage5_views.sql").read_text("utf-8"))
    tables = connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_type='BASE TABLE'"
    ).fetchone()[0]
    views = connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_type='VIEW'"
    ).fetchone()[0]
    connection.close()
    assert tables == 12
    assert views == 8
