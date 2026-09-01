"""Network boundary for Stage 18.1 fundamental capability calls."""
from __future__ import annotations

import importlib
import inspect
from typing import Any

from .stock_finance import FinancialCall, call_with_retry


class Stage18FundamentalAdapter:
    def __init__(self, ak_module: Any | None = None) -> None:
        self._ak = ak_module or importlib.import_module("akshare")

    @property
    def akshare_version(self) -> str:
        return str(getattr(self._ak, "__version__", "unknown"))

    def inspect_function(self, name: str) -> tuple[bool, str]:
        function = getattr(self._ak, name, None)
        if not callable(function):
            return False, ""
        try:
            return True, str(inspect.signature(function))
        except (TypeError, ValueError):
            return True, "<unavailable>"

    def call(
        self,
        name: str,
        parameters: dict[str, Any],
        *,
        max_attempts: int,
        retry_delay_seconds: float,
    ) -> FinancialCall:
        function = getattr(self._ak, name, None)
        if not callable(function):
            return FinancialCall(
                None, 0, "unavailable", "function_missing",
                f"Function {name!r} not found in installed akshare",
            )
        return call_with_retry(
            function,
            parameters,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
