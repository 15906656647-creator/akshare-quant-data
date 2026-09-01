"""Network-isolated AKShare adapter for Stage 17 Hong Kong equities."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pandas as pd

from .stock_market import (
    MarketCall, _call_with_default_http_timeout, _call_with_retry,
)


def hk_source_symbol(symbol: str) -> str:
    canonical = str(symbol).upper()
    if not canonical.endswith(".HK"):
        raise ValueError("Hong Kong canonical symbols must end with .HK")
    source = canonical[:-3]
    if len(source) != 5 or not source.isdigit():
        raise ValueError("Hong Kong canonical symbols must contain five digits")
    return source


class HkMarketAdapter:
    """Only network boundary for the Stage 17 Hong Kong market calls."""

    def __init__(
        self, *, max_attempts: int = 3, retry_delay_seconds: float = 2.0,
        max_retry_delay_seconds: float = 8.0,
        request_timeout_seconds: float = 20.0,
        sleeper: Callable[[float], None] = time.sleep,
        ak_module: Any | None = None,
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

    def _call(self, name: str, parameters: dict[str, Any]) -> MarketCall:
        function = getattr(self.ak, name)

        def bounded_call(**kwargs: Any) -> Any:
            return _call_with_default_http_timeout(
                function, parameters=kwargs, timeout=self.request_timeout_seconds,
            )

        return _call_with_retry(
            bounded_call, parameters=parameters,
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
            max_retry_delay_seconds=self.max_retry_delay_seconds,
            sleeper=self.sleeper,
        )

    def fetch_history(
        self, *, symbol: str, start_date: str, end_date: str, adjust: str,
    ) -> MarketCall:
        return self._call("stock_hk_hist", {
            "symbol": hk_source_symbol(symbol), "period": "daily",
            "start_date": start_date, "end_date": end_date, "adjust": adjust,
        })

    def fetch_history_fallback(
        self, *, symbol: str, start_date: str, end_date: str, adjust: str,
    ) -> MarketCall:
        call = self._call("stock_hk_daily", {
            "symbol": hk_source_symbol(symbol), "adjust": adjust,
        })
        if call.status != "success" or call.dataframe is None:
            return call
        columns = {str(column).strip().casefold(): column for column in call.dataframe.columns}
        date_column = next(
            (columns[name] for name in ("date", "日期", "trade_date") if name.casefold() in columns),
            None,
        )
        if date_column is None:
            return MarketCall(
                None, call.attempt_count, "failed", "unexpected_schema",
                "stock_hk_daily returned no date column",
            )
        dates = pd.to_datetime(call.dataframe[date_column], errors="coerce")
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        filtered = call.dataframe.loc[dates.between(start, end)].reset_index(drop=True)
        if filtered.empty:
            return MarketCall(
                filtered, call.attempt_count, "empty", "empty_result",
                "stock_hk_daily returned no rows in the requested date range",
            )
        return MarketCall(filtered, call.attempt_count, "success")

    def fetch_profile(self, *, symbol: str) -> MarketCall:
        return self._call(
            "stock_hk_security_profile_em", {"symbol": hk_source_symbol(symbol)}
        )

    def fetch_minutes(
        self, *, symbol: str, start_date: str, end_date: str, interval: str,
    ) -> MarketCall:
        period = {"1m": "1", "5m": "5"}.get(interval)
        if period is None:
            return MarketCall(
                None, 0, "unsupported", "unsupported_interval",
                f"Hong Kong AKShare minute interface does not directly support {interval}",
            )
        return self._call("stock_hk_hist_min_em", {
            "symbol": hk_source_symbol(symbol), "period": period,
            "adjust": "", "start_date": start_date, "end_date": end_date,
        })
