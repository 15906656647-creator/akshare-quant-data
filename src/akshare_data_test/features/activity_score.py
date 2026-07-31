"""Stage 7 cross-sectional 120-trading-day activity score."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stock_daily_features import Stage7Parameters


PERCENTILE_COLUMNS = [
    "amount_percentile",
    "turnover_percentile",
    "volatility_percentile",
    "volume_spike_percentile",
    "large_move_percentile",
    "event_frequency_percentile",
]


def _valid_frequency(flag: pd.Series) -> float:
    values = flag.dropna()
    return float(values.astype(bool).mean()) if not values.empty else np.nan


def compute_activity_scores(
    features: pd.DataFrame,
    parameters: Stage7Parameters,
    *,
    as_of_date: pd.Timestamp,
    lookback_days: int | None = None,
) -> pd.DataFrame:
    """Summarise recent valid trading rows and rank the current stock sample.

    The event component is explicitly a configured gap-frequency proxy. It is
    not a formal limit-up/limit-down statistic. Missing component metrics remain
    null and result in ``insufficient_data`` rather than an implicit zero score.
    """
    window = (
        parameters.activity_lookback_days
        if lookback_days is None
        else lookback_days
    )
    if window <= 0:
        raise ValueError("lookback_days must be positive")
    cutoff = pd.Timestamp(as_of_date)
    frame = features.loc[features["trade_date"].le(cutoff)].copy()
    frame = (
        frame.sort_values(["symbol", "trade_date"])
        .groupby("symbol", sort=False, group_keys=False)
        .tail(window)
    )
    rows: list[dict[str, object]] = []
    for symbol, group in frame.groupby("symbol", sort=True):
        gap_valid = group["gap_return"].dropna()
        rows.append(
            {
                "symbol": symbol,
                "as_of_date": cutoff,
                "lookback_days": window,
                "observation_count": int(len(group)),
                "avg_amount_120d": group["amount_cny"].mean(),
                "avg_turnover_120d": group["turnover_rate"].mean(),
                "avg_amplitude_120d": group["amplitude"].mean(),
                "avg_volatility_20_120d": group["volatility_20"].mean(),
                "volume_spike_frequency": _valid_frequency(
                    group["is_volume_spike"]
                ),
                "large_move_frequency": _valid_frequency(group["is_large_move"]),
                "gap_frequency": (
                    float(
                        gap_valid.abs().ge(parameters.gap_abs_threshold).mean()
                    )
                    if not gap_valid.empty
                    else np.nan
                ),
            }
        )
    result = pd.DataFrame(rows)
    metric_to_percentile = {
        "avg_amount_120d": "amount_percentile",
        "avg_turnover_120d": "turnover_percentile",
        "avg_volatility_20_120d": "volatility_percentile",
        "volume_spike_frequency": "volume_spike_percentile",
        "large_move_frequency": "large_move_percentile",
        "gap_frequency": "event_frequency_percentile",
    }
    for metric, percentile in metric_to_percentile.items():
        result[percentile] = result[metric].rank(method="average", pct=True)

    component_map = {
        "liquidity_component": "amount_percentile",
        "turnover_component": "turnover_percentile",
        "volatility_component": "volatility_percentile",
        "volume_spike_component": "volume_spike_percentile",
        "large_move_component": "large_move_percentile",
        "event_component": "event_frequency_percentile",
    }
    for component, percentile in component_map.items():
        result[component] = result[percentile]

    weights = parameters.activity_weights
    result["activity_score"] = (
        weights["turnover_amount_quantile"] * result["liquidity_component"]
        + weights["turnover_rate_quantile"] * result["turnover_component"]
        + weights["volatility_quantile"] * result["volatility_component"]
        + weights["volume_spike_frequency_quantile"]
        * result["volume_spike_component"]
        + weights["large_move_frequency_quantile"]
        * result["large_move_component"]
        + weights["limit_and_gap_event_frequency_quantile"]
        * result["event_component"]
    )
    missing_component = result[list(component_map)].isna().any(axis=1)
    insufficient_count = result["observation_count"].lt(
        parameters.minimum_scoring_observations
    )
    result["score_status"] = np.select(
        [missing_component, insufficient_count],
        ["missing_component", "insufficient_observations"],
        default="scored",
    )
    result.loc[missing_component, "activity_score"] = np.nan
    result["score_version"] = parameters.score_version
    result["event_component_source"] = parameters.event_component_source
    return result.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)
