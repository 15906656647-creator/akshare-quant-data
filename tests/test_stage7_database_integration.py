from __future__ import annotations

from pathlib import Path

import duckdb
import hashlib
import pandas as pd
import pytest

from akshare_data_test.stage7_build import _select_target_universe
from akshare_data_test.storage.feature_repository import (
    read_qfq_daily,
    upsert_stage7_results,
)


ROOT = Path(__file__).resolve().parents[1]


def _frames(run_id: str):
    calculated_at = pd.Timestamp("2026-07-30", tz="UTC")
    feature = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "exchange": "SZ",
                "trade_date": pd.Timestamp("2026-07-27"),
                "adjust_type": "qfq",
                "close": 10.0,
                "prev_close": 9.0,
                "return_1d": 1 / 9,
                **{f"ma_{n}": 10.0 for n in [3, 5, 7, 10, 13, 20, 21]},
                "volume_ma_5": 100.0,
                "volume_ma_20": 100.0,
                "volume_ratio_20": 1.0,
                "intraday_range": 0.1,
                "gap_return": 0.0,
                "volatility_20": 0.2,
                "is_volume_spike": False,
                "is_large_move": True,
                "source_fetched_at": calculated_at,
                "calculated_at": calculated_at,
                "run_id": run_id,
            }
        ]
    )
    components = {
        "amount_percentile": 1.0,
        "turnover_percentile": 1.0,
        "volatility_percentile": 1.0,
        "volume_spike_percentile": 1.0,
        "large_move_percentile": 1.0,
        "event_frequency_percentile": 1.0,
        "liquidity_component": 1.0,
        "turnover_component": 1.0,
        "volatility_component": 1.0,
        "volume_spike_component": 1.0,
        "large_move_component": 1.0,
        "event_component": 1.0,
    }
    activity = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "as_of_date": pd.Timestamp("2026-07-27"),
                "lookback_days": 120,
                "observation_count": 120,
                "avg_amount_120d": 1000.0,
                "avg_turnover_120d": 0.02,
                "avg_amplitude_120d": 0.03,
                "avg_volatility_20_120d": 0.2,
                "volume_spike_frequency": 0.1,
                "large_move_frequency": 0.1,
                "gap_frequency": 0.1,
                **components,
                "activity_score": 1.0,
                "score_status": "scored",
                "score_version": "activity_v1_pre_limit_event",
                "event_component_source": "gap_proxy",
                "calculated_at": calculated_at,
                "run_id": run_id,
            }
        ]
    )
    quality = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "check_name": "test",
                "status": "PASS",
                "severity": "ERROR",
                "observed_value": "0",
                "expected_value": "0",
                "details": "",
                "calculated_at": calculated_at,
            }
        ]
    )
    return feature, activity, quality


def test_transactional_upsert_is_idempotent_and_preserves_other_schema(tmp_path):
    database = tmp_path / "stage7.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA untouched")
        connection.execute("CREATE TABLE untouched.marker(value INTEGER)")
        connection.execute("INSERT INTO untouched.marker VALUES (7)")
    frames = _frames("run-one")
    upsert_stage7_results(
        database, ROOT / "sql" / "create_feature_tables.sql", *frames
    )
    upsert_stage7_results(
        database, ROOT / "sql" / "create_feature_tables.sql", *frames
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM feature.feature_stock_daily"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM analysis.analysis_stock_activity"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT value FROM untouched.marker"
        ).fetchone()[0] == 7


def test_transaction_rolls_back_first_table_when_second_write_fails(tmp_path):
    database = tmp_path / "rollback.duckdb"
    first = _frames("run-one")
    upsert_stage7_results(
        database, ROOT / "sql" / "create_feature_tables.sql", *first
    )
    changed_feature, malformed_activity, quality = _frames("run-two")
    changed_feature.loc[:, "close"] = 999.0
    malformed_activity = malformed_activity.drop(columns=["activity_score"])
    with pytest.raises(KeyError):
        upsert_stage7_results(
            database,
            ROOT / "sql" / "create_feature_tables.sql",
            changed_feature,
            malformed_activity,
            quality,
        )
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT close FROM feature.feature_stock_daily"
        ).fetchone()[0] == 10.0
        assert connection.execute(
            "SELECT run_id FROM feature.feature_stock_daily"
        ).fetchone()[0] == "run-one"


def _create_source_table(connection, qualified_name: str, symbol: str) -> None:
    connection.execute(
        f"""
        CREATE TABLE {qualified_name} (
            symbol VARCHAR, exchange VARCHAR, trade_date DATE,
            adjust_type VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume_share DOUBLE, amount_cny DOUBLE,
            amplitude DOUBLE, turnover_rate DOUBLE, ingested_at TIMESTAMPTZ
        )
        """
    )
    connection.execute(
        f"INSERT INTO {qualified_name} VALUES "
        "(?, 'SZ', DATE '2026-07-27', 'qfq', 1, 1, 1, 1, "
        "100, 100, 0, 0, TIMESTAMPTZ '2026-07-27 00:00:00+00')",
        [symbol],
    )


def test_source_is_read_only_and_clean_schema_has_explicit_priority(tmp_path):
    source = tmp_path / "source.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute("CREATE SCHEMA clean")
        _create_source_table(connection, "main.fact_stock_" + "daily", "000100")
        _create_source_table(connection, "clean.fact_stock_" + "daily", "002067")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    frame, table = read_qfq_daily(
        source, as_of_date=pd.Timestamp("2026-07-27")
    )
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert table == "clean.fact_stock_" + "daily"
    assert frame["symbol"].tolist() == ["002067"]
    assert before == after


def test_target_universe_filter_excludes_extra_and_rejects_empty():
    daily = pd.DataFrame({"symbol": ["000100", "999999"], "value": [1, 2]})
    selected, extras = _select_target_universe(daily, ["000100"])
    assert selected["symbol"].tolist() == ["000100"]
    assert extras == ["999999"]
    with pytest.raises(ValueError, match="no configured target stocks"):
        _select_target_universe(daily.loc[daily["symbol"].eq("999999")], ["000100"])
