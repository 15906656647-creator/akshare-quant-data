"""Paginated and retrying OKX adapter dedicated to Stage 17 Raw collection."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


OKX_BAR_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "1h": "1H", "1d": "1Dutc",
}


def _default_request_json(url: str, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "akshare-data-test-stage17/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS endpoint
        return json.loads(response.read().decode("utf-8"))


class Stage17OkxAdapter:
    endpoint = "https://www.okx.com/api/v5/market/history-candles"

    def __init__(
        self, *, max_attempts: int = 3, retry_delay_seconds: float = 1.0,
        inter_request_delay_seconds: float = 0.15,
        request_json: Callable[[str, float], dict[str, Any]] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_attempts = max(1, min(int(max_attempts), 3))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.inter_request_delay_seconds = max(0.0, float(inter_request_delay_seconds))
        self.request_json = request_json or _default_request_json
        self.sleeper = sleeper

    def _page(self, url: str, timeout: float) -> dict[str, Any]:
        last: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = self.request_json(url, timeout)
                if str(payload.get("code")) != "0":
                    raise RuntimeError(
                        f"OKX history request failed: {payload.get('code')} {payload.get('msg')}"
                    )
                return payload
            except Exception as exc:  # heterogeneous HTTP failures
                last = exc
                if attempt < self.max_attempts:
                    self.sleeper(self.retry_delay_seconds * (2 ** (attempt - 1)))
        assert last is not None
        raise last

    def fetch(
        self, *, symbol: str, interval: str, start_time: datetime,
        end_time: datetime, limit: int = 300, timeout: float = 20.0,
    ) -> pd.DataFrame:
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware")
        if start_time >= end_time:
            raise ValueError("start_time must be earlier than end_time")
        if symbol.upper() not in {"ETHUSDT", "ETH-USDT"}:
            raise ValueError("Stage 17 OKX adapter only permits exact ETH-USDT spot")
        bar = OKX_BAR_MAP.get(interval)
        if bar is None:
            raise ValueError(f"Unsupported Stage 17 OKX interval: {interval}")
        page_limit = max(1, min(int(limit), 300))
        start_ms = int(start_time.timestamp() * 1000)
        cursor = int(end_time.timestamp() * 1000)
        records: list[list[Any]] = []
        seen_cursors: set[int] = set()
        while cursor >= start_ms:
            if cursor in seen_cursors:
                raise RuntimeError("OKX pagination cursor did not advance")
            seen_cursors.add(cursor)
            params = {
                "instId": "ETH-USDT", "bar": bar, "after": str(cursor),
                "limit": str(page_limit),
            }
            payload = self._page(f"{self.endpoint}?{urlencode(params)}", timeout)
            page = payload.get("data") or []
            if not page:
                break
            records.extend(page)
            oldest = min(int(row[0]) for row in page)
            if oldest < start_ms or len(page) < page_limit:
                break
            if oldest >= cursor:
                raise RuntimeError("OKX pagination returned a non-decreasing cursor")
            cursor = oldest
            self.sleeper(self.inter_request_delay_seconds)
        columns = [
            "open_time", "open", "high", "low", "close", "volume",
            "volume_currency", "quote_volume", "confirmed",
        ]
        frame = pd.DataFrame(records, columns=columns)
        if frame.empty:
            return frame
        frame["trade_time"] = pd.to_datetime(
            frame.pop("open_time").astype("int64"), unit="ms", utc=True,
        )
        lower, upper = pd.Timestamp(start_time), pd.Timestamp(end_time)
        frame = frame.loc[(frame.trade_time >= lower) & (frame.trade_time < upper)]
        frame = frame.loc[frame["confirmed"].astype(str).eq("1")]
        frame = frame.drop_duplicates("trade_time", keep="last")
        frame["confirmed"] = True
        frame["raw_instrument"] = "ETH-USDT"
        frame["data_provider"] = "okx_public_api"
        frame["raw_exchange"] = "OKX"
        frame["instrument_type"] = "spot"
        frame["bar_interval"] = interval
        return frame[[
            "raw_instrument", "data_provider", "raw_exchange", "instrument_type",
            "bar_interval", "confirmed", "trade_time", "open", "high", "low",
            "close", "volume", "quote_volume",
        ]].sort_values("trade_time", kind="mergesort").reset_index(drop=True)
