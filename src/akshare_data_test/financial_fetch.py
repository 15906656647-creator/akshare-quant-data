"""Stage 4 orchestration and evidence generation."""
from __future__ import annotations

import csv
import json
import platform
import shutil
import subprocess
import time
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .adapters.stock_finance import StockFinanceAdapter
from .adapters.stock_fund_flow import StockFundFlowAdapter
from .collectors.financial_collector import (
    FUND_DATE_TOKENS,
    FinancialCollector,
    FinancialRecord,
    core_field_rows,
)
from .config import load_universe
from .market_fetch import _git_commit, _write_csv, _write_json
from .paths import project_root
from .storage.raw_store import RawStore, file_record

INTERFACES = (
    ("financial_abstract", "stock_financial_abstract"),
    ("financial_indicator", "stock_financial_analysis_indicator"),
    ("balance_sheet_report", "stock_balance_sheet_by_report_em"),
    ("profit_sheet_report", "stock_profit_sheet_by_report_em"),
    ("cashflow_sheet_report", "stock_cash_flow_sheet_by_report_em"),
    ("individual_fund_flow", "stock_individual_fund_flow"),
)

_INT_FIELDS = {
    "row_count", "column_count", "attempt_count", "warning_count", "error_count"
}
_FLOAT_FIELDS = {"elapsed_seconds"}


def _record_from_csv(row: dict[str, str]) -> FinancialRecord:
    values: dict[str, Any] = {}
    for name in FinancialRecord.__dataclass_fields__:
        value: Any = row.get(name, "")
        if name in _INT_FIELDS:
            value = int(value or 0)
        elif name in _FLOAT_FIELDS:
            value = float(value or 0)
        values[name] = value
    return FinancialRecord(**values)


def resolve_start_year(as_of_date: date, requested: str | None = None) -> str:
    derived = str(as_of_date.year - 5)
    if requested is not None and requested != derived:
        raise ValueError(
            f"--start-year must equal as_of_date.year - 5 ({derived})"
        )
    return requested or derived


def _date_values(frame: pd.DataFrame) -> list[date]:
    for token in FUND_DATE_TOKENS:
        matches = [
            column for column in frame.columns
            if token.casefold() in str(column).casefold()
        ]
        if matches:
            return [
                item.date()
                for item in pd.to_datetime(
                    frame[matches[0]], errors="coerce"
                ).dropna()
            ]
    return []


def _point_rows(
    record: FinancialRecord, frame: pd.DataFrame, as_of_date: date
) -> list[dict[str, Any]]:
    report_cols = json.loads(record.detected_report_date_columns)
    announcement_cols = json.loads(record.detected_announcement_date_columns)
    header_periods = [column for column in report_cols if column not in frame.columns]
    if not header_periods:
        header_periods = [
            column for column in report_cols
            if column in frame.columns
            and str(column)[:4].isdigit()
        ]
    if header_periods:
        return [{
            "run_id": record.run_id, "symbol": record.symbol,
            "interface_id": record.interface_id,
            "report_period": pd.to_datetime(column).date().isoformat(),
            "announcement_date": "", "as_of_date": as_of_date.isoformat(),
            "potential_lookahead": False,
            "announcement_date_status": "unavailable",
            "raw_path": record.raw_path,
            "notes": (
                "WARN: report period detected from column label; "
                "announcement date unavailable"
            ),
        } for column in header_periods]
    if not report_cols:
        return [{
            "run_id": record.run_id, "symbol": record.symbol,
            "interface_id": record.interface_id, "report_period": "",
            "announcement_date": "", "as_of_date": as_of_date.isoformat(),
            "potential_lookahead": False,
            "announcement_date_status": "unavailable",
            "raw_path": record.raw_path,
            "notes": "WARN: report/announcement date could not be paired",
        }]
    rows: list[dict[str, Any]] = []
    report = pd.to_datetime(frame[report_cols[0]], errors="coerce")
    announcement = (
        pd.to_datetime(frame[announcement_cols[0]], errors="coerce")
        if announcement_cols else pd.Series(pd.NaT, index=frame.index)
    )
    for index in frame.index:
        rp = report.loc[index]
        ad = announcement.loc[index]
        report_text = "" if pd.isna(rp) else rp.date().isoformat()
        announcement_text = "" if pd.isna(ad) else ad.date().isoformat()
        future_report = bool(not pd.isna(rp) and rp.date() > as_of_date)
        lookahead = bool(not pd.isna(ad) and ad.date() > as_of_date)
        note = "ERROR: report period later than as_of_date" if future_report else ""
        rows.append({
            "run_id": record.run_id, "symbol": record.symbol,
            "interface_id": record.interface_id,
            "report_period": report_text,
            "announcement_date": announcement_text,
            "as_of_date": as_of_date.isoformat(),
            "potential_lookahead": lookahead,
            "announcement_date_status": (
                "unavailable" if pd.isna(ad) else "available"
            ),
            "raw_path": record.raw_path, "notes": note,
        })
    return rows


def _documentation(run_id: str, status: str) -> str:
    return f"""# 阶段4：财务与资金流 Raw 抓取

- Run ID：`{run_id}`
- 状态：**{status}**
- 范围：16只股票、5类财务数据和个股资金流，共96项任务。

Raw 保留 AKShare 原始列、列顺序、空列和宽表结构。本阶段不创建 Clean、
Feature 或业务数据库，不计算单季度、TTM、同比、环比或财务比率，也不对
资金流源字段作确定性行为解释。
"""


def run_financial_fetch(
    *,
    as_of_date: date,
    start_year: str | None = None,
    output_dir: str | Path = "data/raw",
    evidence_dir: str | Path = "reports/evidence/stage4",
    run_id: str | None = None,
    only_symbol: str | None = None,
    only_interface: str | None = None,
    resume: bool = False,
    finance_adapter: Any | None = None,
    fund_flow_adapter: Any | None = None,
    inter_task_delay_seconds: float = 0.3,
    now: Any | None = None,
    project_root_override: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    root = Path(project_root_override).resolve() if project_root_override else project_root()
    universe = load_universe()
    derived_year = resolve_start_year(as_of_date, start_year)
    actual_run_id = run_id or str(uuid.uuid4())
    uuid.UUID(actual_run_id)
    if resume and run_id is None:
        raise ValueError("--resume requires --run-id")
    stocks = universe.stocks
    if only_symbol:
        stocks = [stock for stock in stocks if stock.symbol == only_symbol]
        if not stocks:
            raise ValueError(f"Unknown configured symbol: {only_symbol}")
    interfaces = list(INTERFACES)
    if only_interface:
        interfaces = [item for item in interfaces if item[0] == only_interface]
        if not interfaces:
            raise ValueError(f"Unknown Stage 4 interface: {only_interface}")
    clock = now or (lambda: datetime.now(ZoneInfo(universe.timezone)))
    raw_root = Path(output_dir)
    if not raw_root.is_absolute():
        raw_root = root / raw_root
    evidence_root = Path(evidence_dir)
    if not evidence_root.is_absolute():
        evidence_root = root / evidence_root
    fa = finance_adapter or StockFinanceAdapter()
    ffa = fund_flow_adapter or StockFundFlowAdapter()
    collector = FinancialCollector(
        finance_adapter=fa, fund_flow_adapter=ffa, store=RawStore(raw_root),
        now=clock, project_root=root,
    )
    started_at = clock()
    records: list[FinancialRecord] = []
    frames_by_symbol: dict[str, dict[str, pd.DataFrame]] = {}
    previous: dict[tuple[str, str], FinancialRecord] = {}
    coverage_path = root / "reports/stage4_financial_coverage.csv"
    run_path = root / "reports/stage4_financial_run.json"
    manifest_path = evidence_root / actual_run_id / "manifest.json"
    if resume and coverage_path.exists():
        with coverage_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("run_id") == actual_run_id:
                    record = _record_from_csv(row)
                    previous[(record.symbol, record.interface_id)] = record
        # Preserve the failed attempt before final reports are regenerated.
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        snapshots = (
            (coverage_path, manifest_path.parent / "initial_failure_coverage.csv"),
            (run_path, manifest_path.parent / "initial_failure_run.json"),
            (manifest_path, manifest_path.parent / "initial_failure_manifest.json"),
            (coverage_path, root / "reports/stage4_repair_before_coverage.csv"),
            (run_path, root / "reports/stage4_repair_before_run.json"),
            (
                manifest_path,
                manifest_path.parent / "manifest.before_repair.json",
            ),
        )
        for source, destination in snapshots:
            if source.exists() and not destination.exists():
                shutil.copy2(source, destination)
    total = len(stocks) * len(interfaces)
    for task_index, stock in enumerate(stocks):
        frames_by_symbol[stock.symbol] = {}
        for interface_id, interface_name in interfaces:
            prior = previous.get((stock.symbol, interface_id))
            prior_path = root / prior.raw_path if prior and prior.raw_path else None
            if (
                prior is not None
                and prior.status == "success"
                and prior_path is not None
                and prior_path.is_file()
            ):
                record = prior
                frame = pd.read_parquet(prior_path)
            else:
                record, frame = collector.collect(
                    run_id=actual_run_id, interface_id=interface_id,
                    interface_name=interface_name, stock=stock,
                    as_of_date=as_of_date, start_year=derived_year,
                )
            records.append(record)
            if frame is not None and not frame.empty:
                frames_by_symbol[stock.symbol][interface_id] = frame
            if inter_task_delay_seconds and task_index < total - 1:
                time.sleep(inter_task_delay_seconds)
    finished_at = clock()
    success_count = sum(record.status == "success" for record in records)
    empty_count = sum(record.status == "empty" for record in records)
    failed_count = len(records) - success_count - empty_count
    status = "PASS" if success_count == total else "PARTIAL"
    core_path = root / "reports/stage4_core_field_availability.csv"
    fund_path = root / "reports/stage4_fund_flow_coverage.csv"
    point_path = root / "reports/stage4_point_in_time_risk.csv"
    doc_path = root / "docs/stage4_financial_fetch.md"
    for record in records:
        record.evidence_write_status = "success"
    rows = [record.to_dict() for record in records]
    _write_csv(coverage_path, rows, tuple(FinancialRecord.__dataclass_fields__))
    core_rows: list[dict[str, Any]] = []
    for symbol, frames in frames_by_symbol.items():
        core_rows.extend(core_field_rows(actual_run_id, symbol, frames))
    _write_csv(core_path, core_rows, (
        "run_id", "symbol", "concept", "candidate_source_interface",
        "matched_source_fields", "availability_status", "non_null_count", "notes",
    ))
    fund_rows: list[dict[str, Any]] = []
    point_rows: list[dict[str, Any]] = []
    for record in records:
        frame = frames_by_symbol[record.symbol].get(record.interface_id)
        if record.interface_id == "individual_fund_flow":
            dates = [] if frame is None else _date_values(frame)
            fund_rows.append({
                "run_id": actual_run_id, "symbol": record.symbol,
                "status": record.status, "row_count": record.row_count,
                "column_count": record.column_count,
                "min_date": min(dates).isoformat() if dates else "",
                "max_date": max(dates).isoformat() if dates else "",
                "coverage_days": (max(dates) - min(dates)).days + 1 if dates else 0,
                "schema_hash": record.schema_hash, "raw_path": record.raw_path,
                "warning": "limited upstream window; not complete multi-year history",
            })
        elif frame is not None:
            point_rows.extend(_point_rows(record, frame, as_of_date))
    _write_csv(fund_path, fund_rows, (
        "run_id", "symbol", "status", "row_count", "column_count", "min_date",
        "max_date", "coverage_days", "schema_hash", "raw_path", "warning",
    ))
    _write_csv(point_path, point_rows, (
        "run_id", "symbol", "interface_id", "report_period",
        "announcement_date", "as_of_date", "potential_lookahead",
        "announcement_date_status", "raw_path", "notes",
    ))
    core_ok_symbols = sum(
        all(any(
            row["symbol"] == stock.symbol and row["concept"] == concept
            and row["availability_status"] == "available_non_null"
            for row in core_rows
        ) for concept in ("报告期", "营业收入或营业总收入"))
        and any(
            row["symbol"] == stock.symbol
            and row["concept"] in ("净利润", "归属于母公司股东的净利润")
            and row["availability_status"] == "available_non_null"
            for row in core_rows
        )
        for stock in stocks
    )
    report = {
        "stage": 4, "run_id": actual_run_id, "status": status,
        "as_of_date": as_of_date.isoformat(), "start_year": derived_year,
        "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
        "python_version": platform.python_version(),
        "akshare_version": fa.akshare_version, "stock_count": len(stocks),
        "interface_count": len(interfaces), "expected_task_count": total,
        "success_count": success_count, "empty_count": empty_count,
        "failed_count": failed_count,
        "core_financial_symbol_count": core_ok_symbols,
        "statement_success_count": sum(
            record.status == "success" and record.interface_id in {
                "balance_sheet_report", "profit_sheet_report", "cashflow_sheet_report"
            } for record in records
        ),
        "fund_flow_success_count": sum(
            record.status == "success"
            and record.interface_id == "individual_fund_flow" for record in records
        ),
        "potential_lookahead_count": sum(
            bool(row["potential_lookahead"]) for row in point_rows
        ),
        "warnings": [
            "Fund-flow results expose a limited upstream window.",
            "Raw is current retrieval output, not strict historical point-in-time data.",
        ],
        "errors": [
            f"{record.symbol}/{record.interface_id}: {record.error_type}"
            for record in records if record.status != "success"
        ],
        "resume_selected_task_count": sum(
            prior.status != "success" or not prior.raw_path
            for prior in previous.values()
        ) if resume else 0,
    }
    _write_json(run_path, report)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(_documentation(actual_run_id, status), encoding="utf-8")
    repair_paths: list[Path] = []
    if resume:
        current = {
            (record.symbol, record.interface_id): record for record in records
        }
        failed_before = [
            prior for prior in previous.values() if prior.status != "success"
        ]
        repair_rows = []
        for prior in failed_before:
            repaired = current[(prior.symbol, prior.interface_id)]
            repair_rows.append({
                "symbol": prior.symbol,
                "interface_id": prior.interface_id,
                "previous_status": prior.status,
                "previous_error_type": prior.error_type,
                "repair_status": repaired.status,
                "row_count": repaired.row_count,
                "column_count": repaired.column_count,
                "raw_path": repaired.raw_path,
                "schema_hash": repaired.schema_hash,
                "attempt_count": repaired.attempt_count,
                "stdout_log_path": repaired.stdout_log_path,
                "stderr_log_path": repaired.stderr_log_path,
            })
        repair_csv = root / "reports/stage4_repair_task_results.csv"
        repair_json = root / "reports/stage4_repair.json"
        repair_doc = root / "docs/stage4_repair.md"
        _write_csv(repair_csv, repair_rows, (
            "symbol", "interface_id", "previous_status", "previous_error_type",
            "repair_status", "row_count", "column_count", "raw_path",
            "schema_hash", "attempt_count", "stdout_log_path", "stderr_log_path",
        ))
        repair_status = (
            "PASS"
            if len(repair_rows) == 13
            and all(row["repair_status"] == "success" for row in repair_rows)
            else "PARTIAL"
        )
        _write_json(repair_json, {
            "stage": 4,
            "run_id": actual_run_id,
            "repair_status": repair_status,
            "previous_success_count": len(previous) - len(failed_before),
            "selected_task_count": len(failed_before),
            "repaired_success_count": sum(
                row["repair_status"] == "success" for row in repair_rows
            ),
            "remaining_failed_count": sum(
                row["repair_status"] != "success" for row in repair_rows
            ),
            "final_success_count": success_count,
            "final_failed_count": failed_count,
            "final_raw_file_count": sum(bool(record.raw_path) for record in records),
            "historical_failure_evidence_preserved": all(
                (manifest_path.parent / name).exists()
                for name in (
                    "initial_failure_coverage.csv",
                    "initial_failure_run.json",
                    "initial_failure_manifest.json",
                )
            ),
        })
        repair_doc.parent.mkdir(parents=True, exist_ok=True)
        repair_doc.write_text(
            "# 阶段4输出管道修复\n\n"
            f"- Run ID：`{actual_run_id}`\n"
            f"- 修复状态：**{repair_status}**\n"
            f"- 仅复测任务：{len(repair_rows)}\n"
            f"- 复测成功：{sum(row['repair_status'] == 'success' for row in repair_rows)}\n"
            f"- 最终覆盖：{success_count}/{total}\n\n"
            "AKShare stdout/stderr 已重定向到任务级 UTF-8 日志，控制台管道"
            "关闭不会再使已成功的上游 DataFrame 或 Raw 写入失败。\n",
            encoding="utf-8",
        )
        repair_paths = [repair_csv, repair_json, repair_doc]
    raw_paths = sorted({record.raw_path for record in records if record.raw_path})
    report_files = [
        coverage_path, run_path, core_path, fund_path, point_path, doc_path,
        *repair_paths,
    ]
    manifest = {
        "run_id": actual_run_id, "created_at": clock().isoformat(),
        "as_of_date": as_of_date.isoformat(), "start_year": derived_year,
        "python_version": platform.python_version(),
        "akshare_version": fa.akshare_version, "git_commit": _git_commit(root),
        "stock_count": len(stocks), "interface_count": len(interfaces),
        "expected_task_count": total,
        "status_counts": dict(Counter(record.status for record in records)),
        "raw_file_count": len(raw_paths),
        "raw_files": [file_record(root / path, root) for path in raw_paths],
        "report_files": [file_record(path, root) for path in report_files],
    }
    _write_json(manifest_path, manifest)
    report["manifest_path"] = manifest_path.resolve().relative_to(root).as_posix()
    return report, 0 if status == "PASS" else 1
