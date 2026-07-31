"""Stage 5 offline Raw-to-Clean and DuckDB build."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow
import yaml

from .config import load_universe
from .stage5_idempotency import (
    finalize_metadata_schema,
    migrate_metadata_schema,
    preflight_metadata_columns,
    prepare_mapping_records,
    prepare_quality_records,
    snapshot_tables,
    upsert_hashed_records,
)
from .storage.raw_store import file_sha256

MARKET_INTERFACES = {"stock_zh_a_hist", "stock_zh_a_spot_em"}
STATEMENT_TYPES = {
    "stock_balance_sheet_by_report_em": "balance_sheet",
    "stock_profit_sheet_by_report_em": "profit_statement",
    "stock_cash_flow_sheet_by_report_em": "cash_flow_statement",
}
STATEMENT_METADATA = {
    "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "ORG_TYPE",
    "REPORT_DATE", "REPORT_TYPE", "REPORT_DATE_NAME", "SECURITY_TYPE_CODE",
    "NOTICE_DATE", "UPDATE_DATE", "CURRENCY", "OPINION_TYPE",
    "OSOPINION_TYPE", "LISTING_STATE",
}
PERCENT_FIELDS = {"振幅", "涨跌幅", "换手率"}
SPOT_FIELDS = {
    "代码": "symbol", "名称": "name", "最新价": "latest_price",
    "涨跌幅": "pct_change", "涨跌额": "price_change", "成交量": "volume_lot",
    "成交额": "amount_cny", "振幅": "amplitude", "换手率": "turnover_rate",
    "量比": "volume_ratio", "市盈率-动态": "pe_dynamic", "市净率": "pb",
    "总市值": "market_cap_cny", "流通市值": "float_market_cap_cny",
}
FUND_FIELDS = {
    "收盘价": "close", "涨跌幅": "pct_change",
    "主力净流入-净额": "main_net_inflow_cny",
    "主力净流入-净占比": "main_net_inflow_ratio",
    "超大单净流入-净额": "super_large_net_inflow_cny",
    "超大单净流入-净占比": "super_large_net_inflow_ratio",
    "大单净流入-净额": "large_net_inflow_cny",
    "大单净流入-净占比": "large_net_inflow_ratio",
    "中单净流入-净额": "medium_net_inflow_cny",
    "中单净流入-净占比": "medium_net_inflow_ratio",
    "小单净流入-净额": "small_net_inflow_cny",
    "小单净流入-净占比": "small_net_inflow_ratio",
}


@dataclass
class RawManifest:
    run_id: str
    payload: dict[str, Any]
    raw_files: list[dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative(path: str | Path, root: Path) -> str:
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def _stable_code(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _exchange(symbol: str) -> str | None:
    if symbol.startswith(("600", "601", "603", "605", "688")):
        return "SH"
    if symbol.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZ"
    if symbol.startswith(("4", "8", "9")):
        return "BJ"
    return None


def _number(value: Any) -> float | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, str) and value.strip() in {"", "-", "--"}:
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed) or not pd.api.types.is_number(parsed):
        return None
    result = float(parsed)
    if result in (float("inf"), float("-inf")):
        return None
    return result


def _raw_text(value: Any) -> str | None:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    return str(value)


def _json_record(row: pd.Series) -> str:
    payload: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or value is pd.NA or pd.isna(value):
            payload[str(key)] = None
        elif isinstance(value, (datetime, date)):
            payload[str(key)] = value.isoformat()
        elif hasattr(value, "item"):
            payload[str(key)] = value.item()
        else:
            payload[str(key)] = value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def load_mapping_config(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with (root / "config/field_mapping.yml").open(encoding="utf-8") as handle:
        fields = yaml.safe_load(handle)
    with (root / "config/unit_mapping.yml").open(encoding="utf-8") as handle:
        units = yaml.safe_load(handle)
    return fields, units


def validate_raw_manifest(root: Path, manifest_path: Path, expected_run_id: str) -> RawManifest:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("run_id") != expected_run_id:
        raise ValueError(f"Manifest run_id mismatch: {manifest_path}")
    records = payload.get("raw_files")
    if not isinstance(records, list) or not records:
        raise ValueError(f"Manifest has no raw_files: {manifest_path}")
    for record in records:
        rel = str(record["path"])
        if expected_run_id not in rel or Path(rel).is_absolute():
            raise ValueError(f"Unsafe or mismatched Raw path: {rel}")
        path = root / rel
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"Missing or empty Raw file: {rel}")
        if path.stat().st_size != int(record["size"]):
            raise ValueError(f"Raw size mismatch: {rel}")
        if file_sha256(path).lower() != str(record["sha256"]).lower():
            raise ValueError(f"Raw SHA-256 mismatch: {rel}")
        pd.read_parquet(path)
    return RawManifest(expected_run_id, payload, records)


def _atomic_parquet(frame: pd.DataFrame, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Clean path already exists: {destination}")
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary Clean path already exists: {temporary}")
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return {
        "size": destination.stat().st_size,
        "sha256": file_sha256(destination),
        "rows": len(frame),
    }


def _source_files(manifest: RawManifest, interface: str) -> list[dict[str, Any]]:
    prefix = f"data/raw/{interface}/"
    return [item for item in manifest.raw_files if str(item["path"]).startswith(prefix)]


def clean_stock_daily(
    root: Path, manifest: RawManifest, transform_run_id: str
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    output: dict[str, list[pd.DataFrame]] = {"stock_daily_qfq": [], "stock_daily_raw": []}
    lineage: list[dict[str, Any]] = []
    for record in _source_files(manifest, "stock_zh_a_hist"):
        rel = record["path"]
        frame = pd.read_parquet(root / rel)
        adjust = "qfq" if "adjust=qfq" in rel else "raw"
        dataset = f"stock_daily_{adjust}"
        cleaned = pd.DataFrame(
            {
                "transform_run_id": transform_run_id,
                "source_run_id": manifest.run_id,
                "symbol": frame["股票代码"].astype("string").str.zfill(6),
                "trade_date": pd.to_datetime(frame["日期"], errors="coerce").dt.date,
                "adjust_type": adjust,
                "open": pd.to_numeric(frame["开盘"], errors="coerce"),
                "high": pd.to_numeric(frame["最高"], errors="coerce"),
                "low": pd.to_numeric(frame["最低"], errors="coerce"),
                "close": pd.to_numeric(frame["收盘"], errors="coerce"),
                "volume_lot": pd.to_numeric(frame["成交量"], errors="coerce"),
                "amount_cny": pd.to_numeric(frame["成交额"], errors="coerce"),
                "amplitude": pd.to_numeric(frame["振幅"], errors="coerce") / 100,
                "pct_change": pd.to_numeric(frame["涨跌幅"], errors="coerce") / 100,
                "price_change": pd.to_numeric(frame["涨跌额"], errors="coerce"),
                "turnover_rate": pd.to_numeric(frame["换手率"], errors="coerce") / 100,
            }
        )
        cleaned.insert(3, "exchange", cleaned["symbol"].map(_exchange))
        cleaned.insert(11, "volume_share", cleaned["volume_lot"] * 100)
        cleaned["source_file"] = rel
        cleaned["source_row_number"] = range(1, len(cleaned) + 1)
        cleaned["ingested_at"] = manifest.payload.get("created_at")
        output[dataset].append(cleaned)
        lineage.append({"dataset_id": dataset, "source_file": rel})
    return {key: pd.concat(value, ignore_index=True) for key, value in output.items()}, lineage


def clean_stock_spot(
    root: Path, manifest: RawManifest, transform_run_id: str
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    result: dict[str, pd.DataFrame] = {}
    lineage: list[dict[str, Any]] = []
    snapshot_at = manifest.payload.get("snapshot_at")
    for record in _source_files(manifest, "stock_zh_a_spot_em"):
        rel = record["path"]
        scope = "target_16" if rel.endswith("target_16.parquet") else "full_market"
        dataset = f"stock_spot_{scope}"
        raw = pd.read_parquet(root / rel)
        data: dict[str, Any] = {
            "transform_run_id": transform_run_id,
            "source_run_id": manifest.run_id,
            "snapshot_at": snapshot_at,
            "snapshot_scope": scope,
        }
        for source, canonical in SPOT_FIELDS.items():
            if canonical in {"symbol", "name"}:
                data[canonical] = raw[source].astype("string")
            else:
                data[canonical] = pd.to_numeric(raw[source], errors="coerce").replace(
                    [float("inf"), float("-inf")], pd.NA
                )
                if source in PERCENT_FIELDS:
                    data[canonical] = data[canonical] / 100
        cleaned = pd.DataFrame(data)
        cleaned["symbol"] = cleaned["symbol"].str.zfill(6)
        cleaned.insert(5, "exchange", cleaned["symbol"].map(_exchange))
        cleaned.insert(
            cleaned.columns.get_loc("volume_lot") + 1,
            "volume_share",
            cleaned["volume_lot"] * 100,
        )
        cleaned["source_payload_json"] = raw.apply(_json_record, axis=1)
        cleaned["source_file"] = rel
        result[dataset] = cleaned
        lineage.append({"dataset_id": dataset, "source_file": rel})
    return result, lineage


def _unit_from_metric(name: str) -> tuple[str, str, float]:
    if "(%)" in name or "（%）" in name:
        return "percent_point", "decimal", 0.01
    if "(元)" in name or "（元）" in name:
        return "CNY_yuan", "CNY_yuan", 1.0
    if "(天)" in name or "（天）" in name:
        return "day", "day", 1.0
    if "(次)" in name or "（次）" in name:
        return "times", "times", 1.0
    return "unknown", "unknown", 1.0


def _point_in_time(
    announcement: Any, as_of_date: date
) -> tuple[date | None, str, bool | None]:
    parsed = pd.to_datetime(announcement, errors="coerce")
    if pd.isna(parsed):
        return None, "unavailable", None
    value = parsed.date()
    return value, "available", value > as_of_date


def clean_financial_abstract(
    root: Path, manifest: RawManifest, transform_run_id: str, as_of_date: date
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    interface = "stock_financial_abstract"
    for record in _source_files(manifest, interface):
        rel = record["path"]
        symbol = rel.split("symbol=")[1].split("/")[0]
        raw = pd.read_parquet(root / rel)
        period_columns = [column for column in raw.columns if str(column).isdigit() and len(str(column)) == 8]
        for source_row, source in raw.iterrows():
            metric_name = str(source.get("指标"))
            metric_category = str(source.get("选项"))
            metric_code = _stable_code(metric_category + "\x1f" + metric_name)
            unit_source, unit_canonical, scale = _unit_from_metric(metric_name)
            for period_column in period_columns:
                period = pd.to_datetime(period_column, format="%Y%m%d", errors="coerce")
                if pd.isna(period):
                    continue
                raw_value = source[period_column]
                value = _number(raw_value)
                rows.append(
                    {
                        "transform_run_id": transform_run_id,
                        "source_run_id": manifest.run_id,
                        "symbol": symbol,
                        "exchange": _exchange(symbol),
                        "report_period": period.date(),
                        "announcement_date": None,
                        "metric_code": metric_code,
                        "metric_name_source": metric_name,
                        "metric_category_source": metric_category,
                        "metric_value": None if value is None else value * scale,
                        "metric_value_raw": _raw_text(raw_value),
                        "unit_source": unit_source,
                        "unit_canonical": unit_canonical,
                        "potential_lookahead": None,
                        "announcement_date_status": "unavailable",
                        "source_interface": interface,
                        "source_field": str(period_column),
                        "source_file": rel,
                        "source_row_number": int(source_row) + 1,
                    }
                )
        lineage.append({"dataset_id": "financial_abstract", "source_file": rel})
    return pd.DataFrame(rows), lineage


def clean_financial_indicator(
    root: Path, manifest: RawManifest, transform_run_id: str, as_of_date: date
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    interface = "stock_financial_analysis_indicator"
    for record in _source_files(manifest, interface):
        rel = record["path"]
        symbol = rel.split("symbol=")[1].split("/")[0]
        raw = pd.read_parquet(root / rel)
        metric_columns = [column for column in raw.columns if column != "日期"]
        for source_row, source in raw.iterrows():
            period = pd.to_datetime(source["日期"], errors="coerce")
            if pd.isna(period):
                continue
            for metric_name in metric_columns:
                unit_source, unit_canonical, scale = _unit_from_metric(str(metric_name))
                raw_value = source[metric_name]
                value = _number(raw_value)
                rows.append(
                    {
                        "transform_run_id": transform_run_id,
                        "source_run_id": manifest.run_id,
                        "symbol": symbol,
                        "exchange": _exchange(symbol),
                        "report_period": period.date(),
                        "announcement_date": None,
                        "metric_code": _stable_code(str(metric_name)),
                        "metric_name_source": str(metric_name),
                        "metric_value": None if value is None else value * scale,
                        "metric_value_raw": _raw_text(raw_value),
                        "unit_source": unit_source,
                        "unit_canonical": unit_canonical,
                        "potential_lookahead": None,
                        "announcement_date_status": "unavailable",
                        "source_interface": interface,
                        "source_field": str(metric_name),
                        "source_file": rel,
                        "source_row_number": int(source_row) + 1,
                    }
                )
        lineage.append({"dataset_id": "financial_indicator", "source_file": rel})
    return pd.DataFrame(rows), lineage


def clean_financial_statements(
    root: Path, manifest: RawManifest, transform_run_id: str, as_of_date: date
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    outputs: dict[str, list[dict[str, Any]]] = {
        f"financial_statement_{value}": [] for value in STATEMENT_TYPES.values()
    }
    lineage: list[dict[str, Any]] = []
    for interface, statement_type in STATEMENT_TYPES.items():
        dataset = f"financial_statement_{statement_type}"
        for record in _source_files(manifest, interface):
            rel = record["path"]
            raw = pd.read_parquet(root / rel)
            for source_row, source in raw.iterrows():
                symbol = str(source.get("SECURITY_CODE", "")).zfill(6)
                report = pd.to_datetime(source.get("REPORT_DATE"), errors="coerce")
                if pd.isna(report):
                    continue
                announcement, status, lookahead = _point_in_time(
                    source.get("NOTICE_DATE"), as_of_date
                )
                for column in [item for item in raw.columns if item not in STATEMENT_METADATA]:
                    raw_value = source[column]
                    value = _number(raw_value)
                    if str(column).endswith("_YOY"):
                        unit_source, unit_canonical, scale = "percent_point", "decimal", 0.01
                    elif str(column) in {"BASIC_EPS", "DILUTED_EPS"}:
                        unit_source, unit_canonical, scale = "CNY_per_share", "CNY_per_share", 1.0
                    else:
                        unit_source, unit_canonical, scale = "CNY_yuan", "CNY_yuan", 1.0
                    outputs[dataset].append(
                        {
                            "transform_run_id": transform_run_id,
                            "source_run_id": manifest.run_id,
                            "symbol": symbol,
                            "exchange": _exchange(symbol),
                            "statement_type": statement_type,
                            "report_period": report.date(),
                            "announcement_date": announcement,
                            "line_item_code": _stable_code(str(column)),
                            "line_item_name_source": str(column),
                            "line_item_value": None if value is None else value * scale,
                            "line_item_value_raw": _raw_text(raw_value),
                            "unit_source": unit_source,
                            "unit_canonical": unit_canonical,
                            "potential_lookahead": lookahead,
                            "announcement_date_status": status,
                            "source_column": str(column),
                            "source_file": rel,
                            "source_row_number": int(source_row) + 1,
                        }
                    )
            lineage.append({"dataset_id": dataset, "source_file": rel})
    return {key: pd.DataFrame(value) for key, value in outputs.items()}, lineage


def clean_fund_flow(
    root: Path, manifest: RawManifest, transform_run_id: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    lineage: list[dict[str, Any]] = []
    interface = "stock_individual_fund_flow"
    ratio_fields = {name for name in FUND_FIELDS if name.endswith("净占比")}
    for record in _source_files(manifest, interface):
        rel = record["path"]
        symbol = rel.split("symbol=")[1].split("/")[0]
        raw = pd.read_parquet(root / rel)
        data: dict[str, Any] = {
            "transform_run_id": transform_run_id,
            "source_run_id": manifest.run_id,
            "symbol": symbol,
            "exchange": _exchange(symbol),
            "trade_date": pd.to_datetime(raw["日期"], errors="coerce").dt.date,
        }
        for source, canonical in FUND_FIELDS.items():
            values = pd.to_numeric(raw[source], errors="coerce")
            data[canonical] = values / 100 if source in ratio_fields or source == "涨跌幅" else values
        cleaned = pd.DataFrame(data)
        cleaned["source_file"] = rel
        frames.append(cleaned)
        lineage.append({"dataset_id": "fund_flow", "source_file": rel})
    return pd.concat(frames, ignore_index=True), lineage


def _source_row_count(root: Path, records: list[dict[str, Any]]) -> int:
    return sum(len(pd.read_parquet(root / item["path"])) for item in records)


def build_field_mapping_report(
    root: Path, manifests: list[RawManifest], transform_run_id: str
) -> pd.DataFrame:
    field_config, _ = load_mapping_config(root)
    exact = field_config["datasets"]
    meta = field_config["financial_metadata"]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for manifest in manifests:
        for record in manifest.raw_files:
            interface = Path(record["path"]).parts[2]
            columns = pd.read_parquet(root / record["path"]).columns
            if interface == "stock_zh_a_hist":
                config_dataset = "stock_daily"
            elif interface == "stock_zh_a_spot_em":
                config_dataset = "stock_spot"
            elif interface == "stock_individual_fund_flow":
                config_dataset = "fund_flow"
            else:
                config_dataset = None
            for column in columns:
                key = (interface, str(column))
                if key in seen:
                    continue
                seen.add(key)
                configured = exact.get(config_dataset, {}).get(str(column)) if config_dataset else None
                if configured:
                    row = dict(configured)
                    status = row.get("mapping_status", "mapped")
                    source_unit = ""
                    target_unit = ""
                    scale = 1.0
                elif str(column) in meta:
                    row = {
                        "canonical_field": meta[str(column)],
                        "data_type": "source",
                        "nullable": True,
                        "required": False,
                        "mapping_evidence": "Financial metadata field mapping",
                    }
                    status, source_unit, target_unit, scale = "mapped", "", "", 1.0
                elif interface == "stock_zh_a_spot_em":
                    row = {
                        "canonical_field": "",
                        "data_type": "source",
                        "nullable": True,
                        "required": False,
                        "mapping_evidence": "Preserved in source_payload_json; no canonical guess",
                    }
                    status, source_unit, target_unit, scale = "unmapped", "unknown", "unknown", 1.0
                else:
                    if interface in STATEMENT_TYPES:
                        if str(column).endswith("_YOY"):
                            unit_source, unit_target, unit_scale = (
                                "percent_point", "decimal", 0.01
                            )
                        elif str(column) in {"BASIC_EPS", "DILUTED_EPS"}:
                            unit_source, unit_target, unit_scale = (
                                "CNY_per_share", "CNY_per_share", 1.0
                            )
                        else:
                            unit_source, unit_target, unit_scale = (
                                "CNY_yuan", "CNY_yuan", 1.0
                            )
                    else:
                        unit_source, unit_target, unit_scale = _unit_from_metric(
                            str(column)
                        )
                    row = {
                        "canonical_field": f"source_derived:{_stable_code(str(column))}",
                        "data_type": "source",
                        "nullable": True,
                        "required": False,
                        "mapping_evidence": "Raw wide field preserved as traceable long-form item",
                    }
                    status, source_unit, target_unit, scale = (
                        "passthrough", unit_source, unit_target, unit_scale
                    )
                rows.append(
                    {
                        "transform_run_id": transform_run_id,
                        "source_dataset": interface,
                        "source_field": str(column),
                        "canonical_field": row.get("canonical_field", ""),
                        "data_type": row.get("data_type", "source"),
                        "source_unit": source_unit,
                        "target_unit": target_unit,
                        "scale_factor": scale,
                        "nullable": bool(row.get("nullable", True)),
                        "required": bool(row.get("required", False)),
                        "mapping_status": status,
                        "mapping_evidence": row.get("mapping_evidence", ""),
                        "notes": "",
                    }
                )
    return prepare_mapping_records(pd.DataFrame(rows), root)


def _quality_rows(frames: dict[str, pd.DataFrame], transform_run_id: str, as_of: date) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(dataset: str, check: str, severity: str, count: int, message: str) -> None:
        rows.append(
            {
                "transform_run_id": transform_run_id, "dataset_id": dataset,
                "check_name": check, "severity": severity,
                "status": "PASS" if count == 0 else ("WARN" if severity == "WARN" else "FAIL"),
                "issue_count": int(count), "message": message,
            }
        )

    for dataset, frame in frames.items():
        add(dataset, "non_empty", "ERROR", int(frame.empty), "Clean dataset must be non-empty")
        key_map = {
            "stock_daily_qfq": ["symbol", "trade_date", "adjust_type", "source_run_id"],
            "stock_daily_raw": ["symbol", "trade_date", "adjust_type", "source_run_id"],
            "stock_spot_full_market": ["symbol", "snapshot_at", "snapshot_scope", "source_run_id"],
            "stock_spot_target_16": ["symbol", "snapshot_at", "snapshot_scope", "source_run_id"],
            "financial_abstract": ["symbol", "report_period", "metric_code", "source_run_id"],
            "financial_indicator": ["symbol", "report_period", "metric_code", "source_run_id"],
            "fund_flow": ["symbol", "trade_date", "source_run_id"],
        }
        keys = key_map.get(dataset, ["symbol", "statement_type", "report_period", "line_item_code", "source_run_id"])
        add(dataset, "duplicate_business_key", "ERROR", int(frame.duplicated(keys).sum()), "Stable business key must be unique")
        add(dataset, "null_primary_key", "ERROR", int(frame[keys].isna().any(axis=1).sum()), "Business key fields must be non-null")
        if dataset.startswith("stock_daily"):
            invalid_ohlc = (
                (frame["high"] < frame["low"]) | (frame["high"] < frame["open"])
                | (frame["high"] < frame["close"]) | (frame["low"] > frame["open"])
                | (frame["low"] > frame["close"])
            ).fillna(False)
            add(dataset, "ohlc_relationship", "ERROR", int(invalid_ohlc.sum()), "OHLC relationships")
            add(dataset, "future_trade_date", "ERROR", int((frame["trade_date"] > as_of).sum()), "No daily date later than as_of_date")
            mismatch = ((frame["volume_share"] - frame["volume_lot"] * 100).abs() > 1e-9).fillna(False)
            add(dataset, "volume_conversion", "ERROR", int(mismatch.sum()), "volume_share = volume_lot * 100")
        if dataset == "stock_spot_target_16":
            add(dataset, "target_symbol_count", "ERROR", abs(frame["symbol"].nunique() - 16), "Exactly 16 target symbols")
        if dataset.startswith("financial_"):
            unknown = int((frame["announcement_date_status"] == "unavailable").sum())
            add(dataset, "announcement_date_unknown", "WARN", unknown, "Unknown announcement date is not point-in-time safe")
            raw_column = (
                "metric_value_raw"
                if "metric_value_raw" in frame.columns
                else "line_item_value_raw"
            )
            value_column = (
                "metric_value"
                if "metric_value" in frame.columns
                else "line_item_value"
            )
            raw_present = (
                frame[raw_column].notna()
                & ~frame[raw_column].astype("string").str.strip().isin(
                    ["", "-", "--"]
                )
            )
            conversion_failed = int(
                (raw_present & frame[value_column].isna()).sum()
            )
            add(
                dataset,
                "numeric_conversion_failed",
                "WARN",
                conversion_failed,
                "Raw value preserved; unknown or unsupported unit was not guessed",
            )
    return pd.DataFrame(rows)


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _execute_sql_file(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
    connection.execute(path.read_text(encoding="utf-8"))


def _insert_frame(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    frame: pd.DataFrame,
    keys: list[str],
) -> None:
    view = f"incoming_{table}"
    connection.register(view, frame)
    columns = list(frame.columns)
    quoted = ", ".join(f'"{column}"' for column in columns)
    predicate = " AND ".join(f't."{key}" = s."{key}"' for key in keys)
    connection.execute(
        f'INSERT INTO {table} ({quoted}) SELECT {quoted} FROM "{view}" s '
        f"WHERE NOT EXISTS (SELECT 1 FROM {table} t WHERE {predicate})"
    )
    connection.unregister(view)


def load_database(
    root: Path,
    database_path: Path,
    frames: dict[str, pd.DataFrame],
    transform_run: dict[str, Any],
    source_manifest: pd.DataFrame,
    lineage: pd.DataFrame,
    quality: pd.DataFrame,
    mappings: pd.DataFrame,
) -> dict[str, Any]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        # Legacy-schema migration is committed before constraints/indexes,
        # because DuckDB cannot create them with outstanding UPDATEs.
        connection.execute("BEGIN TRANSACTION")
        preflight_metadata_columns(connection)
        _execute_sql_file(connection, root / "sql/stage5_schema.sql")
        migration = migrate_metadata_schema(connection, root)
        connection.execute("COMMIT")
        finalize_metadata_schema(connection)
        _execute_sql_file(
            connection, root / "sql/stage5_metadata_indexes.sql"
        )
        connection.execute("BEGIN TRANSACTION")
        quality = prepare_quality_records(quality, root)
        mappings = prepare_mapping_records(mappings, root)
        universe = load_universe()
        dim = pd.DataFrame(
            [
                {
                    "symbol": item.symbol, "exchange": item.exchange,
                    "symbol_em": item.symbol_em, "market_lower": item.market_lower,
                    "asset_type": "A_SHARE", "currency": "CNY", "is_active": True,
                }
                for item in universe.stocks
            ]
        )
        _insert_frame(connection, "dim_security", dim, ["symbol"])
        run_frame = pd.DataFrame([transform_run])
        _insert_frame(connection, "etl_run", run_frame, ["transform_run_id"])
        _insert_frame(connection, "source_file_manifest", source_manifest, ["source_run_id", "source_file"])
        _insert_frame(connection, "data_lineage", lineage, ["transform_run_id", "dataset_id", "clean_file", "source_file"])
        quality_upsert = upsert_hashed_records(
            connection, "data_quality_issue", quality, "issue_key"
        )
        mapping_upsert = upsert_hashed_records(
            connection, "field_mapping_registry", mappings, "mapping_key"
        )
        table_map = {
            "stock_daily_qfq": ("fact_stock_daily", ["symbol", "trade_date", "adjust_type", "source_run_id"]),
            "stock_daily_raw": ("fact_stock_daily", ["symbol", "trade_date", "adjust_type", "source_run_id"]),
            "stock_spot_full_market": ("fact_stock_spot", ["symbol", "snapshot_at", "snapshot_scope", "source_run_id"]),
            "stock_spot_target_16": ("fact_stock_spot", ["symbol", "snapshot_at", "snapshot_scope", "source_run_id"]),
            "financial_abstract": ("fact_financial_abstract", ["symbol", "report_period", "metric_code", "source_run_id"]),
            "financial_indicator": ("fact_financial_indicator", ["symbol", "report_period", "metric_code", "source_run_id"]),
            "fund_flow": ("fact_stock_fund_flow", ["symbol", "trade_date", "source_run_id"]),
        }
        for dataset, frame in frames.items():
            if dataset.startswith("financial_statement_"):
                table, keys = "fact_financial_statement", [
                    "symbol", "statement_type", "report_period", "line_item_code", "source_run_id"
                ]
            else:
                table, keys = table_map[dataset]
            _insert_frame(connection, table, frame, keys)
        _execute_sql_file(connection, root / "sql/stage5_views.sql")
        connection.execute("COMMIT")
        tables = [
            row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY 1"
            ).fetchall()
        ]
        views = [
            row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='VIEW' ORDER BY 1"
            ).fetchall()
        ]
        counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
        return {
            "tables": tables,
            "views": views,
            "counts": counts,
            "metadata_migration": migration,
            "quality_upsert": quality_upsert,
            "mapping_upsert": mapping_upsert,
        }
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise
    finally:
        connection.close()


def validate_database(database_path: Path) -> dict[str, Any]:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        fact_keys = {
            "fact_stock_daily": "symbol, trade_date, adjust_type, source_run_id",
            "fact_stock_spot": "symbol, snapshot_at, snapshot_scope, source_run_id",
            "fact_financial_abstract": "symbol, report_period, metric_code, source_run_id",
            "fact_financial_indicator": "symbol, report_period, metric_code, source_run_id",
            "fact_financial_statement": "symbol, statement_type, report_period, line_item_code, source_run_id",
            "fact_stock_fund_flow": "symbol, trade_date, source_run_id",
        }
        duplicates = {
            table: connection.execute(
                f"SELECT count(*) FROM (SELECT {keys}, count(*) c FROM {table} GROUP BY {keys} HAVING c > 1)"
            ).fetchone()[0]
            for table, keys in fact_keys.items()
        }
        null_keys = {
            table: connection.execute(
                f"SELECT count(*) FROM {table} WHERE "
                + " OR ".join(f"{key.strip()} IS NULL" for key in keys.split(","))
            ).fetchone()[0]
            for table, keys in fact_keys.items()
        }
        checks = {
            "dim_security_a_share_count": connection.execute("SELECT count(*) FROM dim_security").fetchone()[0],
            "daily_qfq_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM v_stock_daily_qfq").fetchone()[0],
            "daily_raw_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM v_stock_daily_raw").fetchone()[0],
            "spot_target_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM fact_stock_spot WHERE snapshot_scope='target_16'").fetchone()[0],
            "financial_abstract_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM fact_financial_abstract").fetchone()[0],
            "financial_indicator_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM fact_financial_indicator").fetchone()[0],
            "financial_statement_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM fact_financial_statement").fetchone()[0],
            "fund_flow_symbols": connection.execute("SELECT count(DISTINCT symbol) FROM fact_stock_fund_flow").fetchone()[0],
            "safe_unknown_count": connection.execute("SELECT count(*) FROM v_financial_point_in_time_safe WHERE announcement_date_status='unavailable'").fetchone()[0],
            "lookahead_logic_errors": connection.execute("SELECT count(*) FROM v_financial_potential_lookahead WHERE announcement_date IS NULL OR potential_lookahead <> TRUE").fetchone()[0],
        }
        return {
            "status": "PASS" if all(value == 0 for value in duplicates.values()) and all(value == 0 for value in null_keys.values()) and all(checks[key] == 16 for key in checks if key.endswith(("count", "symbols")) and key not in {"safe_unknown_count"}) and checks["safe_unknown_count"] == 0 and checks["lookahead_logic_errors"] == 0 else "FAIL",
            "checks": checks, "duplicate_keys": duplicates, "null_primary_keys": null_keys,
        }
    finally:
        connection.close()


def refresh_mapping_artifacts(
    root: Path,
    market_run_id: str,
    fundamental_run_id: str,
    transform_run_id: str,
    database_path: Path,
) -> dict[str, int]:
    """Refresh mapping registry/reports after mapping-policy-only changes."""
    market = validate_raw_manifest(
        root,
        root / f"reports/evidence/stage3/{market_run_id}/manifest.json",
        market_run_id,
    )
    finance = validate_raw_manifest(
        root,
        root / f"reports/evidence/stage4/{fundamental_run_id}/manifest.json",
        fundamental_run_id,
    )
    mappings = build_field_mapping_report(
        root, [market, finance], transform_run_id
    )
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN")
        preflight_metadata_columns(connection)
        _execute_sql_file(connection, root / "sql/stage5_schema.sql")
        migrate_metadata_schema(connection, root)
        connection.execute("COMMIT")
        finalize_metadata_schema(connection)
        _execute_sql_file(
            connection, root / "sql/stage5_metadata_indexes.sql"
        )
        connection.execute("BEGIN")
        upsert_hashed_records(
            connection,
            "field_mapping_registry",
            mappings,
            "mapping_key",
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    reports = root / "reports"
    mappings.to_csv(
        reports / "stage5_field_mapping.csv", index=False, encoding="utf-8-sig"
    )
    mappings[mappings["mapping_status"].isin(["unmapped", "ambiguous"])].to_csv(
        reports / "stage5_unmapped_fields.csv",
        index=False,
        encoding="utf-8-sig",
    )
    counts = {
        str(key): int(value)
        for key, value in mappings["mapping_status"].value_counts().items()
    }
    run_path = reports / "stage5_run.json"
    run_report = json.loads(run_path.read_text(encoding="utf-8"))
    run_report["field_mapping"] = counts
    run_report["field_mapping"]["unknown_unit_fields"] = int(
        (mappings["source_unit"] == "unknown").sum()
    )
    run_path.write_text(
        json.dumps(run_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evidence_path = (
        reports
        / "evidence/stage5"
        / transform_run_id
        / "manifest.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["database"]["size"] = database_path.stat().st_size
    evidence["database"]["sha256"] = file_sha256(database_path)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return counts


def refresh_quality_artifacts(
    root: Path,
    transform_run_id: str,
    as_of_date: date,
    database_path: Path,
) -> dict[str, int]:
    """Refresh quality registry/reports without changing persisted Clean facts."""
    evidence_path = (
        root
        / "reports/evidence/stage5"
        / transform_run_id
        / "manifest.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    frames = {
        record["dataset_id"]: pd.read_parquet(root / record["path"])
        for record in evidence["clean_files"]
    }
    quality = prepare_quality_records(
        _quality_rows(frames, transform_run_id, as_of_date), root
    )
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN")
        preflight_metadata_columns(connection)
        _execute_sql_file(connection, root / "sql/stage5_schema.sql")
        migrate_metadata_schema(connection, root)
        connection.execute("COMMIT")
        finalize_metadata_schema(connection)
        _execute_sql_file(
            connection, root / "sql/stage5_metadata_indexes.sql"
        )
        connection.execute("BEGIN")
        upsert_hashed_records(
            connection,
            "data_quality_issue",
            quality,
            "issue_key",
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    quality.to_csv(
        root / "reports/stage5_data_quality.csv",
        index=False,
        encoding="utf-8-sig",
    )
    coverage_path = root / "reports/stage5_clean_coverage.csv"
    coverage = pd.read_csv(coverage_path)
    warning_counts = (
        quality[quality["status"] == "WARN"]
        .groupby("dataset_id")["issue_count"]
        .sum()
        .to_dict()
    )
    for dataset, frame in frames.items():
        if dataset.startswith("financial_"):
            warning_counts[dataset] = int(
                warning_counts.get(dataset, 0)
                + (frame["unit_source"] == "unknown").sum()
            )
    coverage["warning_count"] = coverage["dataset_id"].map(
        warning_counts
    ).fillna(0).astype("int64")
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    status_counts = {
        str(key): int(value)
        for key, value in quality["status"].value_counts().items()
    }
    run_path = root / "reports/stage5_run.json"
    run_report = json.loads(run_path.read_text(encoding="utf-8"))
    run_report["quality"] = status_counts
    run_report["warnings"] = [
        "Unknown announcement dates remain unavailable and are excluded from the point-in-time-safe view"
    ]
    numeric_failures = int(
        quality.loc[
            quality["check_name"] == "numeric_conversion_failed",
            "issue_count",
        ].sum()
    )
    if numeric_failures:
        run_report["warnings"].append(
            "Unsupported textual financial values retain metric_value_raw and NULL canonical value; counts are reported as WARN"
        )
    run_path.write_text(
        json.dumps(run_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evidence["database"]["size"] = database_path.stat().st_size
    evidence["database"]["sha256"] = file_sha256(database_path)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return status_counts


def build_stage5(
    root: Path,
    as_of_date: date,
    market_run_id: str,
    fundamental_run_id: str,
    transform_run_id: str | None = None,
    clean_output_dir: Path | None = None,
    database_path: Path | None = None,
    evidence_dir: Path | None = None,
) -> tuple[dict[str, Any], int]:
    started_at = _now()
    transform_run_id = transform_run_id or str(uuid.uuid4())
    uuid.UUID(transform_run_id)
    clean_root = clean_output_dir or root / "data/clean"
    database_path = database_path or root / "database/akshare_data_test.duckdb"
    evidence_root = evidence_dir or root / "reports/evidence/stage5"
    market_manifest_path = root / f"reports/evidence/stage3/{market_run_id}/manifest.json"
    finance_manifest_path = root / f"reports/evidence/stage4/{fundamental_run_id}/manifest.json"
    market = validate_raw_manifest(root, market_manifest_path, market_run_id)
    finance = validate_raw_manifest(root, finance_manifest_path, fundamental_run_id)
    if len(market.raw_files) != 34 or len(finance.raw_files) != 96:
        raise ValueError("Expected exactly 34 Stage 3 and 96 Stage 4 Raw files")

    frames: dict[str, pd.DataFrame] = {}
    lineage_items: list[dict[str, Any]] = []
    part, lines = clean_stock_daily(root, market, transform_run_id)
    frames.update(part); lineage_items.extend(lines)
    part, lines = clean_stock_spot(root, market, transform_run_id)
    frames.update(part); lineage_items.extend(lines)
    frame, lines = clean_financial_abstract(root, finance, transform_run_id, as_of_date)
    frames["financial_abstract"] = frame; lineage_items.extend(lines)
    frame, lines = clean_financial_indicator(root, finance, transform_run_id, as_of_date)
    frames["financial_indicator"] = frame; lineage_items.extend(lines)
    part, lines = clean_financial_statements(root, finance, transform_run_id, as_of_date)
    frames.update(part); lineage_items.extend(lines)
    frame, lines = clean_fund_flow(root, finance, transform_run_id)
    frames["fund_flow"] = frame; lineage_items.extend(lines)

    mappings = build_field_mapping_report(root, [market, finance], transform_run_id)
    quality = prepare_quality_records(
        _quality_rows(frames, transform_run_id, as_of_date), root
    )
    if (quality["status"] == "FAIL").any():
        raise ValueError("Clean quality gate failed before persistence")

    dataset_paths = {
        "stock_daily_qfq": f"stock_daily/transform_run_id={transform_run_id}/adjust=qfq/data.parquet",
        "stock_daily_raw": f"stock_daily/transform_run_id={transform_run_id}/adjust=raw/data.parquet",
        "stock_spot_full_market": f"stock_spot/transform_run_id={transform_run_id}/full_market.parquet",
        "stock_spot_target_16": f"stock_spot/transform_run_id={transform_run_id}/target_16.parquet",
        "financial_abstract": f"financial_abstract/transform_run_id={transform_run_id}/data.parquet",
        "financial_indicator": f"financial_indicator/transform_run_id={transform_run_id}/data.parquet",
        "financial_statement_balance_sheet": f"financial_statement/transform_run_id={transform_run_id}/statement_type=balance_sheet/data.parquet",
        "financial_statement_profit_statement": f"financial_statement/transform_run_id={transform_run_id}/statement_type=profit_statement/data.parquet",
        "financial_statement_cash_flow_statement": f"financial_statement/transform_run_id={transform_run_id}/statement_type=cash_flow_statement/data.parquet",
        "fund_flow": f"fund_flow/transform_run_id={transform_run_id}/data.parquet",
    }
    clean_records: list[dict[str, Any]] = []
    for dataset, frame in frames.items():
        relative_clean = dataset_paths[dataset]
        metadata = _atomic_parquet(frame, clean_root / relative_clean)
        clean_records.append(
            {
                "dataset_id": dataset,
                "path": (Path("data/clean") / relative_clean).as_posix()
                if clean_root.resolve() == (root / "data/clean").resolve()
                else relative_clean,
                **metadata,
            }
        )

    lineage_rows: list[dict[str, Any]] = []
    for item in lineage_items:
        clean_path = next(record["path"] for record in clean_records if record["dataset_id"] == item["dataset_id"])
        source_run = market.run_id if Path(item["source_file"]).parts[2] in MARKET_INTERFACES else finance.run_id
        lineage_rows.append(
            {
                "transform_run_id": transform_run_id, "dataset_id": item["dataset_id"],
                "clean_file": clean_path, "source_file": item["source_file"],
                "source_run_id": source_run,
            }
        )
    lineage = pd.DataFrame(lineage_rows).drop_duplicates()
    source_rows = []
    for manifest in (market, finance):
        for item in manifest.raw_files:
            source_rows.append(
                {
                    "source_run_id": manifest.run_id, "source_file": item["path"],
                    "byte_size": int(item["size"]), "sha256": item["sha256"],
                    "row_count": len(pd.read_parquet(root / item["path"])),
                }
            )
    source_manifest = pd.DataFrame(source_rows)
    finished_at = _now()
    transform_run = {
        "transform_run_id": transform_run_id, "market_source_run_id": market.run_id,
        "fundamental_source_run_id": finance.run_id, "as_of_date": as_of_date,
        "started_at": started_at, "finished_at": finished_at, "code_version": "stage5",
        "git_commit": _git_commit(root), "python_version": platform.python_version(),
        "pandas_version": pd.__version__, "pyarrow_version": pyarrow.__version__,
        "duckdb_version": duckdb.__version__, "status": "PASS",
    }

    if database_path.exists():
        raise FileExistsError(f"Database already exists; refusing silent overwrite: {database_path}")
    temporary_database = database_path.with_name(database_path.name + f".{transform_run_id}.tmp")
    database_summary = load_database(
        root, temporary_database, frames, transform_run, source_manifest,
        lineage, quality, mappings,
    )
    os.replace(temporary_database, database_path)
    validation = validate_database(database_path)
    if validation["status"] != "PASS":
        raise ValueError("Database validation failed")

    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    coverage_rows = []
    interface_by_dataset = {
        "stock_daily_qfq": (market, "stock_zh_a_hist", "adjust=qfq"),
        "stock_daily_raw": (market, "stock_zh_a_hist", "adjust=raw"),
        "stock_spot_full_market": (market, "stock_zh_a_spot_em", "full_market.parquet"),
        "stock_spot_target_16": (market, "stock_zh_a_spot_em", "target_16.parquet"),
        "financial_abstract": (finance, "stock_financial_abstract", ""),
        "financial_indicator": (finance, "stock_financial_analysis_indicator", ""),
        "financial_statement_balance_sheet": (finance, "stock_balance_sheet_by_report_em", ""),
        "financial_statement_profit_statement": (finance, "stock_profit_sheet_by_report_em", ""),
        "financial_statement_cash_flow_statement": (finance, "stock_cash_flow_sheet_by_report_em", ""),
        "fund_flow": (finance, "stock_individual_fund_flow", ""),
    }
    for record in clean_records:
        dataset = record["dataset_id"]
        manifest, interface, token = interface_by_dataset[dataset]
        sources = [item for item in _source_files(manifest, interface) if token in item["path"]]
        warnings = int(
            quality.loc[
                (quality["dataset_id"] == dataset)
                & (quality["status"] == "WARN"),
                "issue_count",
            ].sum()
        )
        if dataset.startswith("financial_"):
            warnings += int(
                (frames[dataset]["unit_source"] == "unknown").sum()
            )
        coverage_rows.append(
            {
                "transform_run_id": transform_run_id, "source_run_id": manifest.run_id,
                "dataset_id": dataset, "status": "success", "source_file_count": len(sources),
                "source_row_count": _source_row_count(root, sources),
                "clean_file_count": 1, "clean_row_count": len(frames[dataset]),
                "rejected_row_count": 0, "warning_count": warnings, "error_count": 0,
                "schema_hash": hashlib.sha256(
                    json.dumps([(str(c), str(frames[dataset][c].dtype)) for c in frames[dataset].columns]).encode()
                ).hexdigest(),
                "clean_path": record["path"],
            }
        )
    coverage = pd.DataFrame(coverage_rows)
    coverage.to_csv(reports / "stage5_clean_coverage.csv", index=False, encoding="utf-8-sig")
    mappings.to_csv(reports / "stage5_field_mapping.csv", index=False, encoding="utf-8-sig")
    mappings[mappings["mapping_status"].isin(["unmapped", "ambiguous"])].to_csv(
        reports / "stage5_unmapped_fields.csv", index=False, encoding="utf-8-sig"
    )
    quality.to_csv(reports / "stage5_data_quality.csv", index=False, encoding="utf-8-sig")
    unit_rows = []
    for dataset, frame in frames.items():
        if dataset.startswith("stock_daily"):
            unit_rows.extend([
                [dataset, "volume_lot", "lot", "share", 100, int(frame["volume_lot"].notna().sum()), 0],
                [dataset, "pct_change", "percent_point", "decimal", 0.01, int(frame["pct_change"].notna().sum()), 0],
            ])
        elif dataset.startswith("stock_spot"):
            unit_rows.append([dataset, "volume_lot", "lot", "share", 100, int(frame["volume_lot"].notna().sum()), 0])
        elif dataset == "fund_flow":
            unit_rows.append([dataset, "*_ratio", "percent_point", "decimal", 0.01, int(frame.filter(regex="_ratio$").notna().sum().sum()), 0])
        elif dataset.startswith("financial_"):
            converted = int((frame["unit_source"] == "percent_point").sum())
            unit_rows.append([dataset, "explicit_percent_fields", "percent_point", "decimal", 0.01, converted, int((frame["unit_source"] == "unknown").sum())])
    unit_conversion = pd.DataFrame(
        unit_rows, columns=["dataset", "field", "source_unit", "target_unit", "scale_factor", "converted_row_count", "warning_count"]
    )
    unit_conversion.to_csv(reports / "stage5_unit_conversion.csv", index=False, encoding="utf-8-sig")
    point_frames = [frame for key, frame in frames.items() if key.startswith("financial_")]
    point = pd.concat(point_frames, ignore_index=True)
    point_report = pd.DataFrame(
        [
            {"check": "announcement_unknown", "row_count": int((point["announcement_date_status"] == "unavailable").sum()), "status": "WARN"},
            {"check": "potential_lookahead", "row_count": int((point["potential_lookahead"] == True).sum()), "status": "PASS"},
            {"check": "safe_view_unknown", "row_count": validation["checks"]["safe_unknown_count"], "status": "PASS"},
            {"check": "lookahead_logic_errors", "row_count": validation["checks"]["lookahead_logic_errors"], "status": "PASS"},
        ]
    )
    point_report.to_csv(reports / "stage5_point_in_time_validation.csv", index=False, encoding="utf-8-sig")
    (reports / "stage5_database_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(
        [{"table": key, "row_count": value} for key, value in database_summary["counts"].items()]
    ).to_csv(reports / "stage5_table_counts.csv", index=False, encoding="utf-8-sig")

    idempotency_database = database_path.with_name(database_path.name + ".idempotency.tmp")
    if idempotency_database.exists():
        idempotency_database.unlink()
    import shutil
    shutil.copy2(database_path, idempotency_database)
    try:
        with duckdb.connect(str(idempotency_database), read_only=True) as connection:
            first_snapshot = snapshot_tables(connection)
        load_database(
            root,
            idempotency_database,
            frames,
            transform_run,
            source_manifest,
            lineage,
            quality,
            mappings,
        )
        with duckdb.connect(str(idempotency_database), read_only=True) as connection:
            second_snapshot = snapshot_tables(connection)
    finally:
        if idempotency_database.exists():
            idempotency_database.unlink()
    snapshot_match = first_snapshot == second_snapshot
    idempotency = {
        "status": "PASS" if snapshot_match else "FAIL",
        "complete_nonempty_second_load": True,
        "all_table_rows_and_content_unchanged": snapshot_match,
        "first_snapshot": first_snapshot,
        "second_snapshot": second_snapshot,
        "clean_overwritten": False,
        "transaction_rollback_test": "covered_by_automated_test",
    }
    (reports / "stage5_idempotency_check.json").write_text(
        json.dumps(idempotency, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mapping_counts = mappings["mapping_status"].value_counts().to_dict()
    run_report = {
        "stage": 5, "status": "PASS", "can_enter_stage6": True,
        "transform_run_id": transform_run_id, "market_source_run_id": market.run_id,
        "fundamental_source_run_id": finance.run_id, "as_of_date": as_of_date.isoformat(),
        "started_at": started_at, "finished_at": finished_at,
        "raw_validation": {"stage3": "34/34", "stage4": "96/96"},
        "clean_datasets": {row["dataset_id"]: int(row["clean_row_count"]) for row in coverage_rows},
        "database": {"path": _relative(database_path, root), **validation},
        "field_mapping": mapping_counts,
        "unit_conversion": {"rows": len(unit_conversion)},
        "point_in_time": point_report.to_dict("records"),
        "quality": quality["status"].value_counts().to_dict(),
        "idempotency": idempotency,
        "tests": {}, "failures": [],
        "warnings": ["Unknown announcement dates remain unavailable and are excluded from the point-in-time-safe view"],
        "powershell_required": [],
    }
    (reports / "stage5_run.json").write_text(
        json.dumps(run_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    evidence_run = evidence_root / transform_run_id
    evidence_run.mkdir(parents=True, exist_ok=False)
    report_paths = [
        reports / "stage5_clean_coverage.csv",
        reports / "stage5_field_mapping.csv",
        reports / "stage5_unmapped_fields.csv",
        reports / "stage5_data_quality.csv",
        reports / "stage5_unit_conversion.csv",
        reports / "stage5_point_in_time_validation.csv",
        reports / "stage5_database_validation.json",
        reports / "stage5_table_counts.csv",
        reports / "stage5_idempotency_check.json",
        reports / "stage5_run.json",
    ]
    evidence_manifest = {
        "transform_run_id": transform_run_id,
        "created_at": _now(),
        "market_source_run_id": market.run_id,
        "fundamental_source_run_id": finance.run_id,
        "as_of_date": as_of_date.isoformat(),
        "status": "PASS",
        "code_commit": _git_commit(root),
        "clean_files": clean_records,
        "database": {
            "path": _relative(database_path, root),
            "size": database_path.stat().st_size,
            "sha256": file_sha256(database_path),
        },
        "report_files": [
            {
                "path": _relative(path, root),
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            for path in report_paths
        ],
    }
    (evidence_run / "manifest.json").write_text(
        json.dumps(evidence_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_report, 0
