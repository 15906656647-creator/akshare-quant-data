"""Collection and Raw acceptance checks for Stage 3 market data."""
from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..adapters.stock_market import StockMarketAdapter
from ..storage.raw_store import RawStore, schema_hash

REQUIRED_HISTORY_COLUMNS = ("日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额")
SPOT_FIELDS = (
    "代码",
    "名称",
    "最新价",
    "成交额",
    "振幅",
    "量比",
    "换手率",
    "市盈率-动态",
    "市净率",
    "总市值",
    "流通市值",
)


@dataclass
class DatasetRecord:
    run_id: str
    dataset_id: str
    interface_name: str
    symbol: str
    exchange: str
    adjust: str
    request_parameters: dict[str, Any]
    started_at: str
    finished_at: str
    fetched_at: str
    snapshot_at: str
    as_of_date: str
    akshare_version: str
    python_version: str
    status: str
    row_count: int
    column_count: int
    columns: list[str]
    dtypes: list[str]
    schema_hash: str
    min_date: str
    max_date: str
    raw_path: str
    error_type: str
    error_message: str
    attempt_count: int
    quality_status: str
    warning_count: int
    error_count: int
    quality_issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.isoformat()


def validate_history(
    frame: pd.DataFrame,
    *,
    start_date: date,
    as_of_date: date,
) -> tuple[str, list[str], str, str]:
    warnings: list[str] = []
    errors: list[str] = []
    missing = [column for column in REQUIRED_HISTORY_COLUMNS if column not in frame.columns]
    if missing:
        errors.append("missing_required_columns:" + ",".join(missing))
        return "ERROR", errors, "", ""
    parsed = pd.to_datetime(frame["日期"], errors="coerce")
    if parsed.isna().any():
        errors.append("unparseable_date")
    valid = parsed.dropna()
    min_date = valid.min().date().isoformat() if not valid.empty else ""
    max_date = valid.max().date().isoformat() if not valid.empty else ""
    if not valid.empty and valid.max().date() > as_of_date:
        errors.append("date_later_than_as_of_date")
    if valid.duplicated().any():
        errors.append("duplicate_date")
    if not valid.is_monotonic_increasing:
        warnings.append("date_not_ascending")
    numeric = {
        column: pd.to_numeric(frame[column], errors="coerce")
        for column in ("开盘", "收盘", "最高", "最低", "成交量", "成交额")
    }
    if ((numeric["最高"] < numeric["开盘"]) | (numeric["最高"] < numeric["收盘"])).any():
        errors.append("high_below_open_or_close")
    if ((numeric["最低"] > numeric["开盘"]) | (numeric["最低"] > numeric["收盘"])).any():
        errors.append("low_above_open_or_close")
    if (numeric["最高"] < numeric["最低"]).any():
        errors.append("high_below_low")
    if ((numeric["成交量"] < 0) | (numeric["成交额"] < 0)).any():
        errors.append("negative_volume_or_amount")
    if min_date and date.fromisoformat(min_date) > start_date:
        errors.append("historical_window_not_covered")
    issues = errors + warnings
    return ("ERROR" if errors else "WARN" if warnings else "PASS"), issues, min_date, max_date


class MarketCollector:
    def __init__(
        self,
        *,
        adapter: StockMarketAdapter,
        store: RawStore,
        now: Any,
        project_root: Any,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.now = now
        self.project_root = project_root

    def collect_history(
        self,
        *,
        run_id: str,
        symbol: str,
        exchange: str,
        adjust: str,
        start_date: date,
        as_of_date: date,
    ) -> DatasetRecord:
        started = self.now()
        parameters = {
            "symbol": symbol,
            "period": "daily",
            "start_date": start_date.strftime("%Y%m%d"),
            "end_date": as_of_date.strftime("%Y%m%d"),
            "adjust": adjust,
        }
        call = self.adapter.fetch_history(
            symbol=symbol,
            start_date=parameters["start_date"],
            end_date=parameters["end_date"],
            adjust=adjust,
        )
        finished = self.now()
        frame = call.dataframe
        quality_status = "ERROR"
        issues: list[str] = []
        min_date = ""
        max_date = ""
        raw_path = ""
        status = call.status
        error_type = call.error_type
        error_message = call.error_message
        if frame is not None and not frame.empty:
            quality_status, issues, min_date, max_date = validate_history(
                frame, start_date=start_date, as_of_date=as_of_date
            )
            destination = self.store.history_path(run_id, adjust, symbol)
            self.store.write_parquet(frame, destination)
            raw_path = destination.resolve().relative_to(self.project_root.resolve()).as_posix()
            if quality_status == "ERROR":
                status = "failed"
                error_type = "quality_error"
                error_message = ";".join(issues)
        return DatasetRecord(
            run_id=run_id,
            dataset_id=f"stock_zh_a_hist:{symbol}:{'raw' if adjust == '' else adjust}",
            interface_name="stock_zh_a_hist",
            symbol=symbol,
            exchange=exchange,
            adjust=adjust,
            request_parameters=parameters,
            started_at=_iso(started),
            finished_at=_iso(finished),
            fetched_at=_iso(finished),
            snapshot_at="",
            as_of_date=as_of_date.isoformat(),
            akshare_version=self.adapter.akshare_version,
            python_version=platform.python_version(),
            status=status,
            row_count=0 if frame is None else len(frame),
            column_count=0 if frame is None else len(frame.columns),
            columns=[] if frame is None else [str(x) for x in frame.columns],
            dtypes=[] if frame is None else [str(frame[x].dtype) for x in frame.columns],
            schema_hash=schema_hash(frame),
            min_date=min_date,
            max_date=max_date,
            raw_path=raw_path,
            error_type=error_type,
            error_message=error_message,
            attempt_count=call.attempt_count,
            quality_status=quality_status,
            warning_count=sum(not x.startswith(("missing_", "unparseable_", "date_later_", "duplicate_", "high_", "low_", "negative_", "historical_")) for x in issues),
            error_count=sum(x.startswith(("missing_", "unparseable_", "date_later_", "duplicate_", "high_", "low_", "negative_", "historical_")) for x in issues),
            quality_issues=issues,
        )

    def collect_spot(
        self,
        *,
        run_id: str,
        target_symbols: list[str],
        as_of_date: date,
    ) -> tuple[list[DatasetRecord], dict[str, Any], pd.DataFrame | None]:
        started = self.now()
        call = self.adapter.fetch_spot()
        finished = self.now()
        snapshot_at = _iso(finished)
        frame = call.dataframe
        records: list[DatasetRecord] = []
        summary: dict[str, Any] = {
            "snapshot_at": snapshot_at,
            "full_market_rows": 0,
            "target_count": 0,
            "missing_symbols": list(target_symbols),
            "field_availability": [
                {"field": field, "available": False} for field in SPOT_FIELDS
            ],
            "full_market_raw_path": "",
            "target_raw_path": "",
        }
        if frame is None or frame.empty:
            records.append(
                self._spot_record(
                    run_id, "full_market", frame, call, started, finished,
                    as_of_date, snapshot_at, "", "ERROR", ["spot_not_available"]
                )
            )
            return records, summary, None
        snapshot_date = finished.date().isoformat()
        full_path = self.store.spot_path(run_id, snapshot_date, "full_market.parquet")
        self.store.write_parquet(frame, full_path)
        summary["full_market_rows"] = len(frame)
        summary["full_market_raw_path"] = full_path.resolve().relative_to(
            self.project_root.resolve()
        ).as_posix()
        summary["field_availability"] = [
            {"field": field, "available": field in frame.columns} for field in SPOT_FIELDS
        ]
        if "代码" in frame.columns:
            normalized = frame["代码"].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6)
            target = frame.loc[normalized.isin(target_symbols)].copy()
            target_codes = normalized.loc[target.index]
            target = target.loc[~target_codes.duplicated()].copy()
            found = set(target_codes.loc[target.index])
        else:
            target = frame.iloc[0:0].copy()
            found = set()
        missing = sorted(set(target_symbols) - found)
        target_path = self.store.spot_path(run_id, snapshot_date, "target_16.parquet")
        self.store.write_parquet(target, target_path)
        summary["target_count"] = len(found)
        summary["missing_symbols"] = missing
        summary["target_raw_path"] = target_path.resolve().relative_to(
            self.project_root.resolve()
        ).as_posix()
        field_warnings = [
            f"missing_spot_field:{item['field']}"
            for item in summary["field_availability"]
            if not item["available"]
        ]
        full_quality = "WARN" if field_warnings else "PASS"
        records.append(
            self._spot_record(
                run_id, "full_market", frame, call, started, finished, as_of_date,
                snapshot_at, summary["full_market_raw_path"], full_quality, field_warnings
            )
        )
        for symbol in target_symbols:
            present = symbol in found
            issues = [] if present else ["missing_target_symbol"]
            records.append(
                self._spot_record(
                    run_id, symbol, target if present else None, call, started, finished,
                    as_of_date, snapshot_at, summary["target_raw_path"],
                    "PASS" if present else "ERROR", issues,
                    row_count_override=1 if present else 0,
                )
            )
        return records, summary, target

    def _spot_record(
        self,
        run_id: str,
        symbol: str,
        frame: pd.DataFrame | None,
        call: Any,
        started: datetime,
        finished: datetime,
        as_of_date: date,
        snapshot_at: str,
        raw_path: str,
        quality_status: str,
        issues: list[str],
        row_count_override: int | None = None,
    ) -> DatasetRecord:
        errors = 1 if quality_status == "ERROR" else 0
        warnings = len(issues) if quality_status == "WARN" else 0
        return DatasetRecord(
            run_id=run_id,
            dataset_id=f"stock_zh_a_spot_em:{symbol}",
            interface_name="stock_zh_a_spot_em",
            symbol=symbol,
            exchange="",
            adjust="",
            request_parameters={},
            started_at=_iso(started),
            finished_at=_iso(finished),
            fetched_at=_iso(finished),
            snapshot_at=snapshot_at,
            as_of_date=as_of_date.isoformat(),
            akshare_version=self.adapter.akshare_version,
            python_version=platform.python_version(),
            status="success" if quality_status != "ERROR" else "failed",
            row_count=(0 if frame is None else len(frame)) if row_count_override is None else row_count_override,
            column_count=0 if frame is None else len(frame.columns),
            columns=[] if frame is None else [str(x) for x in frame.columns],
            dtypes=[] if frame is None else [str(frame[x].dtype) for x in frame.columns],
            schema_hash=schema_hash(frame),
            min_date="",
            max_date="",
            raw_path=raw_path,
            error_type=call.error_type if call.status != "success" else ("quality_error" if errors else ""),
            error_message=call.error_message if call.status != "success" else (";".join(issues) if errors else ""),
            attempt_count=call.attempt_count,
            quality_status=quality_status,
            warning_count=warnings,
            error_count=errors,
            quality_issues=issues,
        )
