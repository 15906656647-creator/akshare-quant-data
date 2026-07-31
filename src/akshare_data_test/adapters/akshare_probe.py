# -*- coding: utf-8 -*-
"""Minimal AKShare probe adapter.

This module owns all AKShare calls used by the Stage 2 smoke test.  It performs
no business cleaning and writes no formal Raw/Clean/Feature data.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd


INTERFACE_HOSTS = {
    "stock_zh_a_hist": "push2his.eastmoney.com",
    "stock_zh_a_spot_em": "push2.eastmoney.com",
    "stock_financial_abstract": "quotes.sina.cn",
    "stock_financial_analysis_indicator": "money.finance.sina.com.cn",
    "stock_balance_sheet_by_report_em": "emweb.securities.eastmoney.com",
    "stock_profit_sheet_by_report_em": "emweb.securities.eastmoney.com",
    "stock_cash_flow_sheet_by_report_em": "emweb.securities.eastmoney.com",
    "stock_individual_fund_flow": "push2his.eastmoney.com",
    "stock_zt_pool_em": "push2ex.eastmoney.com",
    "stock_zt_pool_dtgc_em": "push2ex.eastmoney.com",
    "crypto_js_spot": "datacenter-api.jin10.com",
}

PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_SENSITIVE_URL_RE = re.compile(r"(?i)\b(https?://)([^/\s:@]+):([^@\s/]+)@")
_WHITESPACE_RE = re.compile(r"[\r\n\t]+")
_HOST_RE = re.compile(r"host=['\"]([^'\"]+)['\"]", re.IGNORECASE)


@dataclass
class ProbeResult:
    run_id: str
    probe_id: str
    category: str
    interface_name: str
    function_exists: bool
    function_signature: str
    parameters_json: str
    started_at: str
    finished_at: str
    elapsed_seconds: float
    attempt_count: int
    akshare_version: str
    status: str
    capability_result: str
    row_count: int | None = None
    column_count: int | None = None
    schema_hash: str = ""
    columns_json: str = ""
    dtypes_json: str = ""
    required_columns_present: bool | None = None
    missing_required_columns_json: str = ""
    coverage_start: str = ""
    coverage_end: str = ""
    sample_path: str = ""
    error_type: str = ""
    error_message: str = ""
    notes: str = ""
    pool_date: str = ""
    pool_date_source: str = ""
    exception_class: str = ""
    root_exception_class: str = ""
    root_error_message: str = ""
    target_host: str = ""
    retry_reason: str = ""
    proxy_detected: bool = False
    http_status_code: int | None = None
    sample_records_json: str = ""


def _get_akshare_version() -> str:
    import akshare

    return getattr(akshare, "__version__", "unknown")


def _function_exists_and_signature(func_name: str) -> tuple[bool, str]:
    import akshare

    if not hasattr(akshare, func_name):
        return False, ""
    func = getattr(akshare, func_name)
    if not callable(func):
        return False, ""
    try:
        sig = str(inspect.signature(func))
    except (ValueError, TypeError):
        sig = "<unavailable>"
    return True, sig


def _compute_schema_hash(columns: list[Any], dtypes: list[Any]) -> str:
    items = [{"name": c, "dtype": d} for c, d in zip(columns, dtypes)]
    raw = json.dumps(items, ensure_ascii=False, sort_keys=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_date_range(baseline_date: date, natural_days: int) -> tuple[str, str]:
    end = baseline_date
    start = end - timedelta(days=natural_days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _resolve_start_year(baseline_date: date) -> str:
    return str(baseline_date.year - 5)


def _proxy_detected() -> bool:
    return any(bool(os.environ.get(name) or os.environ.get(name.lower())) for name in PROXY_ENV_NAMES)


def _sanitize_message(value: Any, limit: int = 240) -> str:
    message = _WHITESPACE_RE.sub(" ", str(value)).strip()
    message = _SENSITIVE_URL_RE.sub(r"\1***:***@", message)
    for name in PROXY_ENV_NAMES:
        proxy_value = os.environ.get(name) or os.environ.get(name.lower())
        if proxy_value:
            message = message.replace(proxy_value, "<redacted-proxy>")
    return message[:limit]


def _root_exception(exc: BaseException) -> BaseException:
    """Find the deepest useful exception, including urllib3 ``reason`` links."""
    current = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        candidates = (
            getattr(current, "__cause__", None),
            getattr(current, "reason", None),
            getattr(current, "original_error", None),
            getattr(current, "__context__", None),
        )
        next_exc = next(
            (item for item in candidates if isinstance(item, BaseException) and id(item) not in seen),
            None,
        )
        if next_exc is None:
            break
        current = next_exc
    return current


def _http_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


def _target_host(exc: BaseException, interface_name: str) -> str:
    for candidate in (exc, _root_exception(exc)):
        message = str(candidate)
        host_match = _HOST_RE.search(message)
        if host_match:
            return host_match.group(1)
        request = getattr(candidate, "request", None)
        url = getattr(request, "url", "")
        if url:
            parsed = urlparse(url)
            if parsed.hostname:
                return parsed.hostname
    return INTERFACE_HOSTS.get(interface_name, "")


def _classify_error(error: str | BaseException, exception_name: str = "") -> str:
    """Classify a failure by root exception and message without conflating arguments."""
    exc = error if isinstance(error, BaseException) else None
    root = _root_exception(exc) if exc is not None else None
    names = " ".join(
        part for part in (
            exception_name,
            type(exc).__name__ if exc else "",
            type(root).__name__ if root else "",
        )
        if part
    ).lower()
    text = f"{error} {root or ''}".lower()

    if "typeerror" in names or any(x in text for x in ("unexpected keyword", "missing required positional")):
        return "invalid_parameter"
    if any(x in names for x in ("gaierror", "name resolution")) or any(
        x in text for x in ("getaddrinfo", "name or service not known", "nodename nor servname", "dns")
    ):
        return "dns_error"
    if any(x in names for x in ("sslerror", "sslcertverificationerror")) or any(
        x in text for x in ("certificate verify failed", "ssl:", "tls")
    ):
        return "ssl_error"
    if "timeout" in names or any(x in text for x in ("timed out", "timeout")):
        return "timeout"
    status = _http_status_code(exc) if exc else None
    if status == 429 or ("rate" in text and "limit" in text):
        return "rate_limit"
    if status is not None or any(x in text for x in ("http error", "status code", "403 forbidden", "404 not found")):
        return "http_error"
    if any(x in names for x in ("connectionerror", "newconnectionerror", "connectionrefusederror")) or any(
        x in text for x in ("connection", "max retries exceeded", "network is unreachable", "refused")
    ):
        return "connection_error"
    if any(x in names for x in ("jsondecodeerror", "parsererror", "keyerror", "valueerror")):
        return "upstream_format_error"
    if any(x in text for x in ("invalid parameter", "invalid argument", "parameter error")):
        return "invalid_parameter"
    return "unknown_error"


def _error_evidence(exc: BaseException, interface_name: str) -> dict[str, Any]:
    root = _root_exception(exc)
    return {
        "error_type": _classify_error(exc, type(exc).__name__),
        "exception_class": type(exc).__name__,
        "root_exception_class": type(root).__name__,
        "error_message": _sanitize_message(exc),
        "root_error_message": _sanitize_message(root),
        "target_host": _target_host(exc, interface_name),
        "proxy_detected": _proxy_detected(),
        "http_status_code": _http_status_code(exc),
    }


def _assess_crypto_capability(df: pd.DataFrame) -> str:
    columns = list(df.columns)
    pair_col = None
    for col in columns:
        lowered = str(col).lower()
        if any(
            key in lowered
            for key in ("市场", "交易", "品种", "pair", "symbol", "market", "name", "币种", "币对")
        ):
            pair_col = col
            break
    if pair_col is None:
        pair_col = next((col for col in columns if df[col].dtype == "object"), None)
    if pair_col is None:
        return "unknown"

    def normalize(value: Any) -> str:
        return re.sub(r"[/\-_\s]", "", str(value).upper())

    pairs = df[pair_col].astype(str).map(normalize).unique()
    if any(pair == "ETHUSDT" for pair in pairs):
        return "success"
    if any("ETH" in pair for pair in pairs):
        return "partial_success"
    return "unsupported"


def probe_function(
    probe_config: dict[str, Any],
    run_id: str,
    baseline_date: date,
    current_pool_date: str | None = None,
    pool_date_source: str = "unresolved",
    max_sample_rows: int = 20,
) -> ProbeResult:
    """Execute one AKShare call with at most one retry."""
    pid = probe_config["probe_id"]
    interface_name = probe_config["interface_name"]
    category = probe_config["category"]
    policy = probe_config.get("parameter_policy", {})
    required_columns = probe_config.get("required_columns", [])
    common = {
        "run_id": run_id,
        "probe_id": pid,
        "category": category,
        "interface_name": interface_name,
    }
    is_pool_probe = pid in {"limit_up_pool", "limit_down_pool"}
    result_pool_date = current_pool_date or "" if is_pool_probe else ""
    result_pool_source = pool_date_source if is_pool_probe else ""
    exists, signature = _function_exists_and_signature(interface_name)
    akshare_version = _get_akshare_version() if exists else "unknown"

    if not exists:
        return ProbeResult(
            **common,
            function_exists=False,
            function_signature="",
            parameters_json=json.dumps(policy, ensure_ascii=False),
            started_at="",
            finished_at="",
            elapsed_seconds=0.0,
            attempt_count=0,
            akshare_version=akshare_version,
            status="unsupported",
            capability_result="",
            error_type="function_missing",
            error_message=f"Function {interface_name!r} not found in akshare",
            notes=probe_config.get("notes", ""),
            pool_date=result_pool_date,
            pool_date_source=result_pool_source,
            target_host=INTERFACE_HOSTS.get(interface_name, ""),
            proxy_detected=_proxy_detected(),
        )

    resolved_parameters: dict[str, Any] = {}
    for key, value in policy.items():
        if value == "resolve" and key == "start_year":
            resolved_parameters[key] = _resolve_start_year(baseline_date)
        elif value == "resolve_pool_date":
            if current_pool_date:
                resolved_parameters[key] = current_pool_date.replace("-", "")
            else:
                return ProbeResult(
                    **common,
                    function_exists=True,
                    function_signature=signature,
                    parameters_json=json.dumps(policy, ensure_ascii=False),
                    started_at="",
                    finished_at="",
                    elapsed_seconds=0.0,
                    attempt_count=0,
                    akshare_version=akshare_version,
                    status="skipped",
                    capability_result="",
                    error_type="dependency_failure",
                    error_message="Pool date unresolved: no CLI date and stock_daily_raw did not succeed",
                    notes=probe_config.get("notes", ""),
                    pool_date="",
                    pool_date_source="unresolved",
                    target_host=INTERFACE_HOSTS.get(interface_name, ""),
                    proxy_detected=_proxy_detected(),
                )
        elif value != "resolve":
            resolved_parameters[key] = value
    if policy.get("start_date") == "resolve" or policy.get("end_date") == "resolve":
        start_date, end_date = _resolve_date_range(baseline_date, 90)
        resolved_parameters["start_date"] = start_date
        resolved_parameters["end_date"] = end_date

    parameters_json = json.dumps(resolved_parameters, ensure_ascii=False)
    import akshare

    function = getattr(akshare, interface_name)
    started_at = datetime.now(timezone.utc).isoformat()
    attempt_count = 0
    retry_reason = ""
    dataframe = None
    elapsed = 0.0
    final_error: dict[str, Any] | None = None

    for attempt in (1, 2):
        attempt_count = attempt
        started = time.perf_counter()
        try:
            dataframe = function(**resolved_parameters)
            elapsed = time.perf_counter() - started
            final_error = None
            break
        except Exception as exc:
            elapsed = time.perf_counter() - started
            final_error = _error_evidence(exc, interface_name)
            if attempt == 1 and final_error["error_type"] in {
                "dns_error",
                "connection_error",
                "timeout",
                "ssl_error",
                "http_error",
                "rate_limit",
            }:
                retry_reason = final_error["error_type"]
                time.sleep(2)
                continue
            break

    finished_at = datetime.now(timezone.utc).isoformat()
    if final_error is not None:
        return ProbeResult(
            **common,
            function_exists=True,
            function_signature=signature,
            parameters_json=parameters_json,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_seconds=round(elapsed, 4),
            attempt_count=attempt_count,
            akshare_version=akshare_version,
            status="failed",
            capability_result="",
            error_type=final_error["error_type"],
            error_message=final_error["error_message"],
            notes=probe_config.get("notes", ""),
            pool_date=result_pool_date,
            pool_date_source=result_pool_source,
            exception_class=final_error["exception_class"],
            root_exception_class=final_error["root_exception_class"],
            root_error_message=final_error["root_error_message"],
            target_host=final_error["target_host"],
            retry_reason=retry_reason,
            proxy_detected=final_error["proxy_detected"],
            http_status_code=final_error["http_status_code"],
        )

    if not isinstance(dataframe, pd.DataFrame):
        return ProbeResult(
            **common,
            function_exists=True,
            function_signature=signature,
            parameters_json=parameters_json,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_seconds=round(elapsed, 4),
            attempt_count=attempt_count,
            akshare_version=akshare_version,
            status="failed",
            capability_result="",
            row_count=None,
            error_type="unexpected_return_type",
            error_message=f"Returned {type(dataframe).__name__}, expected DataFrame",
            notes=probe_config.get("notes", ""),
            pool_date=result_pool_date,
            pool_date_source=result_pool_source,
            target_host=INTERFACE_HOSTS.get(interface_name, ""),
            retry_reason=retry_reason,
            proxy_detected=_proxy_detected(),
        )

    columns = list(dataframe.columns)
    dtypes = [str(dataframe[col].dtype) for col in columns]
    missing_required = [column for column in required_columns if column not in columns]
    coverage_start = ""
    coverage_end = ""
    if not dataframe.empty:
        date_column = next(
            (column for column in columns if "日期" in str(column) or "date" in str(column).lower()),
            None,
        )
        if date_column is not None:
            dates = pd.to_datetime(dataframe[date_column], errors="coerce").dropna()
            if not dates.empty:
                coverage_start = dates.min().strftime("%Y-%m-%d")
                coverage_end = dates.max().strftime("%Y-%m-%d")

    status = "success"
    error_type = ""
    error_message = ""
    if dataframe.empty:
        status = "empty"
        error_type = "empty_result"
        error_message = "Returned empty DataFrame"
    elif missing_required:
        status = "failed"
        error_type = "schema_mismatch"
        error_message = "Missing required columns: " + ", ".join(map(str, missing_required))

    capability_result = ""
    if pid == "crypto_spot" and status == "success":
        capability_result = _assess_crypto_capability(dataframe)

    sample_records_json = ""
    if status == "success":
        sample_records_json = dataframe.head(max(0, max_sample_rows)).to_json(
            orient="records",
            date_format="iso",
            force_ascii=False,
        )

    return ProbeResult(
        **common,
        function_exists=True,
        function_signature=signature,
        parameters_json=parameters_json,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=round(elapsed, 4),
        attempt_count=attempt_count,
        akshare_version=akshare_version,
        status=status,
        capability_result=capability_result,
        row_count=len(dataframe),
        column_count=len(columns),
        schema_hash=_compute_schema_hash(columns, dtypes),
        columns_json=json.dumps(columns, ensure_ascii=False),
        dtypes_json=json.dumps(dtypes, ensure_ascii=False),
        required_columns_present=not missing_required,
        missing_required_columns_json=json.dumps(missing_required, ensure_ascii=False),
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        error_type=error_type,
        error_message=error_message,
        notes=probe_config.get("notes", ""),
        pool_date=result_pool_date,
        pool_date_source=result_pool_source,
        target_host=INTERFACE_HOSTS.get(interface_name, ""),
        retry_reason=retry_reason,
        proxy_detected=_proxy_detected(),
        sample_records_json=sample_records_json,
    )
