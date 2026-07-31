"""Stage 4 collector: preserve Raw frames and produce descriptive evidence."""
from __future__ import annotations

import json
import platform
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..adapters.stock_finance import OutputCapture
from ..storage.raw_store import RawStore, schema_hash

REPORT_DATE_TOKENS = ("报告期", "报告日期", "REPORT_DATE", "REPORTDATE", "截止日期")
ANNOUNCEMENT_DATE_TOKENS = (
    "公告日期", "公告日", "NOTICE_DATE", "ANNOUNCEMENT_DATE", "UPDATE_DATE"
)
FUND_DATE_TOKENS = ("日期", "交易日期", "trade_date", "date")

CORE_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "报告期": REPORT_DATE_TOKENS,
    "公告日期": ANNOUNCEMENT_DATE_TOKENS,
    "营业收入或营业总收入": ("营业收入", "营业总收入", "TOTAL_OPERATE_INCOME", "OPERATE_INCOME"),
    "净利润": ("净利润", "NETPROFIT"),
    "归属于母公司股东的净利润": ("归母净利润", "归属于母公司", "PARENT_NETPROFIT"),
    "基本每股收益": ("基本每股收益", "BASIC_EPS"),
    "净资产收益率": ("净资产收益率", "ROE"),
    "资产总计": ("资产总计", "TOTAL_ASSETS"),
    "负债合计": ("负债合计", "TOTAL_LIABILITIES"),
    "经营活动产生的现金流量净额": ("经营活动产生的现金流量净额", "NETCASH_OPERATE"),
}


def _matches(columns: list[Any], tokens: tuple[str, ...]) -> list[str]:
    return [
        str(column) for column in columns
        if any(token.casefold() in str(column).casefold() for token in tokens)
    ]


_DATE_LABEL = re.compile(r"^(?:19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?$")


def _is_date_label(value: Any) -> bool:
    return bool(_DATE_LABEL.match(str(value).strip()))


def detect_date_columns(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    columns = list(frame.columns)
    report = _matches(columns, REPORT_DATE_TOKENS)
    # stock_financial_abstract commonly returns report periods as column labels.
    report.extend(
        str(column) for column in columns
        if _is_date_label(column) and str(column) not in report
    )
    return report, _matches(columns, ANNOUNCEMENT_DATE_TOKENS)


def _date_range(frame: pd.DataFrame, columns: list[str]) -> tuple[str, str]:
    values: list[pd.Timestamp] = []
    for column in columns:
        if _is_date_label(column):
            parsed_label = pd.to_datetime(str(column), errors="coerce")
            if not pd.isna(parsed_label):
                values.append(parsed_label)
        elif column in frame.columns:
            parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
            values.extend(parsed.tolist())
    if not values:
        return "", ""
    return min(values).date().isoformat(), max(values).date().isoformat()


@dataclass
class FinancialRecord:
    run_id: str
    dataset_id: str
    interface_id: str
    interface_name: str
    symbol: str
    exchange: str
    symbol_plain: str
    symbol_em: str
    market_lower: str
    request_parameters: str
    started_at: str
    finished_at: str
    fetched_at: str
    as_of_date: str
    start_year: str
    akshare_version: str
    python_version: str
    status: str
    row_count: int
    column_count: int
    columns: str
    dtypes: str
    schema_hash: str
    detected_report_date_columns: str
    detected_announcement_date_columns: str
    min_report_date: str
    max_report_date: str
    min_announcement_date: str
    max_announcement_date: str
    raw_path: str
    error_type: str
    error_message: str
    root_exception_class: str
    target_host: str
    attempt_count: int
    quality_status: str
    warning_count: int
    error_count: int
    elapsed_seconds: float
    upstream_call_status: str = ""
    raw_write_status: str = ""
    evidence_write_status: str = ""
    console_output_status: str = ""
    output_capture_status: str = ""
    stdout_log_path: str = ""
    stderr_log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FinancialCollector:
    def __init__(
        self,
        *,
        finance_adapter: Any,
        fund_flow_adapter: Any,
        store: RawStore,
        now: Any,
        project_root: Path,
    ) -> None:
        self.finance_adapter = finance_adapter
        self.fund_flow_adapter = fund_flow_adapter
        self.store = store
        self.now = now
        self.project_root = project_root

    def collect(
        self,
        *,
        run_id: str,
        interface_id: str,
        interface_name: str,
        stock: Any,
        as_of_date: date,
        start_year: str,
    ) -> tuple[FinancialRecord, pd.DataFrame | None]:
        started = self.now()
        capture = self._output_capture(run_id, stock.symbol, interface_id)
        parameters, call = self._dispatch(
            interface_id, stock, start_year, capture
        )
        finished = self.now()
        frame = call.dataframe
        report_columns: list[str] = []
        announcement_columns: list[str] = []
        min_report = max_report = min_announcement = max_announcement = ""
        warnings = 0
        errors = 0
        raw_path = ""
        raw_write_status = "not_attempted"
        if frame is not None:
            report_columns, announcement_columns = detect_date_columns(frame)
            min_report, max_report = _date_range(frame, report_columns)
            min_announcement, max_announcement = _date_range(
                frame, announcement_columns
            )
        if call.status == "success" and frame is not None:
            destination = self.store.financial_path(
                interface_name, run_id, stock.symbol
            )
            try:
                self.store.write_parquet(frame, destination)
                raw_write_status = "success"
                raw_path = destination.resolve().relative_to(
                    self.project_root.resolve()
                ).as_posix()
                if interface_id != "individual_fund_flow" and not report_columns:
                    warnings += 1
            except Exception as exc:
                raw_write_status = "failed"
                call.status = "failed"
                call.error_type = "raw_write_error"
                call.error_message = str(exc).replace("\r", " ").replace("\n", " ")[:240]
                errors = 1
        else:
            errors = 1
        quality = "ERROR" if errors else ("WARN" if warnings else "PASS")
        record = FinancialRecord(
            run_id=run_id,
            dataset_id=f"{interface_name}:{stock.symbol}",
            interface_id=interface_id,
            interface_name=interface_name,
            symbol=stock.symbol,
            exchange=stock.exchange,
            symbol_plain=stock.symbol,
            symbol_em=stock.symbol_em,
            market_lower=stock.market_lower,
            request_parameters=json.dumps(
                parameters, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")
            ),
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            fetched_at=finished.isoformat(),
            as_of_date=as_of_date.isoformat(),
            start_year=start_year,
            akshare_version=self.finance_adapter.akshare_version,
            python_version=platform.python_version(),
            status=call.status,
            row_count=0 if frame is None else len(frame),
            column_count=0 if frame is None else len(frame.columns),
            columns=json.dumps(
                [] if frame is None else [str(x) for x in frame.columns],
                ensure_ascii=False,
            ),
            dtypes=json.dumps(
                [] if frame is None else [str(x) for x in frame.dtypes],
                ensure_ascii=False,
            ),
            schema_hash=schema_hash(frame),
            detected_report_date_columns=json.dumps(
                report_columns, ensure_ascii=False
            ),
            detected_announcement_date_columns=json.dumps(
                announcement_columns, ensure_ascii=False
            ),
            min_report_date=min_report,
            max_report_date=max_report,
            min_announcement_date=min_announcement,
            max_announcement_date=max_announcement,
            raw_path=raw_path,
            error_type=call.error_type,
            error_message=call.error_message,
            root_exception_class=call.root_exception_class,
            target_host=call.target_host,
            attempt_count=call.attempt_count,
            quality_status=quality,
            warning_count=warnings,
            error_count=errors,
            elapsed_seconds=max(0.0, (finished - started).total_seconds()),
            upstream_call_status=(
                "success" if frame is not None and not frame.empty else call.status
            ),
            raw_write_status=raw_write_status,
            evidence_write_status="pending",
            console_output_status=(
                "warning"
                if call.output_capture_status == "console_output_warning"
                else "success"
            ),
            output_capture_status=call.output_capture_status,
            stdout_log_path=call.stdout_log_path,
            stderr_log_path=call.stderr_log_path,
        )
        return record, frame

    def _output_capture(
        self, run_id: str, symbol: str, interface_id: str
    ) -> OutputCapture:
        relative_root = Path("logs") / "upstream" / "stage4" / run_id
        stdout_relative = relative_root / f"{symbol}_{interface_id}.stdout.log"
        stderr_relative = relative_root / f"{symbol}_{interface_id}.stderr.log"
        return OutputCapture(
            stdout_path=self.project_root / stdout_relative,
            stderr_path=self.project_root / stderr_relative,
            stdout_log_path=stdout_relative.as_posix(),
            stderr_log_path=stderr_relative.as_posix(),
        )

    def _dispatch(
        self,
        interface_id: str,
        stock: Any,
        start_year: str,
        output_capture: OutputCapture,
    ) -> tuple[dict[str, str], Any]:
        if interface_id == "financial_abstract":
            parameters = {"symbol": stock.symbol}
            return parameters, self.finance_adapter.fetch_financial_abstract(
                stock.symbol, output_capture=output_capture
            )
        if interface_id == "financial_indicator":
            parameters = {"symbol": stock.symbol, "start_year": start_year}
            return parameters, self.finance_adapter.fetch_financial_indicator(
                stock.symbol, start_year, output_capture=output_capture
            )
        if interface_id == "balance_sheet_report":
            parameters = {"symbol": stock.symbol_em}
            return parameters, self.finance_adapter.fetch_balance_sheet(
                stock.symbol_em, output_capture=output_capture
            )
        if interface_id == "profit_sheet_report":
            parameters = {"symbol": stock.symbol_em}
            return parameters, self.finance_adapter.fetch_profit_sheet(
                stock.symbol_em, output_capture=output_capture
            )
        if interface_id == "cashflow_sheet_report":
            parameters = {"symbol": stock.symbol_em}
            return parameters, self.finance_adapter.fetch_cashflow_sheet(
                stock.symbol_em, output_capture=output_capture
            )
        if interface_id == "individual_fund_flow":
            parameters = {"stock": stock.symbol, "market": stock.market_lower}
            return parameters, self.fund_flow_adapter.fetch_individual_fund_flow(
                stock.symbol,
                stock.market_lower,
                output_capture=output_capture,
            )
        raise ValueError(f"Unknown Stage 4 interface: {interface_id}")


def core_field_rows(
    run_id: str,
    symbol: str,
    frames: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for concept, candidates in CORE_FIELD_CANDIDATES.items():
        matches: list[tuple[str, str, int]] = []
        for interface_id, frame in frames.items():
            for field in _matches(list(frame.columns), candidates):
                matches.append((interface_id, field, int(frame[field].notna().sum())))
            # Some AKShare wide tables put metric names in rows and periods in columns.
            for column in frame.columns:
                values = frame[column].astype(str)
                mask = values.map(
                    lambda value: any(
                        token.casefold() in str(value).casefold()
                        for token in candidates
                    )
                )
                for index in frame.index[mask]:
                    non_null = int(
                        frame.loc[index].drop(labels=[column]).notna().sum()
                    )
                    matches.append(
                        (
                            interface_id,
                            f"row:{frame.at[index, column]}",
                            non_null,
                        )
                    )
        rows.append(
            {
                "run_id": run_id,
                "symbol": symbol,
                "concept": concept,
                "candidate_source_interface": "|".join(
                    sorted({item[0] for item in matches})
                ),
                "matched_source_fields": "|".join(item[1] for item in matches),
                "availability_status": (
                    "available_non_null" if any(x[2] for x in matches)
                    else ("field_present_all_null" if matches else "unavailable")
                ),
                "non_null_count": sum(item[2] for item in matches),
                "notes": "field recognition only; no source merging or calculation",
            }
        )
    return rows
