"""Fail-closed quality checks for Stage 11 continuous crypto bars."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _quality_row(run_id: str, name: str, passed: bool, observed: Any, expected: Any, checked_at: pd.Timestamp, message: str = "") -> dict[str, Any]:
    return {
        "run_id": run_id, "check_name": name, "severity": "ERROR",
        "status": "PASS" if passed else "FAIL", "observed_value": str(observed),
        "expected_value": str(expected), "message": message, "checked_at": checked_at,
    }


def run_stage11_quality_checks(
    bars: pd.DataFrame, *, run_id: str, as_of_date: pd.Timestamp,
    interval: str, expected_symbol: str, checked_at: pd.Timestamp,
    expected_start: pd.Timestamp | None = None,
    expected_end_exclusive: pd.Timestamp | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    add = lambda name, passed, observed, expected, message="": rows.append(
        _quality_row(run_id, name, passed, observed, expected, checked_at, message)
    )
    times = pd.to_datetime(bars["trade_time"], errors="coerce", utc=True)
    expected_delta = pd.Timedelta(hours=1) if interval == "1h" else pd.Timedelta(days=1)
    unique_symbols = sorted(bars["symbol"].dropna().astype(str).unique())
    add("symbol_unique", unique_symbols == [expected_symbol], unique_symbols, [expected_symbol])
    timezone_ok = times.notna().all() and str(times.dt.tz) == "UTC"
    add("utc_consistent", timezone_ok, f"invalid={int(times.isna().sum())},tz={times.dt.tz}", "invalid=0,tz=UTC")
    on_boundary = times.notna() & times.dt.minute.eq(0) & times.dt.second.eq(0) & times.dt.microsecond.eq(0)
    add("hour_boundary", bool(on_boundary.all()), int((~on_boundary).sum()), 0)
    duplicates = int(bars.duplicated(["symbol", "exchange", "interval", "trade_time"]).sum())
    add("primary_key_unique", duplicates == 0, duplicates, 0)
    diffs = times.diff().dropna()
    strictly_increasing = bool(diffs.gt(pd.Timedelta(0)).all())
    add("time_strictly_increasing", strictly_increasing, int((~diffs.gt(pd.Timedelta(0))).sum()), 0)
    gaps = int(diffs.ne(expected_delta).sum())
    add("time_continuity", gaps == 0, gaps, 0, "24/7 bars must not use an equity trading calendar")
    numeric_columns = ["open", "high", "low", "close", "volume", "quote_volume"]
    numeric = bars[numeric_columns].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    add("numeric_finite", bool(finite.all()), int((~finite).sum()), 0)
    ohlc = (
        numeric["high"].ge(numeric[["open", "close", "low"]].max(axis=1))
        & numeric["low"].le(numeric[["open", "close", "high"]].min(axis=1))
        & numeric[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & pd.Series(finite, index=numeric.index)
    )
    add("ohlc_reasonable", bool(ohlc.all()), int((~ohlc).sum()), 0)
    volumes = numeric[["volume", "quote_volume"]]
    negative = int(volumes.lt(0).sum().sum())
    add("volume_non_negative", negative == 0, negative, 0)
    end_exclusive = pd.Timestamp(expected_end_exclusive) if expected_end_exclusive is not None else pd.Timestamp(as_of_date).normalize() + pd.Timedelta(days=1)
    end_exclusive = end_exclusive.tz_localize("UTC") if end_exclusive.tzinfo is None else end_exclusive.tz_convert("UTC")
    future = int(times.ge(end_exclusive).sum())
    add("no_future_data", future == 0, future, 0)
    if expected_start is not None:
        start = pd.Timestamp(expected_start)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        before = int(times.lt(start).sum())
        after = int(times.ge(end_exclusive).sum())
        add("configured_time_range", before == 0 and after == 0 and (bars.empty or (times.iloc[0] == start and times.iloc[-1] == end_exclusive - expected_delta)), f"before={before},after={after},min={times.min()},max={times.max()}", f"[{start},{end_exclusive})")
        expected_count = int((end_exclusive - start) / expected_delta)
        add("expected_bar_count", len(bars) == expected_count, len(bars), expected_count)
    run_values = sorted(bars["run_id"].dropna().astype(str).unique())
    add("run_consistent", run_values == [run_id], run_values, [run_id])
    weekend = times.dt.dayofweek.ge(5)
    add("weekend_trading_supported", bool(weekend.any()), int(weekend.sum()), ">0")
    if interval == "1h":
        counts = times.groupby(times.dt.floor("D")).nunique()
        complete_days = int(counts.eq(24).sum())
        add("twenty_four_hour_coverage", complete_days > 0, complete_days, ">0 complete UTC days")
    else:
        add("twenty_four_hour_coverage", True, "daily UTC bars", "daily UTC bars")
    identity_expectations = {
        "requested_instrument": "ETH-USDT", "raw_instrument": "ETH-USDT",
        "normalized_instrument": "ETHUSDT", "data_provider": "okx_public_api",
        "raw_exchange": "OKX", "normalized_exchange": "OKX",
        "instrument_type": "spot", "bar_interval": "1h",
        "symbol": "ETHUSDT", "exchange": "OKX", "market": "spot",
        "interval": "1h", "source": "okx_public_api",
    }
    identity_failures = 0
    for column, expected in identity_expectations.items():
        if column not in bars or bars[column].isna().any() or not bars[column].astype(str).eq(expected).all():
            identity_failures += 1
    add("identity_invariants", identity_failures == 0, identity_failures, 0)
    confirmed = bars.get("confirmed", pd.Series(False, index=bars.index)).astype("string").str.lower()
    add("completed_candles", bool(confirmed.isin({"1", "true"}).all()), int((~confirmed.isin({"1", "true"})).sum()), 0)
    local = pd.to_datetime(bars.get("local_trade_time"), errors="coerce", utc=True)
    add("local_utc_round_trip", bool(local.notna().all() and local.eq(times).all()), int((~local.eq(times)).sum()), 0)
    return pd.DataFrame(rows)
