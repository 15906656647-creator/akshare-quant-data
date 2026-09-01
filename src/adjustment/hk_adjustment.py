"""Evidence-bound Hong Kong OHLCV adjustment calculation.

This module never infers factors. Callers must provide one explicit price and
volume factor for every raw trading date plus independently sourced corporate-
action evidence.
"""
from __future__ import annotations

import re

import pandas as pd


RAW_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")
FACTOR_COLUMNS = (
    "symbol", "date", "price_factor", "volume_factor", "evidence_id", "source",
)
ACTION_COLUMNS = ("evidence_id", "event_type", "source", "source_sha256")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def apply_hk_adjustment(
    raw: pd.DataFrame,
    factors: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    *,
    symbol: str,
    adjust: str,
) -> pd.DataFrame:
    """Apply fully evidenced factors without dropping, sorting, or interpolating rows."""
    if symbol != "09669.HK":
        raise ValueError("Stage 17.6.5 adjustment is restricted to 09669.HK")
    if adjust not in {"qfq", "hfq"}:
        raise ValueError("adjust must be qfq or hfq")
    for name, frame, required in (
        ("raw", raw, RAW_COLUMNS),
        ("factors", factors, FACTOR_COLUMNS),
        ("corporate_actions", corporate_actions, ACTION_COLUMNS),
    ):
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"{name} missing required columns: {','.join(missing)}")
        if frame.empty:
            raise ValueError(f"{name} evidence cannot be empty")
    if set(raw["symbol"].astype("string")) != {symbol}:
        raise ValueError("raw symbol identity mismatch")
    if set(factors["symbol"].astype("string")) != {symbol}:
        raise ValueError("factor symbol identity mismatch")
    if raw["date"].duplicated().any() or factors["date"].duplicated().any():
        raise ValueError("raw and factor dates must be unique")
    action_ids = set(corporate_actions["evidence_id"].astype("string"))
    factor_ids = set(factors["evidence_id"].astype("string"))
    if not factor_ids.issubset(action_ids):
        raise ValueError("every factor evidence_id must reference corporate-action evidence")
    if corporate_actions["source"].astype("string").str.strip().eq("").any():
        raise ValueError("corporate-action source cannot be empty")
    if not corporate_actions["source_sha256"].astype("string").map(
        lambda value: bool(SHA256_PATTERN.fullmatch(str(value)))
    ).all():
        raise ValueError("corporate-action evidence requires SHA-256 values")
    left_dates = pd.to_datetime(raw["date"], errors="coerce")
    right_dates = pd.to_datetime(factors["date"], errors="coerce")
    if left_dates.isna().any() or right_dates.isna().any():
        raise ValueError("raw and factor dates must be valid")
    if set(left_dates) != set(right_dates) or len(raw) != len(factors):
        raise ValueError("factors must cover exactly every raw trading date")
    work = factors.copy()
    work["date"] = right_dates
    for field in ("price_factor", "volume_factor"):
        work[field] = pd.to_numeric(work[field], errors="coerce")
        if work[field].isna().any() or (work[field] <= 0).any():
            raise ValueError(f"{field} must contain positive numeric values")
    result = raw.copy()
    result["date"] = left_dates
    joined = result[["date"]].merge(
        work[["date", "price_factor", "volume_factor"]],
        on="date", how="left", validate="one_to_one", sort=False,
    )
    if joined[["price_factor", "volume_factor"]].isna().any().any():
        raise ValueError("factor join left uncovered raw dates")
    for field in ("open", "high", "low", "close"):
        numeric = pd.to_numeric(result[field], errors="coerce")
        if numeric.isna().any():
            raise ValueError(f"raw {field} must be numeric")
        result[field] = numeric * joined["price_factor"].to_numpy()
    volume = pd.to_numeric(result["volume"], errors="coerce")
    if volume.isna().any():
        raise ValueError("raw volume must be numeric")
    result["volume"] = volume * joined["volume_factor"].to_numpy()
    result["date"] = result["date"].dt.date
    result["adjustment_type"] = adjust
    result["price_factor"] = joined["price_factor"].to_numpy()
    result["volume_factor"] = joined["volume_factor"].to_numpy()
    return result
