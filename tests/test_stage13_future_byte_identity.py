import hashlib
import shutil
from pathlib import Path

import duckdb
import pandas as pd

from akshare_data_test.stage13_presentation import build_stage13_presentation


ROOT = Path(__file__).resolve().parents[1]


def _prepare_root(path: Path) -> None:
    (path / "config").mkdir(parents=True)
    (path / "database").mkdir()
    shutil.copy2(ROOT / "config/stage13.yml", path / "config/stage13.yml")
    for name in ("akshare_data_test_stage5_repaired.duckdb", "akshare_features_stage6.duckdb", "akshare_features_stage7.duckdb"):
        shutil.copy2(ROOT / "database" / name, path / "database" / name)


def _inject_future_rows(path: Path) -> None:
    stage5 = duckdb.connect(str(path / "database/akshare_data_test_stage5_repaired.duckdb"))
    stage5.execute("INSERT INTO fact_stock_daily BY NAME SELECT * REPLACE ('future-stage13' AS source_run_id, DATE '2026-08-03' AS trade_date) FROM fact_stock_daily WHERE symbol='000100' AND adjust_type='qfq' LIMIT 1")
    stage5.execute("INSERT INTO fact_stock_fund_flow BY NAME SELECT * REPLACE ('future-stage13' AS source_run_id, DATE '2026-08-03' AS trade_date) FROM fact_stock_fund_flow WHERE symbol='000100' LIMIT 1")
    stage5.execute("INSERT INTO fact_stock_spot BY NAME SELECT * REPLACE ('future-stage13' AS source_run_id, TIMESTAMPTZ '2026-08-03 12:00:00+08:00' AS snapshot_at) FROM fact_stock_spot WHERE symbol='000100' LIMIT 1")
    stage5.execute("INSERT INTO fact_financial_statement BY NAME SELECT * REPLACE ('future-stage13' AS source_run_id, DATE '2026-09-30' AS report_period, DATE '2026-10-31' AS announcement_date) FROM fact_financial_statement WHERE symbol='000100' LIMIT 1")
    stage5.close()
    stage6 = duckdb.connect(str(path / "database/akshare_features_stage6.duckdb"))
    for table in ("feat_price_daily", "feat_trend_daily", "feat_style_daily"):
        stage6.execute(f"INSERT INTO {table} BY NAME SELECT * REPLACE (TIMESTAMP '2026-08-03' AS trade_date) FROM {table} WHERE symbol='000100' LIMIT 1")
    stage6.execute("INSERT INTO feat_limit_event BY NAME SELECT * REPLACE (TIMESTAMP '2026-08-03' AS trade_date, 'confirmed' AS limit_status, 'up' AS limit_direction) FROM feat_limit_event WHERE symbol='000100' LIMIT 1")
    stage6.close()
    stage7 = duckdb.connect(str(path / "database/akshare_features_stage7.duckdb"))
    stage7.execute("INSERT INTO analysis.analysis_stock_activity BY NAME SELECT * REPLACE (DATE '2026-08-03' AS as_of_date, 'future-stage13' AS run_id) FROM analysis.analysis_stock_activity WHERE symbol='000100' LIMIT 1")
    stage7.close()


def _build(path: Path):
    return build_stage13_presentation(
        root=path, as_of_date=pd.Timestamp("2026-07-27"), config_path=path / "config/stage13.yml",
        input_database=path / "database/akshare_data_test_stage5_repaired.duckdb",
        reports_dir=path / "reports/stage13", run_id="future-identity", symbols=["000100"],
    )[0]


def _hashes(path: Path) -> dict[str, str]:
    return {file.relative_to(path).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(path.rglob("*")) if file.is_file()}


def test_future_rows_leave_every_published_byte_identical(tmp_path):
    baseline = tmp_path / "baseline"
    future = tmp_path / "future"
    _prepare_root(baseline)
    _prepare_root(future)
    _inject_future_rows(future)
    left = _build(baseline)
    right = _build(future)
    assert left["visible_input_sha256"] == right["visible_input_sha256"]
    assert left["canonical_sha256"] == right["canonical_sha256"]
    assert left["run_identity_sha256"] == right["run_identity_sha256"]
    assert _hashes(baseline / "reports/stage13") == _hashes(future / "reports/stage13")
