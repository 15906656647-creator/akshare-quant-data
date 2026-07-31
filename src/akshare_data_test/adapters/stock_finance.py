"""Network boundary for the five allowed Stage 4 financial interfaces."""
from __future__ import annotations

import importlib
import io
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .akshare_probe import _classify_error, _error_evidence

TRANSIENT_ERRORS = {"dns_error", "connection_error", "timeout", "rate_limit"}


@dataclass
class FinancialCall:
    dataframe: pd.DataFrame | None
    attempt_count: int
    status: str
    error_type: str = ""
    error_message: str = ""
    root_exception_class: str = ""
    target_host: str = ""
    output_capture_status: str = "not_configured"
    stdout_log_path: str = ""
    stderr_log_path: str = ""


@dataclass(frozen=True)
class OutputCapture:
    """Task-local upstream output destination."""

    stdout_path: Path
    stderr_path: Path
    stdout_log_path: str
    stderr_log_path: str


class _SafeTextSink:
    """Text stream that records output failures without breaking upstream work."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.warning = False

    def write(self, value: str) -> int:
        try:
            return self.stream.write(value)
        except (OSError, ValueError, BrokenPipeError):
            self.warning = True
            return len(value)

    def flush(self) -> None:
        try:
            self.stream.flush()
        except (OSError, ValueError, BrokenPipeError):
            self.warning = True

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"


@contextmanager
def safe_upstream_output(capture: OutputCapture | None):
    """Redirect AKShare/tqdm output away from wrapper-owned console pipes."""
    if capture is None:
        yield {"status": "not_configured"}
        return
    state = {"status": "success"}
    stdout_handle = stderr_handle = None
    try:
        capture.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle = capture.stdout_path.open(
            "a", encoding="utf-8", errors="replace"
        )
        stderr_handle = capture.stderr_path.open(
            "a", encoding="utf-8", errors="replace"
        )
        stdout_sink = _SafeTextSink(stdout_handle)
        stderr_sink = _SafeTextSink(stderr_handle)
    except (OSError, ValueError):
        state["status"] = "capture_open_failed"
        stdout_sink = _SafeTextSink(io.StringIO())
        stderr_sink = _SafeTextSink(io.StringIO())
    try:
        with redirect_stdout(stdout_sink), redirect_stderr(stderr_sink):
            yield state
    finally:
        stdout_sink.flush()
        stderr_sink.flush()
        if stdout_sink.warning or stderr_sink.warning:
            state["status"] = "console_output_warning"
        for handle in (stdout_handle, stderr_handle):
            if handle is not None:
                try:
                    handle.close()
                except (OSError, ValueError):
                    state["status"] = "console_output_warning"


def call_with_retry(
    function: Callable[..., Any],
    parameters: dict[str, Any],
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
    output_capture: OutputCapture | None = None,
) -> FinancialCall:
    """Call an AKShare function with bounded, transient-only retries."""
    attempts = min(max(1, max_attempts), 3)
    for attempt in range(1, attempts + 1):
        capture_status = "not_configured"
        output_state = {"status": capture_status}
        try:
            with safe_upstream_output(output_capture) as output_state:
                value = function(**parameters)
            capture_status = output_state["status"]
            if not isinstance(value, pd.DataFrame):
                return FinancialCall(
                    None, attempt, "failed", "unexpected_return_type",
                    f"Returned {type(value).__name__}, expected DataFrame",
                    output_capture_status=capture_status,
                    stdout_log_path=(
                        output_capture.stdout_log_path if output_capture else ""
                    ),
                    stderr_log_path=(
                        output_capture.stderr_log_path if output_capture else ""
                    ),
                )
            if value.empty:
                return FinancialCall(
                    value, attempt, "empty", "empty_result",
                    "Returned empty DataFrame",
                    output_capture_status=capture_status,
                    stdout_log_path=(
                        output_capture.stdout_log_path if output_capture else ""
                    ),
                    stderr_log_path=(
                        output_capture.stderr_log_path if output_capture else ""
                    ),
                )
            return FinancialCall(
                value,
                attempt,
                "success",
                output_capture_status=capture_status,
                stdout_log_path=(
                    output_capture.stdout_log_path if output_capture else ""
                ),
                stderr_log_path=(
                    output_capture.stderr_log_path if output_capture else ""
                ),
            )
        except Exception as exc:  # upstream libraries expose heterogeneous errors
            capture_status = output_state.get("status", capture_status)
            error_type = _classify_error(exc, type(exc).__name__)
            if isinstance(exc, TypeError):
                error_type = "invalid_parameter"
            evidence = _error_evidence(exc, "")
            if error_type not in TRANSIENT_ERRORS or attempt == attempts:
                return FinancialCall(
                    None,
                    attempt,
                    "failed",
                    error_type,
                    evidence["error_message"],
                    evidence["root_exception_class"],
                    evidence["target_host"],
                    capture_status,
                    output_capture.stdout_log_path if output_capture else "",
                    output_capture.stderr_log_path if output_capture else "",
                )
            if retry_delay_seconds:
                time.sleep(retry_delay_seconds * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


class StockFinanceAdapter:
    """Adapter containing all allowed financial AKShare calls."""

    def __init__(
        self,
        ak_module: Any | None = None,
        *,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._ak = ak_module or importlib.import_module("akshare")
        self.retry_delay_seconds = retry_delay_seconds

    @property
    def akshare_version(self) -> str:
        return str(getattr(self._ak, "__version__", "unknown"))

    def _call(
        self,
        name: str,
        parameters: dict[str, Any],
        output_capture: OutputCapture | None = None,
    ) -> FinancialCall:
        function = getattr(self._ak, name, None)
        if function is None:
            return FinancialCall(
                None, 0, "failed", "function_missing",
                f"Function {name!r} not found in akshare",
            )
        return call_with_retry(
            function,
            parameters,
            retry_delay_seconds=self.retry_delay_seconds,
            output_capture=output_capture,
        )

    def fetch_financial_abstract(
        self, symbol_plain: str, *, output_capture: OutputCapture | None = None
    ) -> FinancialCall:
        return self._call(
            "stock_financial_abstract",
            {"symbol": symbol_plain},
            output_capture,
        )

    def fetch_financial_indicator(
        self,
        symbol_plain: str,
        start_year: str,
        *,
        output_capture: OutputCapture | None = None,
    ) -> FinancialCall:
        return self._call(
            "stock_financial_analysis_indicator",
            {"symbol": symbol_plain, "start_year": start_year},
            output_capture,
        )

    def fetch_balance_sheet(
        self, symbol_em: str, *, output_capture: OutputCapture | None = None
    ) -> FinancialCall:
        return self._call(
            "stock_balance_sheet_by_report_em",
            {"symbol": symbol_em},
            output_capture,
        )

    def fetch_profit_sheet(
        self, symbol_em: str, *, output_capture: OutputCapture | None = None
    ) -> FinancialCall:
        return self._call(
            "stock_profit_sheet_by_report_em",
            {"symbol": symbol_em},
            output_capture,
        )

    def fetch_cashflow_sheet(
        self, symbol_em: str, *, output_capture: OutputCapture | None = None
    ) -> FinancialCall:
        return self._call(
            "stock_cash_flow_sheet_by_report_em",
            {"symbol": symbol_em},
            output_capture,
        )
