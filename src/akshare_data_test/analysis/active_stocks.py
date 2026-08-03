"""Explainable cross-sectional active-stock screening."""
from __future__ import annotations

import numpy as np
import pandas as pd


def analyze_active_stocks(prices: pd.DataFrame, *, as_of_date: pd.Timestamp, config: dict) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    lookback = int(config["lookback_days"])
    for instrument, group in prices.groupby("instrument", sort=True):
        sample = group.sort_values("trade_date", kind="mergesort").tail(lookback).copy()
        valid = sample.loc[sample["volume"].gt(0)]
        reasons: list[str] = []
        if len(valid) < int(config["min_valid_days"]):
            reasons.append("insufficient_valid_days")
        average_turnover = valid["turnover_rate"].mean(skipna=True)
        if valid["turnover_rate"].notna().sum() == 0:
            average_turnover = np.nan
            reasons.append("turnover_missing")
        zero_ratio = float(sample["volume"].eq(0).mean()) if len(sample) else np.nan
        if zero_ratio > float(config["max_zero_volume_ratio"]):
            reasons.append("zero_volume_ratio_exceeded")
        average_amount = valid["amount"].mean()
        if pd.notna(average_amount) and average_amount < float(config["min_average_amount"]):
            reasons.append("average_amount_below_minimum")
        rows.append({
            "instrument": str(instrument), "as_of_date": pd.Timestamp(as_of_date).normalize(),
            "lookback_start": sample["trade_date"].min() if not sample.empty else pd.NaT,
            "valid_days": int(len(valid)), "average_volume": valid["volume"].mean(),
            "average_amount": average_amount, "average_turnover": average_turnover,
            "zero_volume_ratio": zero_ratio, "reason_codes": reasons,
        })
    result = pd.DataFrame(rows)
    metrics = {
        "average_volume": "volume_percentile", "average_amount": "amount_percentile",
        "average_turnover": "turnover_percentile",
    }
    method = str(config.get("ranking_method", "average"))
    for metric, percentile in metrics.items():
        result[percentile] = result[metric].rank(method=method, pct=True)
    weights = config["weights"]
    result["activity_score"] = (
        result["amount_percentile"] * float(weights["amount_percentile"])
        + result["volume_percentile"] * float(weights["volume_percentile"])
        + result["turnover_percentile"] * float(weights["turnover_percentile"])
    )
    missing = result[["volume_percentile", "amount_percentile", "turnover_percentile"]].isna().any(axis=1)
    result.loc[missing, "activity_score"] = np.nan
    insufficient = result["valid_days"].lt(int(config["min_valid_days"]))
    result.loc[insufficient, "activity_score"] = np.nan
    result["activity_rank"] = result["activity_score"].rank(method=method, ascending=False)
    result["is_active"] = result["activity_score"].ge(float(config["score_threshold"])) & ~missing & ~insufficient
    for index in result.index:
        reasons = list(result.at[index, "reason_codes"])
        reasons.append("active_threshold_met" if bool(result.at[index, "is_active"]) else "active_threshold_not_met")
        result.at[index, "reason_codes"] = sorted(set(reasons))
    columns = [
        "instrument", "as_of_date", "lookback_start", "valid_days", "average_volume",
        "average_amount", "average_turnover", "zero_volume_ratio", "volume_percentile",
        "amount_percentile", "turnover_percentile", "activity_score", "activity_rank",
        "is_active", "reason_codes",
    ]
    return result[columns].sort_values(["activity_rank", "instrument"], kind="mergesort", na_position="last").reset_index(drop=True)
