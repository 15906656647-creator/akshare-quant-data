"""Multi-metric range-bound price analysis."""
from __future__ import annotations

import pandas as pd

from ..style_features import compute_log_trend, compute_range_width


def analyze_range_bound(prices: pd.DataFrame, *, as_of_date: pd.Timestamp, config: dict) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for instrument, group in prices.groupby("instrument", sort=True):
        sample = group.sort_values("trade_date", kind="mergesort").tail(int(config["lookback_days"]))
        reasons: list[str] = []
        enough = len(sample) >= int(config["min_history_days"])
        if not enough:
            reasons.append("insufficient_history")
        high, low = float(sample["high"].max()), float(sample["low"].min())
        mid = (high + low) / 2.0
        width, width_pct = compute_range_width(high, low)
        linear_slope, slope_pct, r2 = compute_log_trend(sample["close"])
        if linear_slope is None or slope_pct is None or r2 is None:
            raise ValueError("Stage 12 range trend requires finite positive close prices")
        close_position = (float(sample.iloc[-1]["close"]) - low) / width if width else 0.5
        lower = float(sample["close"].quantile(float(config["inner_quantile_lower"])))
        upper = float(sample["close"].quantile(float(config["inner_quantile_upper"])))
        outside = float((sample["close"].lt(lower) | sample["close"].gt(upper)).mean())
        checks = [
            width_pct <= float(config["max_range_width_pct"]),
            abs(slope_pct) <= float(config["max_abs_slope_pct"]),
            r2 <= float(config["max_trend_r2"]),
            outside <= float(config["max_outside_ratio"]),
        ]
        is_range = bool(enough and all(checks))
        reasons.append("range_bound_confirmed" if is_range else "range_bound_not_confirmed")
        rows.append({
            "instrument": str(instrument), "as_of_date": pd.Timestamp(as_of_date).normalize(),
            "window_start": sample["trade_date"].min(), "window_end": sample["trade_date"].max(),
            "observations": int(len(sample)), "window_high": high, "window_low": low,
            "window_mid": mid, "range_width": width, "range_width_pct": width_pct,
            "trend_slope": linear_slope, "trend_slope_pct": slope_pct, "trend_r2": r2,
            "close_position": close_position, "outside_ratio": outside,
            "is_range_bound": is_range, "reason_codes": sorted(set(reasons)),
        })
    return pd.DataFrame(rows).sort_values("instrument", kind="mergesort").reset_index(drop=True)
