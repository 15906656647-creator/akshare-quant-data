# -*- coding: utf-8 -*-
"""Offline/online probe adapter for authoritative status-history sources.

All network calls used by the Stage 15 S15-14 source audit live in this
module.  Probe evidence is append-only and every published JSON artifact is
written through a UTF-8 safe serializer with an immediate parse self-check;
an artifact that cannot be re-parsed is never published and the command fails
closed.  Nothing in this module is used by Stage 8 event detection itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


STOCKS = [
    "002067", "002600", "002230", "600763", "603259", "603799",
    "601012", "600438", "002361", "601500", "600231", "300274",
    "601636", "002129", "000100", "300433",
]

WINDOW_START = "2025-07-27"
WINDOW_END = "2026-07-27"

# Interface -> source kind.  Only an interface explicitly registered here as
# ``official_status_history`` may ever be graded A after evidence checks; the
# current probe set contains no such source, so the feasibility summary stays
# fail-closed until a verified formal status-history source is added.
SOURCE_KINDS: dict[str, str] = {
    "stock_zh_a_st_em": "current_st_snapshot",
    "stock_individual_info_em": "individual_snapshot",
    "stock_info_change_name": "former_name_history",
    "stock_info_sz_change_name_full": "name_change_history",
    "stock_info_sz_change_name_short": "name_change_history",
    "stock_info_sh_name_code": "official_current_list",
    "stock_info_sz_name_code": "official_current_list",
    "cninfo_risk_warning": "announcement_search",
    "cninfo_special_treatment": "announcement_search",
}

KNOWN_COLUMN_MAPPINGS: dict[str, dict[str, str]] = {
    "stock_zh_a_st_em": {
        "序号": "sequence",
        "代码": "security_code",
        "名称": "security_short_name",
        "最新价": "latest_price",
        "涨跌幅": "pct_change",
        "涨跌额": "price_change",
        "成交量": "volume_lot",
        "成交额": "amount_cny",
        "振幅": "amplitude",
        "最高": "high",
        "最低": "low",
        "今开": "open",
        "昨收": "previous_close",
        "量比": "volume_ratio",
        "换手率": "turnover_rate",
        "市盈率-动态": "pe_dynamic",
        "市净率": "pb",
    },
    "stock_individual_info_em": {
        "item": "field_name",
        "value": "field_value",
        "symbol": "probe_symbol",
    },
    "stock_info_change_name": {
        "index": "sequence",
        "name": "former_name",
        "symbol": "probe_symbol",
    },
    "stock_info_sz_change_name_full": {
        "变更日期": "change_date",
        "证券代码": "security_code",
        "证券简称": "security_short_name",
        "变更前全称": "previous_full_name",
        "变更后全称": "new_full_name",
    },
    "stock_info_sz_change_name_short": {
        "变更日期": "change_date",
        "证券代码": "security_code",
        "证券简称": "security_short_name",
        "变更前简称": "previous_short_name",
        "变更后简称": "new_short_name",
    },
    "stock_info_sh_name_code": {
        "证券代码": "security_code",
        "证券简称": "security_short_name",
        "证券全称": "security_full_name",
        "公司简称": "company_short_name",
        "公司全称": "company_full_name",
        "上市日期": "listing_date",
    },
    "stock_info_sz_name_code": {
        "板块": "board",
        "A股代码": "security_code",
        "A股简称": "security_short_name",
        "A股上市日期": "listing_date",
        "A股总股本": "total_shares",
        "A股流通股本": "float_shares",
        "所属行业": "industry",
    },
    "cninfo_risk_warning": {
        "代码": "security_code",
        "简称": "security_short_name",
        "公告标题": "announcement_title",
        "公告时间": "announcement_datetime",
        "公告链接": "announcement_url",
        "symbol": "probe_symbol",
    },
    "cninfo_special_treatment": {
        "代码": "security_code",
        "简称": "security_short_name",
        "公告标题": "announcement_title",
        "公告时间": "announcement_datetime",
        "公告链接": "announcement_url",
        "symbol": "probe_symbol",
    },
}

INTERFACE_PLAN: list[dict[str, Any]] = [
    {
        "name": "stock_zh_a_st_em",
        "source_name": "东方财富风险警示板",
        "category": "current_snapshot",
        "scope": "full_market",
        "params": {},
        "note": "Eastmoney current risk-warning (ST) board snapshot",
    },
    {
        "name": "stock_individual_info_em",
        "source_name": "东方财富个股信息",
        "category": "current_snapshot",
        "scope": "per_symbol",
        "params": {"symbols": STOCKS},
        "note": "Eastmoney current individual stock info snapshot",
    },
    {
        "name": "stock_info_change_name",
        "source_name": "新浪财经股票曾用名",
        "category": "name_history",
        "scope": "per_symbol",
        "params": {"symbols": STOCKS},
        "note": "Sina former-name history without effective dates",
    },
    {
        "name": "stock_info_sz_change_name_full",
        "source_name": "深交所全称变更",
        "category": "name_change_history",
        "scope": "full_market",
        "params": {"kind": "全称变更"},
        "note": "SZSE official full-name change records with effective dates",
    },
    {
        "name": "stock_info_sz_change_name_short",
        "source_name": "深交所简称变更",
        "category": "name_change_history",
        "scope": "full_market",
        "params": {"kind": "简称变更"},
        "note": "SZSE official short-name change records with effective dates",
    },
    {
        "name": "stock_info_sh_name_code",
        "source_name": "上交所股票列表",
        "category": "official_current_list",
        "scope": "full_market",
        "params": {"kind": "主板A股"},
        "note": "SSE official main-board A-share list",
    },
    {
        "name": "stock_info_sz_name_code",
        "source_name": "深交所A股列表",
        "category": "official_current_list",
        "scope": "full_market",
        "params": {"kind": "A股列表"},
        "note": "SZSE official A-share list",
    },
    {
        "name": "cninfo_risk_warning",
        "source_name": "巨潮资讯风险警示公告检索",
        "category": "announcement_search",
        "scope": "per_symbol",
        "params": {
            "symbols": STOCKS,
            "keyword": "风险警示",
            "start_date": "20200101",
            "end_date": "20260727",
        },
        "note": "CNINFO official disclosure search for risk-warning announcements",
    },
    {
        "name": "cninfo_special_treatment",
        "source_name": "巨潮资讯特别处理和退市公告",
        "category": "announcement_search",
        "scope": "per_symbol",
        "params": {
            "symbols": STOCKS,
            "category": "特别处理和退市",
            "start_date": "20200101",
            "end_date": "20260727",
        },
        "note": "CNINFO official special-treatment/delisting announcement category",
    },
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _akshare_version() -> str:
    try:
        import akshare

        return str(getattr(akshare, "__version__", "unknown"))
    except Exception:
        return "unavailable"


def probe_plan() -> list[dict[str, Any]]:
    return [
        {
            "interface": item["name"],
            "source_name": item["source_name"],
            "category": item["category"],
            "scope": item["scope"],
            "parameters": item["params"],
            "note": item["note"],
        }
        for item in INTERFACE_PLAN
    ]


def _json_safe(value: Any) -> Any:
    """Recursively normalize pandas/numpy/date values for JSON output."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return None if not math.isfinite(number) else number
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if pd.isna(value):
            return None
        try:
            return value.isoformat()
        except (AttributeError, ValueError):
            return str(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _atomic_write_text(path: Path, text: str, *, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        text,
        encoding="utf-8-sig" if bom else "utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _safe_json_write(path: Path, payload: Any) -> Any:
    """Serialize to UTF-8 JSON, atomically publish, then reparse self-check."""
    normalized = _json_safe(payload)
    text = json.dumps(
        normalized, ensure_ascii=False, indent=2, allow_nan=False
    ) + "\n"
    # UTF-8 with BOM lets Windows PowerShell's default Get-Content decode the
    # file as UTF-8 instead of mis-decoding multi-byte characters (which could
    # swallow quote bytes and break ConvertFrom-Json).
    _atomic_write_text(path, text, bom=True)
    try:
        reparsed = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ValueError(
            f"published JSON failed parse self-check: {path}: {exc}"
        ) from exc
    if reparsed != normalized:
        raise ValueError(
            f"published JSON did not round-trip equal: {path}"
        )
    return reparsed


def _classify_probe_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timed out" in message:
        return "timeout"
    if any(
        token in name or token in message
        for token in ("connection", "remote disconnected", "dns", "ssl", "proxy")
    ):
        return "connection_error"
    if "rate" in message and "limit" in message:
        return "rate_limit"
    if any(
        token in message
        for token in ("parse", "json decode", "schema", "columns")
    ) or any(token in name for token in ("jsondecode", "parsererror", "keyerror")):
        return "parse_error"
    if any(token in message for token in ("not found", "参数", "invalid")):
        return "invalid_parameter"
    return "unknown_error"


def _call(function: Callable[..., pd.DataFrame], **kwargs: Any) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Execute one probe with bounded retries and per-attempt failure records."""
    attempts: list[dict[str, Any]] = []
    last: Exception | None = None
    for attempt in range(1, 4):
        started = time.perf_counter()
        try:
            frame = function(**kwargs)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "success",
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                    "error_type": "",
                    "error_message": "",
                }
            )
            return frame, attempts
        except Exception as exc:  # noqa: BLE001 - adapter boundary
            last = exc
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                    "error_type": _classify_probe_error(exc),
                    "error_message": str(exc)[:500],
                }
            )
            if attempt < 3:
                time.sleep(2.0 + attempt)
    assert last is not None
    raise last


def _column_mapping(interface: str, columns: list[str]) -> dict[str, Any]:
    known = KNOWN_COLUMN_MAPPINGS.get(interface, {})
    mapping: dict[str, str] = {}
    normalized: list[str] = []
    errors: list[str] = []
    for raw in columns:
        name = str(raw)
        target = known.get(name)
        if target is None:
            mapping[name] = "UNMAPPED"
            normalized.append("UNMAPPED")
            errors.append(f"unmapped_column:{name}")
        else:
            mapping[name] = target
            normalized.append(target)
    if not columns:
        status = "UNMAPPED"
    elif not errors:
        status = "MAPPED"
    elif len(errors) == len(columns):
        status = "UNMAPPED"
    else:
        status = "PARTIAL"
    return {
        "raw_columns": [str(item) for item in columns],
        "normalized_columns": normalized,
        "column_mapping": mapping,
        "mapping_status": status,
        "mapping_errors": errors,
    }


def _date_coverage(frame: pd.DataFrame, mapping: dict[str, Any]) -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    for raw, normalized in mapping["column_mapping"].items():
        if normalized in {
            "change_date", "listing_date", "announcement_datetime"
        }:
            candidates.append((raw, normalized))
    if not candidates and frame.shape[1]:
        for raw in frame.columns:
            text = str(raw)
            if "日期" in text or "时间" in text or "date" in text.lower():
                candidates.append((str(raw), "unknown_date"))
    if not candidates:
        return {"has_dates": False, "start": "", "end": ""}
    raw, _ = candidates[0]
    series = pd.to_datetime(frame[raw], errors="coerce").dropna()
    if series.empty:
        return {"has_dates": True, "start": "", "end": ""}
    return {
        "has_dates": True,
        "start": series.min().date().isoformat(),
        "end": series.max().date().isoformat(),
    }


def _grade_probe(entry: dict[str, Any]) -> tuple[str, list[str]]:
    status = entry["probe_status"]
    rows = int(entry["rows"])
    kind = entry["source_kind"]
    reasons: list[str] = []
    if status == "failed":
        reasons.append(f"interface_failure:{entry['error_type']}")
        return "C", reasons
    if status == "empty":
        reasons.append("empty_result_cannot_prove_no_data")
        return "C", reasons
    if rows == 0:
        reasons.append("empty_result_cannot_prove_no_data")
        return "C", reasons
    if kind == "former_name_history":
        reasons.append("no_effective_dates")
        return "C", reasons
    if kind == "official_status_history":
        # Reserved for future verified formal status-history sources.
        if (
            entry["date_coverage"].get("has_dates")
            and entry["date_coverage"].get("start")
            and entry["date_coverage"]["start"] <= WINDOW_START
            and entry["date_coverage"]["end"] >= WINDOW_END
        ):
            return "A", []
        reasons.append("incomplete_date_coverage")
        return "C", reasons
    if kind in {
        "current_st_snapshot",
        "individual_snapshot",
        "official_current_list",
        "name_change_history",
        "announcement_search",
    }:
        reasons.append("auxiliary_only_not_complete_status_history")
        return "B", reasons
    reasons.append("unclassified_source")
    return "C", reasons


def _build_probe_entry(
    *,
    plan: dict[str, Any],
    frame: pd.DataFrame | None,
    status: str,
    error_type: str = "",
    error_message: str = "",
    attempts: list[dict[str, Any]] | None = None,
    raw_file: Path | None = None,
    symbol_failures: list[str] | None = None,
) -> dict[str, Any]:
    columns = list(frame.columns) if frame is not None else []
    mapping = _column_mapping(plan["name"], columns)
    date_coverage = (
        _date_coverage(frame, mapping)
        if frame is not None and len(frame)
        else {"has_dates": False, "start": "", "end": ""}
    )
    kind = SOURCE_KINDS.get(plan["name"], "unknown")
    entry = {
        "source_name": plan["source_name"],
        "interface": plan["name"],
        "parameters": plan["params"],
        "probe_status": status,
        "result_semantics": (
            "data_returned"
            if status == "success" and frame is not None and len(frame)
            else "partial_data"
            if status == "partial" and frame is not None and len(frame)
            else "empty_result"
            if frame is not None
            else "interface_failure"
        ),
        "rows": 0 if frame is None else int(len(frame)),
        "raw_columns": mapping["raw_columns"],
        "normalized_columns": mapping["normalized_columns"],
        "column_mapping": mapping["column_mapping"],
        "mapping_status": mapping["mapping_status"],
        "mapping_errors": mapping["mapping_errors"],
        "snapshot_or_history": (
            "history"
            if kind in {"name_change_history", "former_name_history"}
            else "snapshot"
            if kind in {"current_st_snapshot", "individual_snapshot", "official_current_list"}
            else "search_or_unknown"
        ),
        "date_coverage": date_coverage,
        "exchange_coverage": (
            "SZSE"
            if plan["name"].startswith("stock_info_sz")
            else "SSE"
            if plan["name"].startswith("stock_info_sh")
            else "沪深京"
            if plan["name"].startswith("cninfo")
            else "沪深"
        ),
        "sample_coverage": (
            "16_of_16"
            if plan["scope"] == "per_symbol"
            else "full_market"
        ),
        "source_kind": kind,
        "error_type": error_type,
        "error_message": error_message[:500],
        "attempts": attempts or [],
        "symbol_failures": symbol_failures or [],
        "raw_file": str(raw_file.relative_to(raw_file.parents[1]))
        if raw_file is not None
        else "",
        "size": raw_file.stat().st_size if raw_file is not None else 0,
        "sha256": _sha256(raw_file) if raw_file is not None else "",
    }
    grade, blocking = _grade_probe(entry)
    entry["source_grade"] = grade
    entry["authoritative"] = grade == "A"
    entry["can_build_limit_rules"] = False
    entry["can_build_security_status"] = grade == "A"
    entry["auxiliary_only"] = grade in {"B", "C"}
    entry["blocking_reason"] = "; ".join(blocking)
    return entry


def probe_source_suite(
    output_dir: Path,
    *,
    as_of_date: date,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Probe candidate sources and persist append-only evidence and manifest."""
    import akshare as ak

    output_dir.mkdir(parents=True, exist_ok=True)
    effective_run_id = run_id or str(uuid.uuid4())
    fetched_at = datetime.now(timezone.utc).isoformat()
    version = _akshare_version()
    probes: list[dict[str, Any]] = []
    previous_default = socket.getdefaulttimeout()
    socket.setdefaulttimeout(30)
    try:
        def save(name: str, frame: pd.DataFrame) -> Path:
            path = output_dir / f"{name}.csv"
            frame.to_csv(path, index=False, encoding="utf-8-sig")
            return path

        for plan in INTERFACE_PLAN:
            name = plan["name"]
            kind = plan["params"].get("kind")
            if name in {
                "stock_info_sz_change_name_full",
                "stock_info_sz_change_name_short",
            }:
                function = getattr(ak, "stock_info_sz_change_name")
                try:
                    frame, attempts = _call(function, symbol=kind)
                    status = "success" if len(frame) else "empty"
                    raw_file = save(name, frame)
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=frame, status=status,
                            attempts=attempts, raw_file=raw_file,
                        )
                    )
                except Exception as exc:
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=None, status="failed",
                            error_type=_classify_probe_error(exc),
                            error_message=str(exc),
                        )
                    )
                continue
            if name in {"stock_info_sh_name_code", "stock_info_sz_name_code"}:
                function = getattr(ak, name)
                try:
                    frame, attempts = _call(function, symbol=kind)
                    status = "success" if len(frame) else "empty"
                    raw_file = save(name, frame)
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=frame, status=status,
                            attempts=attempts, raw_file=raw_file,
                        )
                    )
                except Exception as exc:
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=None, status="failed",
                            error_type=_classify_probe_error(exc),
                            error_message=str(exc),
                        )
                    )
                continue
            if name == "stock_zh_a_st_em":
                try:
                    frame, attempts = _call(getattr(ak, name))
                    status = "success" if len(frame) else "empty"
                    raw_file = save(name, frame)
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=frame, status=status,
                            attempts=attempts, raw_file=raw_file,
                        )
                    )
                except Exception as exc:
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=None, status="failed",
                            error_type=_classify_probe_error(exc),
                            error_message=str(exc),
                        )
                    )
                continue
            if name in {
                "stock_individual_info_em",
                "stock_info_change_name",
                "cninfo_risk_warning",
                "cninfo_special_treatment",
            }:
                frames: list[pd.DataFrame] = []
                failures: list[str] = []
                for symbol in STOCKS:
                    try:
                        if name == "stock_individual_info_em":
                            frame, _ = _call(
                                getattr(ak, name), symbol=symbol, timeout=25
                            )
                        elif name == "stock_info_change_name":
                            frame, _ = _call(getattr(ak, name), symbol=symbol)
                        else:
                            frame, _ = _call(
                                getattr(ak, "stock_zh_a_disclosure_report_cninfo"),
                                symbol=symbol,
                                market="沪深京",
                                keyword=plan["params"].get("keyword", ""),
                                category=plan["params"].get("category", ""),
                                start_date=plan["params"]["start_date"],
                                end_date=plan["params"]["end_date"],
                            )
                        frames.append(frame.assign(symbol=symbol))
                    except Exception as exc:
                        failures.append(
                            f"{symbol}:{type(exc).__name__}:{str(exc)[:200]}"
                        )
                if frames:
                    combined = pd.concat(frames, ignore_index=True)
                    status = (
                        "success"
                        if not failures
                        else "empty"
                        if len(combined) == 0
                        else "partial"
                    )
                    raw_file = save(name, combined)
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=combined, status=status,
                            attempts=[], raw_file=raw_file,
                            symbol_failures=failures,
                        )
                    )
                else:
                    probes.append(
                        _build_probe_entry(
                            plan=plan, frame=None, status="failed",
                            error_type="connection_error",
                            error_message="; ".join(failures[:10]) or "no successful call",
                            symbol_failures=failures,
                        )
                    )
                continue
            raise AssertionError(f"unhandled probe interface: {name}")
    finally:
        socket.setdefaulttimeout(previous_default)

    manifest = {
        "run_id": effective_run_id,
        "as_of_date": as_of_date.isoformat(),
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "fetched_at": fetched_at,
        "akshare_version": version,
        "interfaces_probed": sorted({item["interface"] for item in probes}),
        "probes": probes,
    }
    _safe_json_write(output_dir / "probe_manifest.json", manifest)
    return manifest


def _write_feasibility_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "source_name", "interface", "probe_status", "rows", "raw_columns",
        "normalized_columns", "snapshot_or_history", "date_coverage",
        "exchange_coverage", "sample_coverage", "source_grade",
        "authoritative", "can_build_limit_rules", "can_build_security_status",
        "auxiliary_only", "blocking_reason", "raw_file", "sha256",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["raw_columns"] = frame["raw_columns"].map(lambda value: "; ".join(value))
    frame["normalized_columns"] = frame["normalized_columns"].map(
        lambda value: "; ".join(value)
    )
    frame["date_coverage"] = frame["date_coverage"].map(
        lambda value: (
            f"{value['start']}~{value['end']}" if value.get("has_dates") else "none"
        )
    )
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _write_feasibility_markdown(
    path: Path,
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    lines = [
        "# 数据源可行性报告",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- as_of_date: {summary['as_of_date']}",
        f"- 探测窗口: {WINDOW_START} 至 {WINDOW_END}",
        f"- 抓取时间: {summary['fetched_at']}",
        f"- AKShare 版本: {summary['akshare_version']}",
        "",
        "| 来源 | 接口 | 状态 | 行数 | 快照/历史 | 日期覆盖 | 等级 | 阻断原因 |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        coverage = row["date_coverage"]
        lines.append(
            f"| {row['source_name']} | {row['interface']} | "
            f"{row['probe_status']} | {row['rows']} | "
            f"{row['snapshot_or_history']} | "
            f"{coverage['start']}~{coverage['end']} | "
            f"{row['source_grade']} | {row['blocking_reason']} |"
        )
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            f"- authoritative_rule_source_ready: "
            f"`{summary['authoritative_rule_source_ready']}`",
            f"- authoritative_status_source_ready: "
            f"`{summary['authoritative_status_source_ready']}`",
            f"- can_continue_rules_build: `{summary['can_continue_rules_build']}`",
            f"- can_continue_status_build: `{summary['can_continue_status_build']}`",
            "- blocking_reasons: " + "; ".join(summary["blocking_reasons"]),
            "",
            "## 结论",
            "",
            summary["conclusion"],
            "",
            "等级说明：A级要求官方来源、历史有效日期、完整状态含义、可审计原始证据，"
            "且覆盖 S15-14 日期范围；B级仅可辅助校验（上市日期、简称变更、当前快照、"
            "名称中 ST 线索等）；C级不可使用（连接失败、无法证明真实无数据的空结果、"
            "无日期或字段无法解释）。接口执行成功不等于 A 级。",
        ]
    )
    _atomic_write_text(path, "\n".join(lines) + "\n", bom=True)


def write_feasibility_report(
    evidence_dir: Path,
    output_dir: Path,
    *,
    run_id: str,
    as_of_date: date,
) -> dict[str, Any]:
    """Write feasibility CSV/Markdown, grade summary, and column mappings."""
    manifest_path = evidence_dir / "probe_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(
            f"probe_manifest.json is invalid or unreadable: {manifest_path}: {exc}"
        ) from exc
    rows: list[dict[str, Any]] = []
    for probe in manifest.get("probes", []):
        rows.append(
            {
                "source_name": probe.get("source_name", ""),
                "interface": probe.get("interface", ""),
                "probe_status": probe.get("probe_status", ""),
                "rows": int(probe.get("rows", 0)),
                "raw_columns": list(probe.get("raw_columns", [])),
                "normalized_columns": list(probe.get("normalized_columns", [])),
                "snapshot_or_history": probe.get("snapshot_or_history", ""),
                "date_coverage": probe.get("date_coverage", {}),
                "exchange_coverage": probe.get("exchange_coverage", ""),
                "sample_coverage": probe.get("sample_coverage", ""),
                "source_grade": probe.get("source_grade", "C"),
                "authoritative": bool(probe.get("authoritative", False)),
                "can_build_limit_rules": bool(
                    probe.get("can_build_limit_rules", False)
                ),
                "can_build_security_status": bool(
                    probe.get("can_build_security_status", False)
                ),
                "auxiliary_only": bool(probe.get("auxiliary_only", True)),
                "blocking_reason": probe.get("blocking_reason", ""),
                "raw_file": probe.get("raw_file", ""),
                "sha256": probe.get("sha256", ""),
            }
        )
    grades = {row["source_grade"] for row in rows}
    blocking_reasons = sorted(
        {
            reason
            for row in rows
            for reason in (
                row["blocking_reason"].split("; ")
                if row["blocking_reason"]
                else []
            )
            if reason
        }
    )
    blocking_reasons.extend(
        [
            "no_authoritative_rule_source",
            "no_authoritative_status_history_source",
        ]
    )
    blocking_reasons = sorted(set(blocking_reasons))
    summary = {
        "run_id": run_id,
        "as_of_date": as_of_date.isoformat(),
        "fetched_at": manifest.get("fetched_at", ""),
        "akshare_version": manifest.get("akshare_version", ""),
        "authoritative_rule_source_ready": False,
        "authoritative_status_source_ready": False,
        "can_continue_rules_build": False,
        "can_continue_status_build": False,
        "blocking_reasons": blocking_reasons,
        "grade_counts": {
            "A": sum(row["source_grade"] == "A" for row in rows),
            "B": sum(row["source_grade"] == "B" for row in rows),
            "C": sum(row["source_grade"] == "C" for row in rows),
        },
        "summary": (
            "authoritative_sources_insufficient"
            if grades <= {"B", "C"} or not grades
            else "authoritative_sources_available"
        ),
        "conclusion": (
            "当前只能完成数据源可行性审计，不能构建正式Stage8数据，"
            "S15-14继续BLOCKED，阶段15尚不能完全通过。"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _safe_json_write(output_dir / "source_grade_summary.json", summary)
    _safe_json_write(output_dir / "column_mapping.json", {
        "run_id": run_id,
        "as_of_date": as_of_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interfaces": [
            {
                "interface": row["interface"],
                "source_name": row["source_name"],
                "raw_columns": row["raw_columns"],
                "normalized_columns": row["normalized_columns"],
                "column_mapping": {
                    raw: normalized
                    for raw, normalized in zip(
                        row["raw_columns"], row["normalized_columns"]
                    )
                },
                "mapping_status": (
                    "MAPPED"
                    if row["raw_columns"]
                    and all(
                        normalized != "UNMAPPED"
                        for normalized in row["normalized_columns"]
                    )
                    else "UNMAPPED"
                    if not row["raw_columns"]
                    or not any(
                        normalized != "UNMAPPED"
                        for normalized in row["normalized_columns"]
                    )
                    else "PARTIAL"
                ),
                "mapping_errors": [
                    f"unmapped_column:{raw}"
                    for raw, normalized in zip(
                        row["raw_columns"], row["normalized_columns"]
                    )
                    if normalized == "UNMAPPED"
                ],
            }
            for row in rows
        ],
    })
    _write_feasibility_csv(output_dir / "source_feasibility.csv", rows)
    _write_feasibility_markdown(
        output_dir / "source_feasibility.md", rows=rows, summary=summary
    )
    # Reparse every published JSON artifact as a final self-check.
    for name in ("source_grade_summary.json", "column_mapping.json"):
        json.loads((output_dir / name).read_text(encoding="utf-8-sig"))
    return summary
