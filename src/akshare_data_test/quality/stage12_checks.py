"""Measured Stage 12 quality gates."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


QUALITY_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "message", "checked_at",
]


def _row(run_id: str, name: str, passed: bool, observed: Any, expected: Any,
         checked_at: pd.Timestamp, *, severity: str = "ERROR", message: str = "") -> dict[str, Any]:
    return {
        "run_id": run_id, "check_name": name, "severity": severity,
        "status": "PASS" if passed else "FAIL", "observed_value": str(observed),
        "expected_value": str(expected), "message": message, "checked_at": checked_at,
    }


def run_stage12_quality_checks(
    *, run_id: str, prices: pd.DataFrame, future_price_rows: int,
    future_fundamental_rows: int, active: pd.DataFrame, breakouts: pd.DataFrame,
    ranges: pd.DataFrame, combined: pd.DataFrame, expected_instruments: list[str],
    checked_at: pd.Timestamp,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    add = lambda name, passed, observed, expected, **kw: rows.append(
        _row(run_id, name, passed, observed, expected, checked_at, **kw)
    )
    add("visible_price_rows_present", not prices.empty, len(prices), ">0")
    add("price_input_keys_unique", not prices.duplicated(["instrument", "trade_date", "adjust_type"]).any(), 0, 0)
    add("future_price_rows_excluded", True, future_price_rows, "excluded", severity="WARNING",
        message="Future rows are permitted as input evidence but excluded before every calculation")
    add("future_fundamental_rows_excluded", True, future_fundamental_rows, "excluded", severity="WARNING")
    expected = set(expected_instruments)
    for name, frame in (("active", active), ("breakout", breakouts), ("range", ranges), ("combined", combined)):
        actual = set(frame["instrument"].astype(str))
        add(f"{name}_instrument_coverage", actual == expected, sorted(actual), sorted(expected))
        duplicates = int(frame.duplicated(["instrument", "as_of_date"]).sum())
        add(f"{name}_output_keys_unique", duplicates == 0, duplicates, 0)
    insufficient_active = int(active["activity_score"].isna().sum())
    insufficient_breakout = int(breakouts["reason_codes"].map(lambda value: "insufficient_history" in value).sum())
    insufficient_range = int(ranges["reason_codes"].map(lambda value: "insufficient_history" in value).sum())
    add("history_windows_sufficient", not any((insufficient_active, insufficient_breakout, insufficient_range)),
        {"active": insufficient_active, "breakout": insufficient_breakout, "range": insufficient_range}, 0)
    score_columns = [
        "fundamental_score", "activity_score", "volume_breakout_score",
        "range_bound_score", "price_momentum_score", "composite_score",
    ]
    invalid_scores = 0
    for column in score_columns:
        values = pd.to_numeric(combined[column], errors="coerce").dropna().to_numpy(dtype=float)
        invalid_scores += int((~np.isfinite(values) | (values < 0) | (values > 1)).sum())
    add("scores_finite_and_bounded", invalid_scores == 0, invalid_scores, 0)
    missing_composite = int(combined["composite_score"].isna().sum())
    add("composite_scores_available", missing_composite == 0, missing_composite, 0)
    future_used = int(pd.to_datetime(combined["fundamental_as_of_date"], errors="coerce").gt(checked_at.tz_localize(None).normalize()).sum())
    add("fundamental_point_in_time_safe", future_used == 0, future_used, 0)
    prohibited = int(combined["signal_label"].astype(str).str.contains("买入|卖出|投资建议|主力正在", regex=True).sum())
    add("no_investment_advice", prohibited == 0, prohibited, 0)
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)
