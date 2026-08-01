from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from akshare_data_test.style_features import (
    compute_style_features,
    load_stage9_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_stage9_config(ROOT / "config/stage9.yml")


def daily(
    count: int = 80,
    *,
    symbol: str = "000001",
    close: np.ndarray | None = None,
) -> pd.DataFrame:
    values = np.asarray(close if close is not None else 10 + 0.2 * np.sin(np.arange(count)), dtype=float)
    dates = pd.bdate_range("2026-01-01", periods=count)
    returns = pd.Series(values).pct_change().fillna(0).to_numpy()
    return pd.DataFrame({
        "symbol": symbol,
        "trade_date": dates,
        "adjust_type": "qfq",
        "open": values * (1 - 0.002),
        "high": values * 1.01,
        "low": values * 0.99,
        "close": values,
        "volume_share": np.linspace(200, 100, count),
        "amount_cny": np.linspace(2_000_000, 1_000_000, count),
        "turnover_rate": np.full(count, 0.01),
        "volume_ratio_20": pd.Series(np.linspace(200, 100, count)).div(
            pd.Series(np.linspace(200, 100, count)).rolling(20).mean()
        ),
        "return_1d": returns,
    })


def compute(frame: pd.DataFrame, *, windows=None, as_of=None):
    return compute_style_features(
        frame,
        CONFIG,
        as_of_date=as_of or frame["trade_date"].max(),
        windows=windows,
    )


def test_unsorted_multi_symbol_windows_are_stable_and_do_not_cross():
    left = daily()
    right = daily(symbol="000002", close=np.linspace(20, 30, 80))
    frame = pd.concat([left, right], ignore_index=True).sample(frac=1, random_state=9)
    result = compute(frame)
    assert len(result) == 6
    assert set(result["window_size"]) == {20, 40, 60}
    assert result["data_quality_status"].eq("pass").all()
    assert result.loc[result.symbol.eq("000001"), "normalized_slope"].abs().max() < 0.01
    assert result.loc[result.symbol.eq("000002"), "normalized_slope"].min() > 0


@pytest.mark.parametrize("window", [20, 40, 60])
def test_exact_window_is_sufficient_and_one_less_is_not(window):
    exact = compute(daily(window), windows=[window]).iloc[0]
    short = compute(daily(window - 1), windows=[window]).iloc[0]
    assert exact.data_quality_status == "pass"
    assert exact.observation_count == window
    assert short.data_quality_status == "insufficient_history"
    assert pd.isna(short.box_width)


def test_constant_price_has_finite_box_slope_and_r_squared():
    row = compute(daily(60, close=np.full(60, 10.0)), windows=[40]).iloc[0]
    assert row.box_width == pytest.approx(0.02020202)
    assert row.normalized_slope == pytest.approx(0)
    assert row.regression_r_squared == pytest.approx(1)
    assert row.close_position_in_box == pytest.approx(0.5)
    assert np.isfinite(row.atr_ratio)


def test_trend_volatility_and_drawdown_metrics_are_directional_and_finite():
    up = compute(daily(close=np.linspace(10, 20, 80)), windows=[40]).iloc[0]
    down = compute(daily(close=np.linspace(20, 10, 80)), windows=[40]).iloc[0]
    noisy = compute(daily(close=10 + np.random.default_rng(7).normal(0, 1, 80)), windows=[40]).iloc[0]
    assert up.trend_direction == "up" and up.regression_r_squared > 0.99
    assert down.trend_direction == "down" and down.regression_r_squared > 0.99
    assert down.rolling_max_drawdown < up.rolling_max_drawdown
    assert noisy.realized_volatility > up.realized_volatility
    assert np.isfinite(noisy.bollinger_band_width)


def test_volume_contraction_spikes_turnover_and_candles_are_measured():
    frame = daily()
    frame.loc[45, "volume_share"] = 1000
    frame.loc[45, "volume_ratio_20"] = 5
    frame.loc[60, "turnover_rate"] = 0.1
    frame.loc[60, ["open", "close", "low"]] = [10, 10.05, 9.95]
    frame.loc[60, "high"] = 12
    row = compute(frame, windows=[40]).iloc[0]
    assert row.volume_contraction_ratio < 1
    assert row.volume_spike_frequency > 0
    assert row.high_turnover_frequency > 0
    assert row.long_upper_shadow_frequency > 0


def test_suspended_and_zero_volume_rows_do_not_count_as_trading_observations():
    frame = daily(41)
    frame.loc[20, "volume_share"] = 0
    frame["is_suspended"] = False
    frame.loc[21, "is_suspended"] = True
    row = compute(frame, windows=[40]).iloc[0]
    assert row.observation_count == 39
    assert row.data_quality_status == "insufficient_history"


def test_future_rows_are_excluded_by_as_of_date():
    frame = daily(70)
    cutoff = frame.loc[59, "trade_date"]
    before = compute(frame.iloc[:60], windows=[40], as_of=cutoff)
    with_future = compute(frame, windows=[40], as_of=cutoff)
    pd.testing.assert_frame_equal(before, with_future)


def test_invalid_inputs_fail_explicitly():
    frame = daily()
    with pytest.raises(ValueError, match="adjust_type"):
        compute(frame.assign(adjust_type="raw"))
    with pytest.raises(ValueError, match="primary key"):
        compute(pd.concat([frame, frame.iloc[[0]]]))
    with pytest.raises(ValueError, match="missing columns"):
        compute(frame.drop(columns="amount_cny"))


def test_nonpositive_low_is_excluded_and_cannot_create_invalid_box():
    frame = daily(40)
    frame.loc[0, "low"] = 0
    row = compute(frame, windows=[40]).iloc[0]
    assert row.data_quality_status == "insufficient_history"
    assert pd.isna(row.rolling_low)


def test_stage8_blocked_preserves_unknown_formal_and_separates_auxiliary():
    row = compute_style_features(
        daily(), CONFIG, as_of_date=daily()["trade_date"].max(), windows=[40],
        stage8_auxiliary={"000001": {
            "publication_status": "blocked", "formal_event_frequency": 0,
            "candidate_event_frequency": 0.1, "proxy_event_frequency": 0.2,
            "gap_proxy_frequency": 0.3, "unresolved_event_frequency": 0.4,
        }},
    ).iloc[0]
    assert pd.isna(row.stage8_formal_event_frequency)
    assert row.stage8_candidate_event_frequency == 0.1
    assert row.stage8_proxy_event_frequency == 0.2
    assert row.stage8_gap_proxy_frequency == 0.3
    assert row.stage8_unresolved_event_frequency == 0.4
