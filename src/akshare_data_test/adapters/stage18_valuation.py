"""Network boundary for Stage 18.1.2 valuation-provider capability calls."""
from __future__ import annotations

import importlib
import inspect
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import pandas as pd

from .akshare_probe import _sanitize_message
from .stock_market import classify_market_error


_HTTP_PATCH_LOCK = Lock()


@dataclass(frozen=True)
class AttemptEvidence:
    attempt: int
    started_at: str
    finished_at: str
    duration_ms: float
    status: str
    error_type: str
    error_message: str


@dataclass(frozen=True)
class ValuationCall:
    dataframe: pd.DataFrame | None
    status: str
    error_type: str
    error_message: str
    attempts: tuple[AttemptEvidence, ...]

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def _call_with_timeout(function: Any, parameters: dict[str, Any], timeout: float) -> Any:
    request_client = getattr(function, "__globals__", {}).get("requests")
    original_get = getattr(request_client, "get", None)
    if original_get is None:
        return function(**parameters)

    def timed_get(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", timeout)
        return original_get(*args, **kwargs)

    with _HTTP_PATCH_LOCK:
        setattr(request_client, "get", timed_get)
        try:
            return function(**parameters)
        finally:
            setattr(request_client, "get", original_get)


class Stage18ValuationAdapter:
    def __init__(self, ak_module: Any | None = None) -> None:
        self._ak = ak_module or importlib.import_module("akshare")

    @property
    def akshare_version(self) -> str:
        return str(getattr(self._ak, "__version__", "unknown"))

    def inspect_function(self, name: str) -> tuple[bool, str, str, str]:
        function = getattr(self._ak, name, None)
        if not callable(function):
            return False, "", "", ""
        try:
            signature = str(inspect.signature(function))
        except (TypeError, ValueError):
            signature = "<unavailable>"
        return (
            True, signature, str(getattr(function, "__module__", "")),
            str(inspect.getsourcefile(function) or ""),
        )

    def discover(self, keywords: tuple[str, ...]) -> list[dict[str, str]]:
        rows = []
        for name in sorted(dir(self._ak)):
            if name.startswith("_") or not callable(getattr(self._ak, name, None)):
                continue
            lowered = name.casefold()
            if not any(keyword in lowered for keyword in keywords):
                continue
            exists, signature, module, source_file = self.inspect_function(name)
            if exists:
                rows.append({
                    "interface": name, "signature": signature,
                    "module": module, "source_file": source_file,
                })
        return rows

    def call(
        self, name: str, parameters: dict[str, Any], *, max_attempts: int,
        retry_delay_seconds: float, timeout_seconds: float,
    ) -> ValuationCall:
        function = getattr(self._ak, name, None)
        if not callable(function):
            return ValuationCall(None, "unavailable", "function_missing", f"Function {name!r} is unavailable", ())
        attempts = []
        for attempt in range(1, min(max(1, int(max_attempts)), 3) + 1):
            started = datetime.now(timezone.utc)
            began = time.perf_counter()
            try:
                value = _call_with_timeout(function, parameters, timeout_seconds)
                finished = datetime.now(timezone.utc)
                if not isinstance(value, pd.DataFrame):
                    attempts.append(AttemptEvidence(
                        attempt, started.isoformat(), finished.isoformat(),
                        round((time.perf_counter() - began) * 1000, 3), "failed",
                        "unexpected_return_type", f"Returned {type(value).__name__}, expected DataFrame",
                    ))
                    return ValuationCall(None, "failed", "unexpected_return_type", attempts[-1].error_message, tuple(attempts))
                status = "empty" if value.empty else "success"
                error_type = "empty_result" if value.empty else ""
                message = "Returned empty DataFrame" if value.empty else ""
                attempts.append(AttemptEvidence(
                    attempt, started.isoformat(), finished.isoformat(),
                    round((time.perf_counter() - began) * 1000, 3), status, error_type, message,
                ))
                return ValuationCall(value, status, error_type, message, tuple(attempts))
            except Exception as exc:
                finished = datetime.now(timezone.utc)
                error_type, transient = classify_market_error(exc)
                attempts.append(AttemptEvidence(
                    attempt, started.isoformat(), finished.isoformat(),
                    round((time.perf_counter() - began) * 1000, 3), "failed", error_type,
                    _sanitize_message(exc)[:500],
                ))
                if not transient or attempt >= max_attempts:
                    return ValuationCall(None, "failed", error_type, attempts[-1].error_message, tuple(attempts))
                time.sleep(max(0.0, retry_delay_seconds) * (2 ** (attempt - 1)))
        raise AssertionError("Stage 18.1.2 retry loop exhausted")
