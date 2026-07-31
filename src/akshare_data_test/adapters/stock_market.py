"""Network boundary for Stage 3 stock-market data."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .akshare_probe import _sanitize_message


@dataclass
class MarketCall:
    """Result of one logical market-data call."""

    dataframe: pd.DataFrame | None
    attempt_count: int
    status: str
    error_type: str = ""
    error_message: str = ""


def classify_market_error(exc: BaseException) -> tuple[str, bool]:
    """Return a stable error type and whether the failure is transient."""
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if isinstance(exc, (TypeError, ValueError, AttributeError)):
        return "parameter_error", False
    if "timeout" in name or "timed out" in message:
        return "timeout", True
    if "rate" in message and "limit" in message:
        return "rate_limit", True
    if any(token in name or token in message for token in ("connection", "ssl", "proxy", "dns")):
        return "connection_error", True
    return "upstream_error", False


def _call_with_retry(
    function: Callable[..., Any],
    *,
    parameters: dict[str, Any],
    max_attempts: int,
    retry_delay_seconds: float,
) -> MarketCall:
    attempts = max(1, min(int(max_attempts), 3))
    for attempt in range(1, attempts + 1):
        try:
            frame = function(**parameters)
            if not isinstance(frame, pd.DataFrame):
                return MarketCall(
                    None,
                    attempt,
                    "failed",
                    "unexpected_return_type",
                    f"Returned {type(frame).__name__}, expected DataFrame",
                )
            if frame.empty:
                return MarketCall(
                    frame, attempt, "empty", "empty_result", "Returned empty DataFrame"
                )
            return MarketCall(frame, attempt, "success")
        except Exception as exc:  # network libraries expose heterogeneous errors
            error_type, transient = classify_market_error(exc)
            if not transient or attempt >= attempts:
                return MarketCall(
                    None,
                    attempt,
                    "failed",
                    error_type,
                    _sanitize_message(exc),
                )
            time.sleep(max(0.0, retry_delay_seconds))
    raise AssertionError("retry loop exhausted unexpectedly")


class StockMarketAdapter:
    """Only class allowed to call the two AKShare interfaces used in Stage 3."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 2.0,
        ak_module: Any | None = None,
    ) -> None:
        if ak_module is None:
            import akshare as ak_module

        self.ak = ak_module
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds

    @property
    def akshare_version(self) -> str:
        return str(getattr(self.ak, "__version__", "unknown"))

    def fetch_history(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> MarketCall:
        return _call_with_retry(
            getattr(self.ak, "stock_zh_a_hist"),
            parameters={
                "symbol": symbol,
                "period": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
            },
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
        )

    def fetch_spot(self) -> MarketCall:
        return _call_with_retry(
            getattr(self.ak, "stock_zh_a_spot_em"),
            parameters={},
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
        )
