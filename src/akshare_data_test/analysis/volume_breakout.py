"""Causal volume-breakout detection with an observation-excluded baseline."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stage12_common import safe_ratio


def analyze_volume_breakouts(prices: pd.DataFrame, *, as_of_date: pd.Timestamp, config: dict) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for instrument, group in prices.groupby("instrument", sort=True):
        group = group.sort_values("trade_date", kind="mergesort")
        current = group.iloc[-1]
        baseline = group.iloc[:-1].tail(int(config["lookback_days"]))
        volumes = baseline["volume"]
        mean = float(volumes.mean()) if len(volumes) else np.nan
        median = float(volumes.median()) if len(volumes) else np.nan
        std = float(volumes.std(ddof=0)) if len(volumes) else np.nan
        ratio_mean = safe_ratio(current["volume"], mean)
        ratio_median = safe_ratio(current["volume"], median)
        zscore = safe_ratio(float(current["volume"]) - mean, std)
        previous = group.iloc[-2] if len(group) >= 2 else None
        price_return = safe_ratio(current["close"], previous["close"]) if previous is not None else None
        price_return = price_return - 1.0 if price_return is not None else None
        amount_change = safe_ratio(current["amount"], previous["amount"]) if previous is not None else None
        amount_change = amount_change - 1.0 if amount_change is not None else None
        reasons: list[str] = []
        enough = len(baseline) >= int(config["min_history_days"])
        if not enough:
            reasons.append("insufficient_history")
        if std == 0:
            reasons.append("zero_baseline_variance")
        checks = [
            ratio_mean is not None and ratio_mean >= float(config["ratio_to_mean_threshold"]),
            ratio_median is not None and ratio_median >= float(config["ratio_to_median_threshold"]),
            zscore is not None and zscore >= float(config["zscore_threshold"]),
            float(current["volume"]) >= float(config["minimum_volume"]),
        ]
        if config["require_positive_return"]:
            checks.append(price_return is not None and price_return > 0)
        if config["require_amount_confirmation"]:
            checks.append(amount_change is not None and amount_change >= float(config["amount_change_threshold"]))
        breakout = bool(enough and all(checks))
        reasons.append("volume_breakout_confirmed" if breakout else "volume_breakout_not_confirmed")
        rows.append({
            "instrument": str(instrument), "as_of_date": pd.Timestamp(as_of_date).normalize(),
            "observation_date": current["trade_date"],
            "baseline_start": baseline["trade_date"].min() if len(baseline) else pd.NaT,
            "baseline_end": baseline["trade_date"].max() if len(baseline) else pd.NaT,
            "baseline_observations": int(len(baseline)), "current_volume": float(current["volume"]),
            "historical_mean_volume": mean, "historical_median_volume": median,
            "historical_std_volume": std, "volume_ratio_to_mean": ratio_mean,
            "volume_ratio_to_median": ratio_median, "volume_zscore": zscore,
            "price_return": price_return, "amount_change": amount_change,
            "breakout_rule": "mean_and_median_and_zscore",
            "is_volume_breakout": breakout, "reason_codes": sorted(set(reasons)),
        })
    return pd.DataFrame(rows).sort_values("instrument", kind="mergesort").reset_index(drop=True)
