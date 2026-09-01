"""Direct Tencent HK daily adapter with response-key compatibility handling."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .hk_market import hk_source_symbol
from .hk_tencent_adapter import normalize_tencent_history, tencent_year_blocks


RAW_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
ADJUSTED_ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"


@dataclass(frozen=True)
class TencentDirectBlock:
    year: int
    adjust: str
    request_url: str
    request_params: dict[str, str]
    requested_key: str
    used_key: str
    field_fallback: bool
    requested_at: str
    completed_at: str
    attempt_count: int
    http_status: int | None
    raw_response: bytes | None
    source_frame: pd.DataFrame | None
    status: str
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class TencentDirectHistoryCall:
    source_frame: pd.DataFrame | None
    dataframe: pd.DataFrame | None
    blocks: tuple[TencentDirectBlock, ...]
    status: str
    duplicate_rows_removed: int = 0
    error_type: str = ""
    error_message: str = ""

    @property
    def attempt_count(self) -> int:
        return sum(block.attempt_count for block in self.blocks)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_jsonp(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8-sig", errors="strict")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Tencent response is not valid JSONP")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Tencent response root is not an object")
    return value


def _rows_to_frame(rows: Any) -> pd.DataFrame:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Tencent response contains no daily rows")
    parsed: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError("Tencent daily row schema changed")
        parsed.append(row[:6])
    return pd.DataFrame(parsed, columns=("date", "open", "close", "high", "low", "volume"))


class HkTencentDirectAdapter:
    """Fetch Tencent responses without relying on AKShare's response-key parser."""

    def __init__(
        self, *, max_attempts: int = 3, retry_delay_seconds: float = 1.0,
        max_retry_delay_seconds: float = 4.0, request_timeout_seconds: float = 20.0,
        sleeper: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.sleeper = sleeper
        self.opener = opener

    @staticmethod
    def _request(symbol: str, year: int, adjust: str) -> tuple[str, dict[str, str], str]:
        source_symbol = hk_source_symbol(symbol)
        request_adjust = "" if adjust == "raw" else adjust
        requested_key = "day" if adjust == "raw" else f"{adjust}day"
        endpoint = RAW_ENDPOINT if adjust == "raw" else ADJUSTED_ENDPOINT
        params = {
            "_var": f"kline_day{request_adjust}{year}",
            "param": (
                f"hk{source_symbol},day,{year}-01-01,{year + 1}-12-31,640,"
                f"{request_adjust}"
            ),
        }
        return endpoint, params, requested_key

    def _fetch_block(self, *, symbol: str, year: int, adjust: str) -> TencentDirectBlock:
        endpoint, params, requested_key = self._request(symbol, year, adjust)
        url = f"{endpoint}?{urlencode(params)}"
        requested_at = _utc_now()
        for attempt in range(1, self.max_attempts + 1):
            try:
                request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with self.opener(request, timeout=self.request_timeout_seconds) as response:
                    payload = response.read()
                    status_code = int(getattr(response, "status", 200))
                root = _decode_jsonp(payload)
                identity = f"hk{hk_source_symbol(symbol)}"
                data = root.get("data")
                if not isinstance(data, dict) or set(data) != {identity}:
                    raise ValueError("Tencent response identity mismatch")
                security = data[identity]
                if not isinstance(security, dict):
                    raise ValueError("Tencent security payload is not an object")
                used_key = requested_key
                fallback = False
                if requested_key not in security and adjust in {"qfq", "hfq"} and "day" in security:
                    used_key = "day"
                    fallback = True
                if used_key not in security:
                    raise ValueError(f"Tencent response missing {requested_key}")
                frame = _rows_to_frame(security[used_key])
                return TencentDirectBlock(
                    year, adjust, url, params, requested_key, used_key, fallback,
                    requested_at, _utc_now(), attempt, status_code, payload, frame, "success",
                )
            except HTTPError as exc:
                retryable = 500 <= exc.code < 600
                if not retryable or attempt == self.max_attempts:
                    return TencentDirectBlock(
                        year, adjust, url, params, requested_key, "", False,
                        requested_at, _utc_now(), attempt, exc.code, None, None, "failed",
                        "http_error", str(exc),
                    )
            except (URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.max_attempts:
                    return TencentDirectBlock(
                        year, adjust, url, params, requested_key, "", False,
                        requested_at, _utc_now(), attempt, None, None, None, "failed",
                        "connection_error", str(exc),
                    )
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                return TencentDirectBlock(
                    year, adjust, url, params, requested_key, "", False,
                    requested_at, _utc_now(), attempt, None, locals().get("payload"), None,
                    "failed", "response_error", str(exc),
                )
            delay = min(
                self.retry_delay_seconds * (2 ** (attempt - 1)),
                self.max_retry_delay_seconds,
            )
            self.sleeper(delay)
        raise AssertionError("unreachable")

    def fetch_history(
        self, *, symbol: str, listing_date: date, as_of_date: date, adjust: str,
    ) -> TencentDirectHistoryCall:
        if adjust not in {"raw", "qfq", "hfq"}:
            raise ValueError("Tencent adjust must be raw, qfq, or hfq")
        years = tencent_year_blocks(listing_date, as_of_date)
        blocks: list[TencentDirectBlock] = []
        frames: list[pd.DataFrame] = []
        for year in years:
            block = self._fetch_block(symbol=symbol, year=year, adjust=adjust)
            blocks.append(block)
            if block.status != "success" or block.source_frame is None:
                return TencentDirectHistoryCall(
                    pd.concat(frames, ignore_index=True) if frames else None,
                    None, tuple(blocks), "failed", error_type=block.error_type,
                    error_message=block.error_message,
                )
            frames.append(block.source_frame)
        source = pd.concat(frames, ignore_index=True)
        try:
            normalized, removed = normalize_tencent_history(
                source, start_date=listing_date, as_of_date=as_of_date,
            )
        except ValueError as exc:
            return TencentDirectHistoryCall(
                source, None, tuple(blocks), "failed", error_type="normalization_error",
                error_message=str(exc),
            )
        if normalized.empty:
            return TencentDirectHistoryCall(
                source, normalized, tuple(blocks), "empty", removed,
                "empty_result", "No rows remained in the fixed business interval",
            )
        return TencentDirectHistoryCall(source, normalized, tuple(blocks), "success", removed)
