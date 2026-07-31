"""Stage 7 feature and activity quality checks."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from akshare_data_test.features.stock_daily_features import Stage7Parameters


def run_stage7_quality_checks(
    input_daily: pd.DataFrame,
    features: pd.DataFrame,
    activity: pd.DataFrame,
    parameters: Stage7Parameters,
    target_symbols: list[str],
) -> list[dict[str, Any]]:
    """Return machine-readable Stage 7 ERROR/WARNING/PASS checks."""
    checks: list[dict[str, Any]] = []

    def add(
        name: str,
        passed: bool,
        observed: Any,
        expected: Any,
        *,
        severity: str = "ERROR",
        details: str = "",
    ) -> None:
        checks.append(
            {
                "check_name": name,
                "status": "PASS" if passed else ("WARNING" if severity == "WARNING" else "FAIL"),
                "severity": severity,
                "observed_value": str(observed),
                "expected_value": str(expected),
                "details": details,
            }
        )

    key = ["symbol", "trade_date", "adjust_type"]
    add("input_primary_key_unique", not input_daily.duplicated(key).any(), int(input_daily.duplicated(key).sum()), 0)
    add("output_primary_key_unique", not features.duplicated(key).any(), int(features.duplicated(key).sum()), 0)
    add(
        "input_output_row_count_equal",
        len(input_daily) == len(features),
        len(features),
        len(input_daily),
    )
    add("qfq_only", features["adjust_type"].eq("qfq").all(), sorted(features["adjust_type"].dropna().unique()), ["qfq"])
    monotonic = features.groupby("symbol")["trade_date"].apply(lambda s: s.is_monotonic_increasing)
    add("dates_monotonic_by_symbol", bool(monotonic.all()), int((~monotonic).sum()), 0)
    ma_columns = [f"ma_{window}" for window in parameters.ma_windows]
    add("all_ma_columns_present", set(ma_columns).issubset(features.columns), sorted(set(ma_columns).difference(features.columns)), [])
    for window in parameters.ma_windows:
        warmup = features.groupby("symbol").head(window - 1)[f"ma_{window}"]
        add(
            f"ma_{window}_full_window",
            warmup.isna().all(),
            int(warmup.notna().sum()),
            0,
        )
    first_rows = features.groupby("symbol").head(1)
    boundary_columns = ["prev_close", "return_1d", "intraday_range", "gap_return"]
    add("no_cross_symbol_shift", first_rows[boundary_columns].isna().all().all(), int(first_rows[boundary_columns].notna().sum().sum()), 0)
    finite_columns = ["return_1d", "volume_ratio_20", "intraday_range", "gap_return", "volatility_20"]
    infinite_count = int(np.isinf(features[finite_columns].to_numpy(dtype=float, na_value=np.nan)).sum())
    add("no_infinite_features", infinite_count == 0, infinite_count, 0)
    negative_ratio = int(features["volume_ratio_20"].dropna().lt(0).sum())
    add("volume_ratio_nonnegative", negative_ratio == 0, negative_ratio, 0)
    range_columns = PERCENTILES_AND_COMPONENTS + ["activity_score"]
    out_of_range = int(((activity[range_columns] < 0) | (activity[range_columns] > 1)).sum().sum())
    add("scores_in_unit_interval", out_of_range == 0, out_of_range, 0)
    scored = activity["score_status"].eq("scored")
    incomplete_scored = int(
        activity.loc[scored, range_columns].isna().any(axis=1).sum()
    )
    add("scored_rows_complete", incomplete_scored == 0, incomplete_scored, 0)
    add("activity_business_key_unique", not activity.duplicated(["symbol", "as_of_date"]).any(), int(activity.duplicated(["symbol", "as_of_date"]).sum()), 0)
    weights = parameters.activity_weights
    recomputed = (
        weights["turnover_amount_quantile"] * activity["liquidity_component"]
        + weights["turnover_rate_quantile"] * activity["turnover_component"]
        + weights["volatility_quantile"] * activity["volatility_component"]
        + weights["volume_spike_frequency_quantile"] * activity["volume_spike_component"]
        + weights["large_move_frequency_quantile"] * activity["large_move_component"]
        + weights["limit_and_gap_event_frequency_quantile"] * activity["event_component"]
    )
    score_match = np.isclose(activity["activity_score"], recomputed, equal_nan=True)
    add("activity_score_decomposition", bool(score_match.all()), int((~score_match).sum()), 0)
    metadata_ok = (
        activity["score_version"].eq(parameters.score_version).all()
        and activity["event_component_source"]
        .eq(parameters.event_component_source)
        .all()
    )
    add("score_metadata_present", bool(metadata_ok), bool(metadata_ok), True)
    present = set(features["symbol"].astype(str))
    extras = sorted(present.difference(target_symbols))
    add(
        "no_extra_symbols",
        not extras,
        len(extras),
        0,
        details="extra=" + ",".join(extras),
    )
    missing = sorted(set(target_symbols).difference(present))
    add("target_symbol_coverage", not missing, len(present.intersection(target_symbols)), len(target_symbols), severity="WARNING", details="missing=" + ",".join(missing))
    insufficient = activity.loc[activity["observation_count"].lt(parameters.minimum_scoring_observations), "symbol"].tolist()
    add("minimum_activity_observations", not insufficient, len(insufficient), 0, severity="WARNING", details="symbols=" + ",".join(insufficient))
    activity_symbols = set(activity["symbol"].astype(str))
    extra_activity = sorted(activity_symbols.difference(target_symbols))
    add(
        "no_extra_activity_symbols",
        not extra_activity,
        len(extra_activity),
        0,
        details="extra=" + ",".join(extra_activity),
    )
    latest_dates = features.groupby("symbol")["trade_date"].max()
    activity_dates = activity.set_index("symbol")["as_of_date"]
    comparable = activity_dates.index.intersection(latest_dates.index)
    latest_match = (
        pd.to_datetime(activity_dates.loc[comparable]).dt.normalize()
        == pd.to_datetime(latest_dates.loc[comparable]).dt.normalize()
    )
    add(
        "activity_as_of_matches_latest_trade",
        bool(latest_match.all()),
        int((~latest_match).sum()),
        0,
    )
    return checks


PERCENTILES_AND_COMPONENTS = [
    "amount_percentile",
    "turnover_percentile",
    "volatility_percentile",
    "volume_spike_percentile",
    "large_move_percentile",
    "event_frequency_percentile",
    "liquidity_component",
    "turnover_component",
    "volatility_component",
    "volume_spike_component",
    "large_move_component",
    "event_component",
]
