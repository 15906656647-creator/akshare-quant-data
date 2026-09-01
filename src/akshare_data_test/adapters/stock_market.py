"""Network boundary for Stage 3 stock-market data."""
from __future__ import annotations

import time
import threading
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
    max_retry_delay_seconds: float | None = None,
    sleeper: Callable[[float], None] = time.sleep,
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
            base_delay = max(0.0, retry_delay_seconds)
            maximum = base_delay if max_retry_delay_seconds is None else max(
                base_delay, max_retry_delay_seconds
            )
            sleeper(min(maximum, base_delay * (2 ** (attempt - 1))))
    raise AssertionError("retry loop exhausted unexpectedly")
_REQUESTS_TIMEOUT_LOCK = threading.Lock()


def _call_with_default_http_timeout(
    function: Callable[..., Any], *, parameters: dict[str, Any], timeout: float,
) -> Any:
    """Apply a bounded default timeout to AKShare functions without timeout args.

    Stage 17 executes source calls sequentially. The lock makes the temporary
    HTTP getter wrapper deterministic if an adapter is accidentally used by
    more than one Stage 17 worker.
    """
    import requests

    original_get = getattr(requests, "get")

    def timed_get(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", timeout)
        return original_get(*args, **kwargs)

    with _REQUESTS_TIMEOUT_LOCK:
        setattr(requests, "get", timed_get)
        try:
            return function(**parameters)
        finally:
            setattr(requests, "get", original_get)

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
