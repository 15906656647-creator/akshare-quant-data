"""Transparent point-in-time fundamental and price-volume composition."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stage12_common import weighted_available


def _normal_score(value: object, *, percent_scale: bool = False) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value) / 100.0 if percent_scale else float(value)
    if not np.isfinite(number):
        raise ValueError("Fundamental score must be finite before normalization")
    return float(min(1.0, max(0.0, number)))


def _growth_score(row: pd.Series) -> float | None:
    if "growth_score" in row and pd.notna(row["growth_score"]):
        return _normal_score(row["growth_score"])
    values = [row.get("revenue_growth"), row.get("profit_growth")]
    available = [float(value) for value in values if value is not None and pd.notna(value)]
    if not available:
        return None
    if not np.isfinite(np.asarray(available, dtype=float)).all():
        raise ValueError("Fundamental growth inputs must be finite before normalization")
    return float(np.mean([min(1.0, max(0.0, 0.5 + value / 2.0)) for value in available]))


def analyze_fundamental_price_volume(
    fundamentals: pd.DataFrame | None, *, as_of_date: pd.Timestamp,
    active: pd.DataFrame, breakouts: pd.DataFrame, ranges: pd.DataFrame,
    prices: pd.DataFrame, config: dict,
) -> pd.DataFrame:
    frame = pd.DataFrame() if fundamentals is None else fundamentals.copy()
    generated_missing = frame.empty
    if "symbol" in frame and "instrument" not in frame:
        frame = frame.rename(columns={"symbol": "instrument"})
    if frame.empty:
        frame = pd.DataFrame({"instrument": sorted(prices["instrument"].unique())})
        frame["available_date"] = pd.NaT
    if "instrument" not in frame:
        raise ValueError("Stage 12 fundamental input missing instrument")
    date_column = next((name for name in ("available_date", "announcement_date", "fundamental_as_of_date") if name in frame), None)
    if date_column is None:
        raise ValueError("Stage 12 fundamental input requires an availability date")
    frame["instrument"] = frame["instrument"].astype("string").str.strip().str.zfill(6)
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce").dt.normalize()
    invalid_date = frame[date_column].isna() & frame.drop(columns=[date_column]).notna().any(axis=1)
    if generated_missing:
        invalid_date[:] = False
    if invalid_date.any():
        raise ValueError("Stage 12 fundamental availability date is invalid")
    visible = frame.loc[frame[date_column].le(pd.Timestamp(as_of_date).normalize())].copy()
    visible = visible.sort_values(["instrument", date_column], kind="mergesort").drop_duplicates("instrument", keep="last")
    active_map = active.set_index("instrument")
    breakout_map = breakouts.set_index("instrument")
    range_map = ranges.set_index("instrument")
    rows: list[dict[str, object]] = []
    fpv = config
    for instrument in sorted(prices["instrument"].unique()):
        match = visible.loc[visible["instrument"].eq(instrument)]
        source = match.iloc[-1] if not match.empty else pd.Series(dtype=object)
        profitability = _normal_score(source.get("profitability_score"), percent_scale=float(source.get("profitability_score", 0) or 0) > 1)
        quality_source = source.get("quality_score", source.get("financial_health_score"))
        quality = _normal_score(quality_source, percent_scale=float(quality_source or 0) > 1 if quality_source is not None and not pd.isna(quality_source) else False)
        valuation = _normal_score(source.get("valuation_score"))
        growth = _growth_score(source)
        fundamental_score, fundamental_weight = weighted_available(
            {"valuation_score": valuation, "profitability_score": profitability, "growth_score": growth, "quality_score": quality},
            fpv["fundamental_weights"],
        )
        activity_score = active_map.at[instrument, "activity_score"] if instrument in active_map.index else np.nan
        breakout_score = float(bool(breakout_map.at[instrument, "is_volume_breakout"])) if instrument in breakout_map.index else None
        range_score = float(bool(range_map.at[instrument, "is_range_bound"])) if instrument in range_map.index else None
        price_sample = prices.loc[prices["instrument"].eq(instrument)].tail(21)
        momentum = None
        if len(price_sample) >= 2:
            raw_momentum = float(price_sample.iloc[-1]["close"] / price_sample.iloc[0]["close"] - 1.0)
            momentum = min(1.0, max(0.0, 0.5 + raw_momentum))
        composite, composite_weight = weighted_available(
            {
                "fundamental_score": fundamental_score,
                "activity_score": None if pd.isna(activity_score) else float(activity_score),
                "volume_breakout_score": breakout_score, "range_bound_score": range_score,
                "price_momentum_score": momentum,
            }, fpv["composite_weights"],
        )
        thresholds = fpv["signal_thresholds"]
        label = "insufficient_data" if composite is None else (
            "strong_characteristics" if composite >= float(thresholds["strong"]) else
            "moderate_characteristics" if composite >= float(thresholds["moderate"]) else "limited_characteristics"
        )
        reasons = ["point_in_time_fundamental_used" if not match.empty else "fundamental_data_missing", label]
        rows.append({
            "instrument": instrument, "as_of_date": pd.Timestamp(as_of_date).normalize(),
            "fundamental_as_of_date": source.get(date_column, pd.NaT),
            "fundamental_score": fundamental_score, "valuation_score": valuation,
            "profitability_score": profitability, "growth_score": growth, "quality_score": quality,
            "activity_score": activity_score, "volume_breakout_score": breakout_score,
            "range_bound_score": range_score, "price_momentum_score": momentum,
            "composite_score": composite, "signal_label": label,
            "reason_codes": sorted(reasons),
            "data_completeness": composite_weight,
            "fundamental_data_completeness": fundamental_weight,
        })
    return pd.DataFrame(rows).sort_values("instrument", kind="mergesort").reset_index(drop=True)
