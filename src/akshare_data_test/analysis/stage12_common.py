"""Shared validation and deterministic helpers for Stage 12."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd


PRICE_COLUMNS = {
    "instrument", "trade_date", "adjust_type", "open", "high", "low",
    "close", "volume", "amount", "turnover_rate",
}


def normalize_price_frame(frame: pd.DataFrame, *, as_of_date: pd.Timestamp) -> tuple[pd.DataFrame, int]:
    """Validate canonical qfq prices and remove rows after the explicit cutoff."""
    data = frame.copy()
    aliases = {"symbol": "instrument", "volume_share": "volume", "amount_cny": "amount"}
    for source, target in aliases.items():
        if target not in data and source in data:
            data = data.rename(columns={source: target})
    missing = sorted(PRICE_COLUMNS.difference(data.columns))
    if missing:
        raise ValueError(f"Stage 12 price input missing columns: {missing}")
    data["instrument"] = data["instrument"].astype("string").str.strip().str.zfill(6)
    if data["instrument"].isna().any() or data["instrument"].eq("").any():
        raise ValueError("Stage 12 instrument cannot be empty")
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    if data["trade_date"].isna().any():
        raise ValueError("Stage 12 trade_date contains invalid values")
    if not data["adjust_type"].astype(str).str.lower().eq("qfq").all():
        raise ValueError("Stage 12 price input must use adjust_type=qfq")
    numeric = ["open", "high", "low", "close", "volume", "amount", "turnover_rate"]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    required_finite = ["open", "high", "low", "close", "volume", "amount"]
    values = data[required_finite].to_numpy(dtype=float)
    if np.isnan(values).any() or np.isinf(values).any():
        raise ValueError("Stage 12 core price values must be finite")
    turnover_values = data["turnover_rate"].dropna().to_numpy(dtype=float)
    if np.isinf(turnover_values).any():
        raise ValueError("Stage 12 turnover_rate must be finite when present")
    if data[["open", "high", "low", "close"]].le(0).any().any():
        raise ValueError("Stage 12 prices must be positive")
    if data[["volume", "amount", "turnover_rate"]].lt(0).any().any():
        raise ValueError("Stage 12 volume, amount, and turnover cannot be negative")
    invalid_ohlc = (
        data["high"].lt(data[["open", "close", "low"]].max(axis=1))
        | data["low"].gt(data[["open", "close", "high"]].min(axis=1))
    )
    if invalid_ohlc.any():
        raise ValueError("Stage 12 OHLC relationship is invalid")
    key = ["instrument", "trade_date", "adjust_type"]
    if data.duplicated(key).any():
        raise ValueError("Stage 12 price input contains duplicate business keys")
    cutoff = pd.Timestamp(as_of_date).normalize()
    future_count = int(data["trade_date"].gt(cutoff).sum())
    visible = data.loc[data["trade_date"].le(cutoff)].copy()
    visible = visible.sort_values(["instrument", "trade_date"], kind="mergesort").reset_index(drop=True)
    return visible, future_count


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
        return None
    result = float(numerator) / float(denominator)
    return result if math.isfinite(result) else None


def weighted_available(values: dict[str, float | None], weights: dict[str, float]) -> tuple[float | None, float]:
    available = {key: float(value) for key, value in values.items() if value is not None and math.isfinite(float(value))}
    denominator = sum(float(weights[key]) for key in available)
    if denominator <= 0:
        return None, 0.0
    score = sum(available[key] * float(weights[key]) for key in available) / denominator
    return float(score), float(denominator)


def canonical_value(value: Any, *, precision: int = 12) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else round(float(value), precision)
    if isinstance(value, (list, tuple)):
        return [canonical_value(item, precision=precision) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def canonical_frame_hash(frame: pd.DataFrame, *, sort_by: list[str], precision: int = 12) -> str:
    ordered = frame.sort_values(sort_by, kind="mergesort", na_position="first").reset_index(drop=True)
    records = [
        {column: canonical_value(row[column], precision=precision) for column in ordered.columns}
        for _, row in ordered.iterrows()
    ]
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
