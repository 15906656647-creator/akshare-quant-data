"""Network-isolated A-share adapter for Stage 17."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .stock_market import (
    MarketCall, _call_with_default_http_timeout, _call_with_retry,
)


def a_sina_symbol(symbol: str) -> str:
    canonical = str(symbol)
    if len(canonical) != 6 or not canonical.isdigit():
        raise ValueError("A-share canonical symbols must contain six digits")
    if canonical.startswith(("600", "601", "603")):
        return f"sh{canonical}"
    if canonical.startswith(("000", "002", "300")):
        return f"sz{canonical}"
    raise ValueError(f"Unsupported Stage 17 A-share exchange mapping: {canonical}")


class Stage17AShareAdapter:
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
        return self._call("stock_zh_a_hist", {
            "symbol": symbol, "period": "daily", "start_date": start_date,
            "end_date": end_date, "adjust": adjust,
            "timeout": self.request_timeout_seconds,
        })

    def fetch_history_fallback(
        self, *, symbol: str, start_date: str, end_date: str, adjust: str,
    ) -> MarketCall:
        return self._call("stock_zh_a_daily", {
            "symbol": a_sina_symbol(symbol), "start_date": start_date,
            "end_date": end_date, "adjust": adjust,
        })

    def fetch_profile(self, *, symbol: str) -> MarketCall:
        return self._call("stock_profile_cninfo", {"symbol": symbol})

    def fetch_minutes(
        self, *, symbol: str, start_date: str, end_date: str, interval: str,
    ) -> MarketCall:
        period = {"1m": "1", "5m": "5"}.get(interval)
        if period is None:
            return MarketCall(
                None, 0, "unsupported", "unsupported_interval",
                f"A-share AKShare minute interface does not directly support {interval}",
            )
        return self._call("stock_zh_a_hist_min_em", {
            "symbol": symbol, "start_date": start_date, "end_date": end_date,
            "period": period, "adjust": "",
        })
