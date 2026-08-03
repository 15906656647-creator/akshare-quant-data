"""Network-isolated adapters for crypto capability and historical OHLCV."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


@dataclass(frozen=True)
class CryptoCapability:
    status: str
    exact_match: bool
    eth_matches: tuple[str, ...]
    source: str


def assess_akshare_crypto_spot(frame: pd.DataFrame, requested_pair: str = "ETHUSDT") -> CryptoCapability:
    """Assess exact-pair support without renaming a different ETH market."""
    normalized: set[str] = set()
    for value in frame.astype("string").fillna("").to_numpy().ravel():
        token = "".join(ch for ch in str(value).upper() if ch.isalnum())
        if "ETH" in token:
            normalized.add(token)
    exact = requested_pair.upper() in normalized
    status = "success" if exact else ("partial_success" if normalized else "unsupported")
    return CryptoCapability(status, exact, tuple(sorted(normalized)), "AKShare.crypto_js_spot")


class AkshareCryptoSpotAdapter:
    def fetch(self) -> tuple[pd.DataFrame, CryptoCapability]:
        import akshare as ak

        frame = getattr(ak, "crypto_js_spot")()
        return frame, assess_akshare_crypto_spot(frame)


class BinancePublicKlineAdapter:
    """Minimal public Binance REST adapter; all HTTP stays in adapters/."""

    endpoint = "https://api.binance.com/api/v3/klines"

    def fetch(
        self, *, symbol: str, interval: str, start_time: datetime,
        end_time: datetime, limit: int = 1000, timeout: float = 20.0,
    ) -> pd.DataFrame:
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware")
        params = {
            "symbol": symbol.upper(), "interval": interval,
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000), "limit": int(limit),
        }
        request = Request(f"{self.endpoint}?{urlencode(params)}", headers={"User-Agent": "akshare-data-test-stage11/1.0"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS endpoint
            payload: list[list[Any]] = json.loads(response.read().decode("utf-8"))
        columns = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trade_count", "taker_base_volume",
            "taker_quote_volume", "ignore",
        ]
        frame = pd.DataFrame(payload, columns=columns)
        if frame.empty:
            return frame
        frame["trade_time"] = pd.to_datetime(frame.pop("open_time"), unit="ms", utc=True)
        frame["raw_instrument"] = symbol.upper()
        frame["data_provider"] = "binance_public_api"
        frame["raw_exchange"] = "BINANCE"
        frame["instrument_type"] = "spot"
        frame["bar_interval"] = interval
        frame["confirmed"] = True
        return frame[[
            "raw_instrument", "data_provider", "raw_exchange", "instrument_type",
            "bar_interval", "confirmed", "trade_time", "open", "high", "low",
            "close", "volume", "quote_volume",
        ]]


class OkxPublicKlineAdapter:
    """Public OKX history adapter for the exact ETH-USDT spot instrument."""

    endpoint = "https://www.okx.com/api/v5/market/history-candles"

    def fetch(
        self, *, symbol: str, interval: str, start_time: datetime,
        end_time: datetime, limit: int = 100, timeout: float = 20.0,
    ) -> pd.DataFrame:
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware")
        if symbol.upper() not in {"ETHUSDT", "ETH-USDT"}:
            raise ValueError("OKX Stage 11 adapter only permits exact ETH-USDT")
        instrument = "ETH-USDT"
        bar = {"1h": "1H", "1d": "1Dutc"}.get(interval)
        if bar is None:
            raise ValueError("OKX adapter supports 1h and 1d")
        start_ms, cursor = int(start_time.timestamp() * 1000), int(end_time.timestamp() * 1000)
        records: list[list[Any]] = []
        while cursor >= start_ms and len(records) < 10000:
            params = {"instId": instrument, "bar": bar, "after": str(cursor), "limit": str(min(int(limit), 100))}
            request = Request(f"{self.endpoint}?{urlencode(params)}", headers={"User-Agent": "akshare-data-test-stage11/1.0"})
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS endpoint
                payload = json.loads(response.read().decode("utf-8"))
            if str(payload.get("code")) != "0":
                raise RuntimeError(f"OKX history request failed: {payload.get('code')} {payload.get('msg')}")
            page = payload.get("data") or []
            if not page:
                break
            records.extend(page)
            oldest = min(int(row[0]) for row in page)
            if oldest >= cursor:
                break
            cursor = oldest
        columns = ["open_time", "open", "high", "low", "close", "volume", "volume_currency", "quote_volume", "confirmed"]
        frame = pd.DataFrame(records, columns=columns)
        if frame.empty:
            return frame
        frame["trade_time"] = pd.to_datetime(frame.pop("open_time").astype("int64"), unit="ms", utc=True)
        frame = frame.loc[(frame["trade_time"] >= pd.Timestamp(start_time)) & (frame["trade_time"] < pd.Timestamp(end_time))]
        frame = frame.loc[frame["confirmed"].astype(str).eq("1")].drop_duplicates("trade_time")
        frame["raw_instrument"] = instrument
        frame["data_provider"] = "okx_public_api"
        frame["raw_exchange"] = "OKX"
        frame["instrument_type"] = "spot"
        frame["bar_interval"] = interval
        return frame[[
            "raw_instrument", "data_provider", "raw_exchange", "instrument_type",
            "bar_interval", "confirmed", "trade_time", "open", "high", "low",
            "close", "volume", "quote_volume",
        ]].sort_values("trade_time", kind="mergesort").reset_index(drop=True)
