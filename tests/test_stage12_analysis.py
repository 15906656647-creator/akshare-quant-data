from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from akshare_data_test.analysis.active_stocks import analyze_active_stocks
from akshare_data_test.analysis.range_bound import analyze_range_bound
from akshare_data_test.analysis.stage12_common import normalize_price_frame
from akshare_data_test.analysis.volume_breakout import analyze_volume_breakouts
from akshare_data_test.stage12_analysis import analyze_stage12
from akshare_data_test.stage12_config import load_stage12_config
from akshare_data_test.style_features import compute_log_trend, compute_range_width


ROOT = Path(__file__).resolve().parents[1]
AS_OF = pd.Timestamp("2026-07-27")


def price_fixture(*, future: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range(end=AS_OF, periods=125)
    rows = []
    for instrument, trending in (("000001", False), ("000002", True)):
        for index, trade_date in enumerate(dates):
            close = 10 + (index * 0.02 if trending else np.sin(index / 4) * 0.12)
            volume = 100 + index % 5
            if index == len(dates) - 1 and instrument == "000001":
                volume = 450
            rows.append({
                "instrument": instrument, "trade_date": trade_date,
                "adjust_type": "qfq", "open": close, "high": close * 1.01,
                "low": close * 0.99, "close": close, "volume": volume,
                "amount": volume * close * 100, "turnover_rate": 0.01 + index / 100000,
            })
    if future:
        rows.append({
            "instrument": "000001", "trade_date": "2026-07-28", "adjust_type": "qfq",
            "open": 1000, "high": 1010, "low": 990, "close": 1000,
            "volume": 999999, "amount": 999999999, "turnover_rate": 0.9,
        })
    return pd.DataFrame(rows)


def fundamental_fixture(*, future: bool = False) -> pd.DataFrame:
    rows = [
        {"instrument": "000001", "available_date": "2026-04-30", "valuation_score": 0.7,
         "profitability_score": 80, "growth_score": 0.7, "quality_score": 75},
        {"instrument": "000002", "available_date": "2026-04-30", "valuation_score": 0.5,
         "profitability_score": 60, "growth_score": 0.4, "quality_score": 55},
    ]
    if future:
        rows.append({"instrument": "000001", "available_date": "2026-08-30",
                     "valuation_score": 1, "profitability_score": 100,
                     "growth_score": 1, "quality_score": 100})
    return pd.DataFrame(rows)


@pytest.fixture
def config():
    return load_stage12_config(ROOT / "config/stage12.yml").raw


def test_price_validation_rejects_duplicate_negative_and_nonfinite():
    base = price_fixture()
    duplicate = pd.concat([base, base.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        normalize_price_frame(duplicate, as_of_date=AS_OF)
    negative = base.copy()
    negative.loc[0, "volume"] = -1
    with pytest.raises(ValueError, match="cannot be negative"):
        normalize_price_frame(negative, as_of_date=AS_OF)
    nonfinite = base.copy()
    nonfinite.loc[0, "close"] = np.inf
    with pytest.raises(ValueError, match="finite"):
        normalize_price_frame(nonfinite, as_of_date=AS_OF)


def test_active_ranking_is_stable_and_missing_turnover_is_not_zero(config):
    visible, _ = normalize_price_frame(price_fixture(), as_of_date=AS_OF)
    active_cfg = {**config["active_stock"], "ranking_method": config["ranking_method"]}
    first = analyze_active_stocks(visible, as_of_date=AS_OF, config=active_cfg)
    second = analyze_active_stocks(visible.sample(frac=1, random_state=3), as_of_date=AS_OF, config=active_cfg)
    pd.testing.assert_frame_equal(first, second)
    missing = visible.copy()
    missing.loc[missing.instrument.eq("000001"), "turnover_rate"] = np.nan
    result = analyze_active_stocks(missing, as_of_date=AS_OF, config=active_cfg).set_index("instrument")
    assert pd.isna(result.at["000001", "average_turnover"])
    assert pd.isna(result.at["000001", "activity_score"])
    assert "turnover_missing" in result.at["000001", "reason_codes"]


def test_volume_breakout_excludes_observation_and_handles_minimum_history(config):
    visible, _ = normalize_price_frame(price_fixture(), as_of_date=AS_OF)
    result = analyze_volume_breakouts(visible, as_of_date=AS_OF, config=config["volume_breakout"]).set_index("instrument")
    expected = visible.loc[visible.instrument.eq("000001")].iloc[-21:-1].volume.mean()
    assert result.at["000001", "historical_mean_volume"] == pytest.approx(expected)
    assert bool(result.at["000001", "is_volume_breakout"])
    short = visible.groupby("instrument", group_keys=False).tail(10)
    short_result = analyze_volume_breakouts(short, as_of_date=AS_OF, config=config["volume_breakout"])
    assert not short_result.is_volume_breakout.any()
    assert all("insufficient_history" in value for value in short_result.reason_codes)


def test_range_bound_constant_and_trending_series(config):
    visible, _ = normalize_price_frame(price_fixture(), as_of_date=AS_OF)
    result = analyze_range_bound(visible, as_of_date=AS_OF, config=config["range_bound"]).set_index("instrument")
    assert bool(result.at["000001", "is_range_bound"])
    assert not bool(result.at["000002", "is_range_bound"])
    constant = visible.loc[visible.instrument.eq("000001")].copy()
    constant[["open", "high", "low", "close"]] = 10.0
    constant_result = analyze_range_bound(constant, as_of_date=AS_OF, config=config["range_bound"]).iloc[0]
    stage9_slope, stage9_slope_pct, stage9_r2 = compute_log_trend(constant["close"])
    assert constant_result.trend_slope == pytest.approx(stage9_slope, abs=1e-15)
    assert constant_result.trend_slope_pct == pytest.approx(stage9_slope_pct, abs=1e-15)
    assert constant_result.trend_r2 == stage9_r2 == 1.0
    assert constant_result.close_position == 0.5


@pytest.mark.parametrize("kind", [
    "constant", "linear_up", "linear_down", "oscillating",
    "near_equal", "outlier", "reversed",
])
def test_stage9_stage12_range_features_are_equivalent(config, kind):
    dates = pd.bdate_range(end=AS_OF, periods=40)
    index = np.arange(40, dtype=float)
    close = {
        "constant": np.full(40, 10.0),
        "linear_up": 10.0 * np.exp(0.002 * index),
        "linear_down": 10.0 * np.exp(-0.002 * index),
        "oscillating": 10.0 + np.sin(index / 3.0) * 0.2,
        "near_equal": 10.0 + index * 1e-10,
        "outlier": np.where(index == 20, 10.8, 10.0),
        "reversed": 10.0 * np.exp(0.001 * index),
    }[kind]
    frame = pd.DataFrame({
        "instrument": "000001", "trade_date": dates,
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close,
    })
    if kind == "reversed":
        frame = frame.iloc[::-1].reset_index(drop=True)
    result = analyze_range_bound(
        frame, as_of_date=AS_OF, config=config["range_bound"]
    ).iloc[0]
    ordered = frame.sort_values("trade_date", kind="mergesort")
    high, low = float(ordered["high"].max()), float(ordered["low"].min())
    width, width_pct = compute_range_width(high, low)
    slope, slope_pct, r2 = compute_log_trend(ordered["close"])
    assert result.window_high == pytest.approx(high)
    assert result.window_low == pytest.approx(low)
    assert result.range_width == pytest.approx(width)
    assert result.range_width_pct == pytest.approx(width_pct)
    assert result.trend_slope == pytest.approx(slope, abs=1e-15)
    assert result.trend_slope_pct == pytest.approx(slope_pct, abs=1e-15)
    assert result.trend_r2 == pytest.approx(r2, abs=1e-15)


def test_unified_analysis_is_ready_deterministic_and_no_lookahead(tmp_path):
    kwargs = dict(
        root=ROOT, as_of_date=AS_OF, config_path=ROOT / "config/stage12.yml",
        output_database=tmp_path / "out.duckdb", run_id="same-run", dry_run=True,
    )
    first, code = analyze_stage12(
        price_frame=price_fixture(future=True), fundamental_frame=fundamental_fixture(future=True), **kwargs
    )
    changed_prices = price_fixture(future=True)
    changed_prices.loc[changed_prices.trade_date.astype(str).eq("2026-07-28"), "volume"] = 7
    changed_fundamentals = fundamental_fixture(future=True)
    changed_fundamentals.loc[changed_fundamentals.available_date.eq("2026-08-30"), "growth_score"] = 0
    second, second_code = analyze_stage12(
        price_frame=changed_prices, fundamental_frame=changed_fundamentals, **kwargs
    )
    assert code == second_code == 0
    assert first == second
    assert first["status"] == "READY"
    assert first["canonical_sha256"] == second["canonical_sha256"]
    assert not (tmp_path / "out.duckdb").exists()


def test_missing_fundamentals_are_explicit_warning_not_zero(tmp_path):
    report, code = analyze_stage12(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(), fundamental_frame=None,
        config_path=ROOT / "config/stage12.yml", output_database=tmp_path / "none.duckdb",
        run_id="no-fundamental", dry_run=True,
    )
    assert code == 0
    assert "fundamental_input_unavailable" in report["warnings"]
    assert report["status"] == "READY"


def test_weekend_cutoff_uses_latest_visible_trading_row(tmp_path):
    weekend = pd.Timestamp("2026-08-01")
    report, code = analyze_stage12(
        root=ROOT, as_of_date=weekend, price_frame=price_fixture(),
        fundamental_frame=fundamental_fixture(), config_path=ROOT / "config/stage12.yml",
        output_database=tmp_path / "weekend.duckdb", run_id="weekend", dry_run=True,
    )
    assert code == 0
    assert report["status"] == "READY"


@pytest.mark.parametrize("mutation,match", [
    (lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True), "duplicate business keys"),
    (lambda frame: frame.assign(valuation_score=np.inf), "valuation_score"),
])
def test_fundamental_input_rejects_invalid_records(tmp_path, mutation, match):
    report, code = analyze_stage12(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(),
        fundamental_frame=mutation(fundamental_fixture()),
        config_path=ROOT / "config/stage12.yml", output_database=tmp_path / "bad.duckdb",
        reports_dir=tmp_path / "reports", run_id="bad-fundamental", dry_run=True,
    )
    assert code == 2 and report["status"] == "BLOCKED"
    assert any(match in reason for reason in report["blocking_reasons"])
    assert not (tmp_path / "bad.duckdb").exists()
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("column", [
    "valuation_score", "profitability_score", "growth_score", "quality_score",
    "financial_health_score", "revenue_growth", "profit_growth",
])
@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf, "not-a-number"])
def test_all_fundamental_scoring_inputs_reject_nonfinite_values(
    tmp_path, column, bad_value,
):
    frame = fundamental_fixture().drop(columns=["quality_score"])
    if column != "growth_score":
        frame = frame.drop(columns=["growth_score"])
    frame[column] = bad_value
    report, code = analyze_stage12(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(),
        fundamental_frame=frame, config_path=ROOT / "config/stage12.yml",
        output_database=tmp_path / "invalid.duckdb", reports_dir=tmp_path / "reports",
        run_id=f"invalid-{column}", dry_run=True,
    )
    assert code == 2 and report["status"] == "BLOCKED"
    assert any(column in reason for reason in report["blocking_reasons"])
    assert report["database_write_status"] == "not_written_blocked"
    assert not (tmp_path / "invalid.duckdb").exists()
    assert not (tmp_path / "reports").exists()


def test_original_growth_infinity_probe_is_structurally_blocked(tmp_path):
    frame = fundamental_fixture().drop(columns=["growth_score"])
    frame["revenue_growth"] = np.inf
    frame["profit_growth"] = 0.1
    report, code = analyze_stage12(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(),
        fundamental_frame=frame, config_path=ROOT / "config/stage12.yml",
        output_database=tmp_path / "original.duckdb", reports_dir=tmp_path / "reports",
        run_id="original-infinity", dry_run=True,
    )
    assert code == 2 and report["status"] == "BLOCKED"
    assert report["blocking_reasons"] == [
        "invalid_fundamental_input:fundamental.revenue_growth must be a finite numeric value when the field is present"
    ]
    assert not (tmp_path / "original.duckdb").exists()
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("revenue_growth,profit_growth,expected", [
    (4.0, 2.0, 1.0),
    (-2.0, -1.0, 0.0),
])
def test_finite_growth_fallback_preserves_mapping(
    tmp_path, revenue_growth, profit_growth, expected,
):
    frame = fundamental_fixture().drop(columns=["growth_score"])
    frame["revenue_growth"] = revenue_growth
    frame["profit_growth"] = profit_growth
    report, code = analyze_stage12(
        root=ROOT, as_of_date=AS_OF, price_frame=price_fixture(),
        fundamental_frame=frame, config_path=ROOT / "config/stage12.yml",
        output_database=tmp_path / "valid.duckdb", reports_dir=tmp_path / "reports",
        run_id="valid-growth",
    )
    assert code == 0 and report["status"] == "READY"
    combined = pd.read_csv(
        tmp_path / "reports" / "stage12_fundamental_price_volume.csv",
        dtype={"instrument": str},
    ).set_index("instrument")
    assert combined.at["000001", "growth_score"] == pytest.approx(expected)


def test_threshold_boundary_is_inclusive(config):
    visible, _ = normalize_price_frame(price_fixture(), as_of_date=AS_OF)
    cfg = copy.deepcopy(config["active_stock"])
    cfg["ranking_method"] = config["ranking_method"]
    result = analyze_active_stocks(visible, as_of_date=AS_OF, config=cfg)
    threshold = float(result.activity_score.dropna().max())
    cfg["score_threshold"] = threshold
    boundary = analyze_active_stocks(visible, as_of_date=AS_OF, config=cfg)
    assert boundary.loc[boundary.activity_score.eq(threshold), "is_active"].all()
