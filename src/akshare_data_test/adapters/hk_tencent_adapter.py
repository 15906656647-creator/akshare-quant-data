"""Network-isolated Tencent Hong Kong daily-history adapter for Stage 17."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .hk_market import hk_source_symbol
from .stock_market import MarketCall, _call_with_default_http_timeout, _call_with_retry


TENCENT_COLUMNS = {
    "date": ("日期", "date", "trade_date"),
    "open": ("开盘", "open"),
    "close": ("收盘", "close"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "volume": ("成交量", "volume"),
}


@dataclass(frozen=True)
class TencentHistoryCall:
    source_frame: pd.DataFrame | None
    dataframe: pd.DataFrame | None
    attempt_count: int
    status: str
    error_type: str = ""
    error_message: str = ""
    requested_blocks: tuple[int, ...] = ()
    duplicate_rows_removed: int = 0


def tencent_year_blocks(listing_date: date, as_of_date: date) -> tuple[int, ...]:
    if listing_date > as_of_date:
        raise ValueError("listing_date cannot be after as_of_date")
    return tuple(range(listing_date.year, as_of_date.year + 1, 2))


def normalize_tencent_history(
    frame: pd.DataFrame, *, start_date: date, as_of_date: date,
) -> tuple[pd.DataFrame, int]:
    columns = {str(column).strip().casefold(): column for column in frame.columns}
    resolved: dict[str, Any] = {}
    for field, aliases in TENCENT_COLUMNS.items():
        found = next(
            (columns[alias.casefold()] for alias in aliases if alias.casefold() in columns),
            None,
        )
        if found is None:
            raise ValueError(f"stock_zh_ah_daily missing required column: {field}")
        resolved[field] = found
    normalized = frame[[resolved[field] for field in TENCENT_COLUMNS]].rename(
        columns={resolved[field]: field for field in TENCENT_COLUMNS}
    ).copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    if normalized["date"].isna().any():
        raise ValueError("stock_zh_ah_daily returned invalid dates")
    for field in ("open", "high", "low", "close", "volume"):
        normalized[field] = pd.to_numeric(normalized[field], errors="coerce")
    if normalized[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError("stock_zh_ah_daily returned nonnumeric OHLCV")
    normalized = normalized.loc[
        normalized["date"].between(pd.Timestamp(start_date), pd.Timestamp(as_of_date))
    ].copy()
    normalized.sort_values("date", inplace=True, kind="stable")
    duplicate_mask = normalized.duplicated(subset=["date"], keep=False)
    duplicate_rows_removed = 0
    if duplicate_mask.any():
        for _, group in normalized.loc[duplicate_mask].groupby("date", sort=False):
            if len(group.drop_duplicates()) != 1:
                raise ValueError("stock_zh_ah_daily returned conflicting duplicate dates")
        before = len(normalized)
        normalized.drop_duplicates(subset=["date"], keep="first", inplace=True)
        duplicate_rows_removed = before - len(normalized)
    normalized["date"] = normalized["date"].dt.date
    normalized.reset_index(drop=True, inplace=True)
    return normalized, duplicate_rows_removed


class HkTencentAdapter:
    """Tencent candidate kept separate from Eastmoney and Sina adapters."""

    def __init__(
        self, *, max_attempts: int = 3, retry_delay_seconds: float = 2.0,
        max_retry_delay_seconds: float = 8.0, request_timeout_seconds: float = 20.0,
        sleeper: Callable[[float], None] = time.sleep, ak_module: Any | None = None,
    ) -> None:
        if ak_module is None:
            import akshare as ak_module
        self.ak = ak_module
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.sleeper = sleeper

    @property
    def akshare_version(self) -> str:
        return str(getattr(self.ak, "__version__", "unknown"))

    def _fetch_block(self, *, symbol: str, year: int, adjust: str) -> MarketCall:
        function = getattr(self.ak, "stock_zh_ah_daily")

        def bounded_call(**kwargs: Any) -> Any:
            return _call_with_default_http_timeout(
                function, parameters=kwargs, timeout=self.request_timeout_seconds,
            )

        return _call_with_retry(
            bounded_call,
            parameters={
                "symbol": hk_source_symbol(symbol),
                "start_year": str(year),
                # AKShare uses an exclusive range and each iteration asks Tencent
                # for that year plus the following year. One iteration therefore
                # forms a non-overlapping two-calendar-year request block.
                "end_year": str(year + 1),
                "adjust": "" if adjust == "raw" else adjust,
            },
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
            max_retry_delay_seconds=self.max_retry_delay_seconds,
            sleeper=self.sleeper,
        )

    def fetch_history(
        self, *, symbol: str, listing_date: date, as_of_date: date, adjust: str,
    ) -> TencentHistoryCall:
        if adjust not in {"raw", "qfq", "hfq"}:
            raise ValueError("Tencent adjust must be raw, qfq, or hfq")
        blocks = tencent_year_blocks(listing_date, as_of_date)
        source_frames: list[pd.DataFrame] = []
        attempts = 0
        for year in blocks:
            call = self._fetch_block(symbol=symbol, year=year, adjust=adjust)
            attempts += call.attempt_count
            if call.status != "success" or call.dataframe is None:
                return TencentHistoryCall(
                    pd.concat(source_frames, ignore_index=True) if source_frames else None,
                    None, attempts, call.status, call.error_type, call.error_message,
                    blocks,
                )
            source_frames.append(call.dataframe.copy())
        source = pd.concat(source_frames, ignore_index=True)
        try:
            normalized, removed = normalize_tencent_history(
                source, start_date=listing_date, as_of_date=as_of_date,
            )
        except ValueError as exc:
            return TencentHistoryCall(
                source, None, attempts, "failed", "normalization_error", str(exc), blocks,
            )
        if normalized.empty:
            return TencentHistoryCall(
                source, normalized, attempts, "empty", "empty_result",
                "No Tencent rows remained in the verified listing/as-of interval", blocks,
                removed,
            )
        return TencentHistoryCall(
            source, normalized, attempts, "success", requested_blocks=blocks,
            duplicate_rows_removed=removed,
        )
