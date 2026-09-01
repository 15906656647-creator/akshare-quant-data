"""Network-isolated external Hong Kong history adapters for Stage 17 remediation."""
from __future__ import annotations

import json
import time
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ExternalHistoryCall:
    raw_response: bytes | None
    dataframe: pd.DataFrame | None
    attempt_count: int
    status: str
    error_type: str = ""
    error_message: str = ""
    provider_symbol: str = ""
    response_url: str = ""
    provider_timezone: str = ""


def yahoo_hk_symbol(symbol: str) -> str:
    canonical = str(symbol).upper()
    if not canonical.endswith(".HK"):
        raise ValueError("Yahoo Hong Kong symbols must use the canonical .HK suffix")
    digits = canonical[:-3]
    if len(digits) != 5 or not digits.isdigit():
        raise ValueError("Canonical Hong Kong symbols must contain five digits")
    return f"{int(digits)}.HK"


def normalize_yahoo_chart(payload: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("Yahoo response has no chart object")
    if chart.get("error"):
        raise ValueError(f"Yahoo chart error: {chart['error']}")
    results = chart.get("result")
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError("Yahoo response must contain exactly one chart result")
    result = results[0]
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    adjclose = indicators.get("adjclose") if isinstance(indicators, dict) else None
    if not isinstance(timestamps, list) or not isinstance(quotes, list) or len(quotes) != 1:
        raise ValueError("Yahoo response is missing timestamp or quote arrays")
    quote = quotes[0]
    adjusted = adjclose[0].get("adjclose") if isinstance(adjclose, list) and len(adjclose) == 1 else None
    required = {name: quote.get(name) for name in ("open", "high", "low", "close", "volume")}
    lengths = {len(timestamps)}
    for values in (*required.values(), adjusted):
        if not isinstance(values, list):
            raise ValueError("Yahoo response is missing an OHLCV or adjusted-close array")
        lengths.add(len(values))
    if len(lengths) != 1:
        raise ValueError("Yahoo response arrays have inconsistent lengths")
    provider_timezone = str(result.get("meta", {}).get("exchangeTimezoneName") or "")
    datetimes = pd.to_datetime(pd.Series(timestamps), unit="s", utc=True, errors="coerce")
    if datetimes.isna().any():
        raise ValueError("Yahoo response contains invalid timestamps")
    if provider_timezone:
        try:
            datetimes = datetimes.dt.tz_convert(provider_timezone)
        except Exception as exc:
            raise ValueError(f"Yahoo returned invalid exchange timezone: {provider_timezone}") from exc
    frame = pd.DataFrame({
        "date": datetimes.dt.date,
        "open": required["open"],
        "high": required["high"],
        "low": required["low"],
        "close": required["close"],
        "adj_close": adjusted,
        "volume": required["volume"],
    })
    return frame, provider_timezone


class YahooHkAdapter:
    """Fetch Yahoo's provider-native raw OHLC and adjusted-close series."""

    endpoint = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def __init__(
        self, *, max_attempts: int = 3, retry_delay_seconds: float = 2.0,
        max_retry_delay_seconds: float = 8.0, request_timeout_seconds: float = 20.0,
        sleeper: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.sleeper = sleeper
        self.opener = opener

    def fetch_history(
        self, *, symbol: str, listing_date: date, as_of_date: date,
    ) -> ExternalHistoryCall:
        if listing_date > as_of_date:
            raise ValueError("listing_date cannot be after as_of_date")
        provider_symbol = yahoo_hk_symbol(symbol)
        period1 = int(datetime.combine(listing_date, datetime_time.min, timezone.utc).timestamp())
        period2 = int(datetime.combine(as_of_date + timedelta(days=1), datetime_time.min, timezone.utc).timestamp())
        query = urlencode({
            "period1": period1, "period2": period2, "interval": "1d",
            "events": "div,splits,capitalGains", "includeAdjustedClose": "true",
        })
        url = f"{self.endpoint.format(symbol=quote(provider_symbol))}?{query}"
        request = Request(
            url, headers={"User-Agent": "akshare-data-test-stage17-validation/1.0"},
        )
        last_type = ""
        last_message = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self.opener(request, timeout=self.request_timeout_seconds) as response:
                    raw = response.read()
                payload = json.loads(raw.decode("utf-8"))
                frame, provider_timezone = normalize_yahoo_chart(payload)
                if frame.empty:
                    return ExternalHistoryCall(
                        raw, frame, attempt, "empty", "empty_result",
                        "Yahoo returned an empty chart", provider_symbol, url,
                        provider_timezone,
                    )
                return ExternalHistoryCall(
                    raw, frame, attempt, "success", provider_symbol=provider_symbol,
                    response_url=url, provider_timezone=provider_timezone,
                )
            except (URLError, TimeoutError, ConnectionError) as exc:
                last_type = "connection_error"
                last_message = str(exc)
                if attempt < self.max_attempts:
                    self.sleeper(min(
                        self.retry_delay_seconds * (2 ** (attempt - 1)),
                        self.max_retry_delay_seconds,
                    ))
                    continue
                return ExternalHistoryCall(
                    None, None, attempt, "failed", last_type, last_message,
                    provider_symbol, url,
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
                return ExternalHistoryCall(
                    None, None, attempt, "failed", "unexpected_schema", str(exc),
                    provider_symbol, url,
                )
        return ExternalHistoryCall(
            None, None, self.max_attempts, "failed", last_type, last_message,
            provider_symbol, url,
        )
