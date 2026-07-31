from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from akshare_data_test.features.stage6_features import (
    REQUIRED_MA_WINDOWS,
    Stage6Parameters,
    build_current_snapshot,
    build_financial_features,
    build_fund_flow_features,
    build_limit_features,
    build_price_and_trend,
    build_suspected_behavior_evidence,
    safe_divide,
)
from akshare_data_test.stage6_build import (
    TRANSFORM_RUN_ID,
    _atomic_parquet,
    _read_source,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "database/akshare_data_test_stage5_repaired.duckdb"


@pytest.fixture
def parameters() -> Stage6Parameters:
    config = yaml.safe_load(
        (ROOT / "config/metric_definition.yml").read_text(encoding="utf-8")
    )
    return Stage6Parameters.from_config(config)


def _daily(adjust: str, rows: int = 25) -> pd.DataFrame:
    dates = pd.bdate_range("2026-06-20", periods=rows)
    close = np.arange(1, rows + 1, dtype=float)
    return pd.DataFrame(
        {
            "transform_run_id": TRANSFORM_RUN_ID,
            "source_run_id": "source",
            "symbol": "000100",
            "exchange": "SZ",
            "trade_date": dates,
            "adjust_type": adjust,
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume_lot": close * 10,
            "volume_share": close * 1000,
            "amount_cny": close * 10000,
            "amplitude": 0.01,
            "pct_change": 0.01,
            "price_change": 0.1,
            "turnover_rate": 0.02,
            "source_file": "data/clean/test.parquet",
            "source_row_number": np.arange(rows),
        }
    )


def test_frozen_ma_windows_are_exact(parameters):
    assert parameters.ma_windows == REQUIRED_MA_WINDOWS
    assert REQUIRED_MA_WINDOWS == [3, 5, 7, 10, 13, 20, 21]


def test_activity_weights_come_from_config_and_sum_to_one(parameters):
    assert sum(parameters.activity_weights.values()) == pytest.approx(1.0)
    assert parameters.activity_weights["turnover_amount_quantile"] == 0.25


def test_safe_divide_zero_and_missing_are_null():
    result = safe_divide(pd.Series([1.0, 1.0, 1.0]), pd.Series([2.0, 0.0, np.nan]))
    assert result.iloc[0] == 0.5
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])


def test_price_and_ma_use_qfq_with_warmup_null(parameters):
    price, trend = build_price_and_trend(
        _daily("qfq"), pd.Timestamp("2026-07-27"), parameters
    )
    assert price["return_1d"].iloc[1] == pytest.approx(1.0)
    assert trend["ma_3"].iloc[:2].isna().all()
    assert trend["ma_3"].iloc[2] == pytest.approx(2.0)
    assert trend["ma_21"].iloc[:20].isna().all()


def test_price_features_reject_raw(parameters):
    with pytest.raises(ValueError, match="require_qfq"):
        build_price_and_trend(
            _daily("raw"), pd.Timestamp("2026-07-27"), parameters
        )


def test_limit_features_use_raw_and_do_not_guess_st():
    result = build_limit_features(
        _daily("raw"), pd.Timestamp("2026-07-27"), 0.5
    )
    assert result["limit_status"].iloc[0] == "warmup"
    assert result["limit_status"].iloc[1:].eq("uncertain").all()
    assert result["limit_threshold"].isna().all()


def test_limit_output_obeys_configured_natural_day_lookback():
    frame = _daily("raw", rows=400)
    result = build_limit_features(
        frame, frame["trade_date"].max(), 0.5, lookback_natural_days=365
    )
    assert result["trade_date"].min() >= (
        frame["trade_date"].max() - pd.Timedelta(days=365)
    )


def test_limit_features_reject_qfq():
    with pytest.raises(ValueError, match="raw_prices"):
        build_limit_features(
            _daily("qfq"), pd.Timestamp("2026-07-27"), 0.5
        )


def test_fund_flow_excludes_future_date():
    frame = pd.DataFrame(
        {
            "transform_run_id": TRANSFORM_RUN_ID,
            "source_run_id": "source",
            "symbol": ["000100", "000100"],
            "exchange": ["SZ", "SZ"],
            "trade_date": ["2026-07-27", "2026-07-28"],
            "main_net_inflow_cny": [1.0, 2.0],
            "main_net_inflow_ratio": [0.01, 0.02],
            "source_file": ["a", "a"],
        }
    )
    result = build_fund_flow_features(frame, pd.Timestamp("2026-07-27"))
    assert len(result) == 1
    assert result["trade_date"].max() == pd.Timestamp("2026-07-27")


def test_current_spot_is_never_historical_as_of():
    frame = pd.DataFrame(
        {
            "transform_run_id": [TRANSFORM_RUN_ID],
            "source_run_id": ["source"],
            "symbol": ["000100"],
            "exchange": ["SZ"],
            "snapshot_at": ["2026-07-29 10:00:00+08"],
            "snapshot_scope": ["target_16"],
            "pe_dynamic": [10.0],
            "pb": [1.2],
            "market_cap_cny": [100.0],
            "float_market_cap_cny": [80.0],
            "source_file": ["spot.parquet"],
        }
    )
    result = build_current_snapshot(frame, ["000100"])
    assert result["is_historical_as_of"].eq(False).all()
    assert result["snapshot_at"].min() > pd.Timestamp("2026-07-27", tz="UTC")


def test_financial_features_exclude_unknown_and_future_announcements():
    base = {
        "transform_run_id": TRANSFORM_RUN_ID,
        "source_run_id": "source",
        "symbol": "000100",
        "financial_kind": "profit_statement",
        "item_code": "x",
        "item_name": "NETPROFIT",
    }
    frame = pd.DataFrame(
        [
            {
                **base,
                "report_period": "2026-03-31",
                "announcement_date": "2026-04-30",
                "item_value": 10.0,
            },
            {
                **base,
                "report_period": "2026-06-30",
                "announcement_date": None,
                "item_value": 20.0,
            },
            {
                **base,
                "report_period": "2026-06-30",
                "announcement_date": "2026-07-28",
                "item_value": 20.0,
            },
        ]
    )
    result = build_financial_features(frame, pd.Timestamp("2026-07-27"))
    assert result["report_period"].max() == pd.Timestamp("2026-03-31")
    assert result["announcement_date"].notna().all()
    assert result["announcement_date"].le(pd.Timestamp("2026-07-27")).all()


def test_ttm_is_null_when_quarters_are_missing():
    rows = []
    for period, value in [("2025-03-31", 10.0), ("2025-09-30", 30.0)]:
        rows.append(
            {
                "transform_run_id": TRANSFORM_RUN_ID,
                "source_run_id": "source",
                "symbol": "000100",
                "report_period": period,
                "announcement_date": "2025-10-30",
                "financial_kind": "profit_statement",
                "item_code": "x",
                "item_value": value,
                "item_name": "TOTAL_OPERATE_INCOME",
            }
        )
    result = build_financial_features(
        pd.DataFrame(rows), pd.Timestamp("2026-07-27")
    )
    ttm = result.loc[result["feature_name"].eq("revenue_ttm")]
    assert ttm["feature_value"].isna().all()


def test_financial_output_obeys_five_annual_and_twelve_quarter_scope():
    rows = []
    for period in pd.date_range("2018-03-31", "2026-03-31", freq="QE"):
        rows.append(
            {
                "transform_run_id": TRANSFORM_RUN_ID,
                "source_run_id": "source",
                "symbol": "000100",
                "report_period": period,
                "announcement_date": min(
                    period + pd.Timedelta(days=30), pd.Timestamp("2026-07-27")
                ),
                "financial_kind": "profit_statement",
                "item_code": "x",
                "item_value": float(len(rows) + 1),
                "item_name": "TOTAL_OPERATE_INCOME",
            }
        )
    result = build_financial_features(
        pd.DataFrame(rows), pd.Timestamp("2026-07-27"), 5, 12
    )
    periods = result["report_period"].drop_duplicates()
    annual = periods[periods.dt.month.eq(12) & periods.dt.day.eq(31)]
    assert len(periods) <= 17
    assert len(annual) <= 5


def test_suspected_behavior_is_neutral_and_insufficient():
    price = pd.DataFrame(
        {
            "symbol": ["000100"],
            "exchange": ["SZ"],
            "trade_date": [pd.Timestamp("2026-07-27")],
        }
    )
    activity = pd.DataFrame(
        {
            "symbol": ["000100"],
            "trade_date": [pd.Timestamp("2026-07-27")],
            "volume_spike_frequency_120": [0.1],
            "turnover_rate_120": [0.02],
            "activity_score": [0.5],
        }
    )
    fund = pd.DataFrame(
        {
            "symbol": ["000100"],
            "trade_date": [pd.Timestamp("2026-07-27")],
            "main_net_inflow_ratio": [0.01],
        }
    )
    result = build_suspected_behavior_evidence(
        price, activity, fund, pd.Timestamp("2026-07-27")
    )
    assert result["insufficient_evidence"].all()
    assert result["confidence_score"].isna().all()
    assert result["evidence_summary"].str.contains("疑似主力行为特征").all()


def test_atomic_feature_write_is_idempotent_and_conflict_safe(tmp_path):
    path = tmp_path / "feature_run_id=x" / "data.parquet"
    first_hash, existed = _atomic_parquet(path, pd.DataFrame({"x": [1]}))
    second_hash, existed_again = _atomic_parquet(path, pd.DataFrame({"x": [1]}))
    assert first_hash == second_hash
    assert existed is False
    assert existed_again is True
    with pytest.raises(RuntimeError, match="feature_payload_conflict"):
        _atomic_parquet(path, pd.DataFrame({"x": [2]}))


def test_stage5_database_is_read_only_and_unchanged():
    before = hashlib.sha256(SOURCE_DB.read_bytes()).hexdigest()
    frames, audit = _read_source(
        SOURCE_DB, date(2026, 7, 27), TRANSFORM_RUN_ID
    )
    after = hashlib.sha256(SOURCE_DB.read_bytes()).hexdigest()
    assert before == after
    assert frames["qfq"]["trade_date"].max() <= pd.Timestamp("2026-07-27")
    assert frames["fund"]["trade_date"].max() <= pd.Timestamp("2026-07-27")
    assert audit["future_fund_rows"] == 16


def test_stage6_source_has_no_future_shift_or_centered_rolling():
    source = (
        ROOT
        / "src"
        / "akshare_data_test"
        / "features"
        / "stage6_features.py"
    ).read_text(encoding="utf-8")
    assert "shift(-1)" not in source
    assert "center=True" not in source


def test_stage6_has_no_stage7_or_investment_output():
    source = (ROOT / "src" / "akshare_data_test" / "stage6_build.py").read_text(
        encoding="utf-8"
    )
    prohibited = ["buy_signal", "sell_signal", "stock_ranking"]
    assert not any(term in source for term in prohibited)
