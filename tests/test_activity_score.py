from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from akshare_data_test.features.activity_score import compute_activity_scores
from akshare_data_test.features.stock_daily_features import Stage7Parameters
from akshare_data_test.stage7_build import _select_target_universe
from test_stock_daily_features import parameters as parameters_fixture


parameters = parameters_fixture


def _features() -> pd.DataFrame:
    rows = []
    for index, symbol in enumerate(["000001", "000002", "000003"], start=1):
        for day in range(80):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
                    "amount_cny": float(index * 100),
                    "turnover_rate": float(index),
                    "amplitude": 0.01 * index,
                    "volatility_20": 0.1 * index,
                    "is_volume_spike": day % (5 - index) == 0,
                    "is_large_move": day % (6 - index) == 0,
                    "gap_return": 0.04 if day % (7 - index) == 0 else 0.0,
                }
            )
    return pd.DataFrame(rows)


def test_activity_percentiles_weighted_score_and_metadata(parameters):
    result = compute_activity_scores(
        _features(),
        parameters,
        as_of_date=pd.Timestamp("2026-07-27"),
    )
    top = result.loc[result["symbol"].eq("000003")].iloc[0]
    assert top["amount_percentile"] == pytest.approx(1.0)
    assert top["turnover_percentile"] == pytest.approx(1.0)
    assert result["activity_score"].between(0, 1).all()
    assert result["score_status"].eq("scored").all()
    assert result["score_version"].eq("activity_v1_pre_limit_event").all()
    assert result["event_component_source"].eq("gap_proxy").all()
    recomputed = (
        0.25 * top["liquidity_component"]
        + 0.20 * top["turnover_component"]
        + 0.20 * top["volatility_component"]
        + 0.15 * top["volume_spike_component"]
        + 0.10 * top["large_move_component"]
        + 0.10 * top["event_component"]
    )
    assert top["activity_score"] == pytest.approx(recomputed)


def test_insufficient_observations_are_marked(parameters):
    short = _features().groupby("symbol", group_keys=False).head(20)
    result = compute_activity_scores(
        short,
        parameters,
        as_of_date=pd.Timestamp("2026-07-27"),
    )
    assert result["observation_count"].eq(20).all()
    assert result["score_status"].eq("insufficient_observations").all()


@pytest.mark.parametrize("invalid_window", [0, -1])
def test_nonpositive_lookback_is_rejected_not_silently_defaulted(
    parameters, invalid_window
):
    with pytest.raises(ValueError, match="lookback_days must be positive"):
        compute_activity_scores(
            _features(),
            parameters,
            as_of_date=pd.Timestamp("2026-07-27"),
            lookback_days=invalid_window,
        )


def test_cross_sectional_ties_use_average_percentile_rank(parameters):
    frame = _features()
    frame.loc[:, ["amount_cny", "turnover_rate", "volatility_20"]] = 1.0
    frame.loc[:, ["is_volume_spike", "is_large_move"]] = False
    frame.loc[:, "gap_return"] = 0.0
    result = compute_activity_scores(
        frame,
        parameters,
        as_of_date=pd.Timestamp("2026-07-27"),
    )
    # Three tied observations have average rank 2, hence percentile 2/3.
    assert np.allclose(result["amount_percentile"], 2 / 3)
    assert np.allclose(result["event_frequency_percentile"], 2 / 3)


def test_invalid_stage7_configuration_is_rejected():
    root = Path(__file__).resolve().parents[1]
    metric = yaml.safe_load(
        (root / "config" / "metric_definition.yml").read_text(encoding="utf-8")
    )
    stage7 = yaml.safe_load(
        (root / "config" / "stage7.yml").read_text(encoding="utf-8")
    )
    bad_windows = copy.deepcopy(metric)
    bad_windows["ma_windows"]["volume"] = [5, 5, 20]
    with pytest.raises(ValueError, match="volume MA windows"):
        Stage7Parameters.from_config(bad_windows, stage7)
    bad_price_windows = copy.deepcopy(metric)
    bad_price_windows["ma_windows"]["price"] = [3, 3, 5, 7, 10, 13, 20, 21]
    with pytest.raises(ValueError, match="requires MA windows"):
        Stage7Parameters.from_config(bad_price_windows, stage7)
    bad_volatility = copy.deepcopy(metric)
    bad_volatility["volume_price_metrics"]["volatility_window"] = 0
    with pytest.raises(ValueError, match="positive configuration"):
        Stage7Parameters.from_config(bad_volatility, stage7)
    bad_annualization = copy.deepcopy(metric)
    bad_annualization["volume_price_metrics"]["annual_trading_days"] = -252
    with pytest.raises(ValueError, match="positive configuration"):
        Stage7Parameters.from_config(bad_annualization, stage7)
    bad_threshold = copy.deepcopy(stage7)
    bad_threshold["gap_abs_threshold"] = "not-a-number"
    with pytest.raises(ValueError):
        Stage7Parameters.from_config(metric, bad_threshold)
    bad_weights = copy.deepcopy(metric)
    bad_weights["activity_scoring"]["weights"]["turnover_amount_quantile"] = 0.5
    with pytest.raises(ValueError, match="weights must sum"):
        Stage7Parameters.from_config(bad_weights, stage7)
    missing_weight = copy.deepcopy(metric)
    missing_weight["activity_scoring"]["weights"].pop(
        "turnover_amount_quantile"
    )
    with pytest.raises(ValueError, match="weight keys"):
        Stage7Parameters.from_config(missing_weight, stage7)
    extra_weight = copy.deepcopy(metric)
    extra_weight["activity_scoring"]["weights"]["unknown_component"] = 0.0
    with pytest.raises(ValueError, match="weight keys"):
        Stage7Parameters.from_config(extra_weight, stage7)
    bad_minimum = copy.deepcopy(stage7)
    bad_minimum["minimum_scoring_observations"] = 121
    with pytest.raises(ValueError, match="cannot exceed"):
        Stage7Parameters.from_config(metric, bad_minimum)


def test_extra_symbol_is_excluded_without_changing_target_scores(parameters):
    base = _features()
    target_symbols = sorted(base["symbol"].unique())
    expected = compute_activity_scores(
        base,
        parameters,
        as_of_date=pd.Timestamp("2026-07-27"),
    ).set_index("symbol")["activity_score"]

    extra = base.loc[base["symbol"].eq("000003")].copy()
    extra["symbol"] = "999999"
    extra["amount_cny"] = 1e20
    extra["turnover_rate"] = 1e6
    extra["volatility_20"] = 1e4
    mixed = pd.concat([base, extra], ignore_index=True)
    selected, excluded = _select_target_universe(mixed, target_symbols)
    actual = compute_activity_scores(
        selected,
        parameters,
        as_of_date=pd.Timestamp("2026-07-27"),
    ).set_index("symbol")["activity_score"]

    pd.testing.assert_series_equal(
        actual.sort_index(), expected.sort_index(), check_names=False
    )
    assert excluded == ["999999"]
