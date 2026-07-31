from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from akshare_data_test.features.stock_daily_features import (
    Stage7Parameters,
    compute_stock_daily_features,
)


@pytest.fixture
def parameters() -> Stage7Parameters:
    return Stage7Parameters(
        ma_windows=(3, 5, 7, 10, 13, 20, 21),
        volume_ma_windows=(5, 20),
        volatility_window=20,
        annualization_days=252,
        activity_lookback_days=120,
        volume_spike_ratio=2.0,
        large_move_abs_return=0.05,
        gap_abs_threshold=0.03,
        minimum_scoring_observations=60,
        activity_weights={
            "turnover_amount_quantile": 0.25,
            "turnover_rate_quantile": 0.20,
            "volatility_quantile": 0.20,
            "volume_spike_frequency_quantile": 0.15,
            "large_move_frequency_quantile": 0.10,
            "limit_and_gap_event_frequency_quantile": 0.10,
        },
        score_version="activity_v1_pre_limit_event",
        event_component_source="gap_proxy",
    )


def _daily(symbol: str, rows: int, start: float = 1.0) -> pd.DataFrame:
    close = np.arange(start, start + rows, dtype=float)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "exchange": "SZ",
            "trade_date": pd.bdate_range("2026-01-01", periods=rows),
            "adjust_type": "qfq",
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume_share": np.arange(1, rows + 1, dtype=float) * 100,
            "amount_cny": close * 1000,
            "amplitude": 0.01,
            "turnover_rate": 0.02,
            "source_fetched_at": pd.Timestamp("2026-07-29", tz="UTC"),
        }
    )


def test_two_stock_boundary_has_no_shift_or_rolling_leakage(parameters):
    frame = pd.concat([_daily("000001", 25), _daily("000002", 25, 101)])
    result = compute_stock_daily_features(frame, parameters)
    second = result.loc[result["symbol"].eq("000002")].reset_index(drop=True)
    assert pd.isna(second.loc[0, "prev_close"])
    assert pd.isna(second.loc[0, "return_1d"])
    assert pd.isna(second.loc[0, "intraday_range"])
    assert pd.isna(second.loc[0, "gap_return"])
    assert second.loc[:1, "ma_3"].isna().all()
    assert second.loc[2, "ma_3"] == pytest.approx(102.0)


def test_moving_average_values_and_full_warmup(parameters):
    result = compute_stock_daily_features(_daily("000001", 25), parameters)
    assert result.loc[2, "ma_3"] == pytest.approx(2.0)
    assert result.loc[4, "ma_5"] == pytest.approx(3.0)
    assert result.loc[19, "ma_20"] == pytest.approx(10.5)
    assert result.loc[20, "ma_21"] == pytest.approx(11.0)
    assert result.loc[:18, "ma_20"].isna().all()
    assert result.loc[:19, "ma_21"].isna().all()


def test_volume_ratio_zero_and_incomplete_window_are_null(parameters):
    frame = _daily("000001", 25)
    frame.loc[:19, "volume_share"] = 0.0
    result = compute_stock_daily_features(frame, parameters)
    assert result.loc[:18, "volume_ratio_20"].isna().all()
    assert pd.isna(result.loc[19, "volume_ratio_20"])
    assert not np.isinf(result["volume_ratio_20"].dropna()).any()


def test_returns_ranges_gap_and_volatility_are_exact(parameters):
    result = compute_stock_daily_features(_daily("000001", 25), parameters)
    assert result.loc[1, "return_1d"] == pytest.approx(1.0)
    assert result.loc[1, "intraday_range"] == pytest.approx(1.0)
    assert result.loc[1, "gap_return"] == pytest.approx(1.0)
    close = np.arange(1.0, 26.0)
    independent_returns = close[1:21] / close[:20] - 1.0
    expected = np.std(independent_returns, ddof=1) * np.sqrt(252)
    assert result.loc[20, "volatility_20"] == pytest.approx(expected)


def test_duplicate_business_key_fails_explicitly(parameters):
    frame = _daily("000001", 3)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate Stage 7 input"):
        compute_stock_daily_features(frame, parameters)


def test_prev_close_zero_produces_null_ratios_not_infinity(parameters):
    frame = _daily("000001", 3)
    frame.loc[0, "close"] = 0.0
    result = compute_stock_daily_features(frame, parameters)
    assert pd.isna(result.loc[1, "return_1d"])
    assert pd.isna(result.loc[1, "intraday_range"])
    assert pd.isna(result.loc[1, "gap_return"])
    numeric = result.select_dtypes(include=[np.number]).to_numpy()
    assert not np.isinf(numeric).any()


def test_unordered_input_is_sorted_before_shift_and_rolling(parameters):
    frame = _daily("000001", 5).sample(frac=1.0, random_state=7)
    result = compute_stock_daily_features(frame, parameters)
    assert result["trade_date"].is_monotonic_increasing
    assert result.loc[2, "ma_3"] == pytest.approx(2.0)
    assert result.loc[1, "prev_close"] == pytest.approx(1.0)


def test_missing_or_invalid_core_input_fails(parameters):
    with pytest.raises(ValueError, match="Missing core daily columns"):
        compute_stock_daily_features(
            _daily("000001", 3).drop(columns=["close"]), parameters
        )
    missing_value = _daily("000001", 3)
    missing_value.loc[1, "high"] = np.nan
    with pytest.raises(ValueError, match="invalid core numeric"):
        compute_stock_daily_features(missing_value, parameters)
    invalid_symbol = _daily("ABC", 3)
    with pytest.raises(ValueError, match="six-digit symbol"):
        compute_stock_daily_features(invalid_symbol, parameters)


def test_infinite_noncore_value_is_cleaned_and_counted(parameters):
    frame = _daily("000001", 3)
    frame.loc[1, "open"] = np.inf
    result = compute_stock_daily_features(frame, parameters)
    assert pd.isna(result.loc[1, "gap_return"])
    assert result.attrs["infinite_values_cleaned"] >= 1
