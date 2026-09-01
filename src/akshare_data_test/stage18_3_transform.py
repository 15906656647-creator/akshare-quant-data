"""Stage 18.3 canonical fundamental Clean transformation and PIT governance."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .stage18_2_collect import _stage181_fingerprint, _tree_state
from .stage18_2_config import load_stage18_2_config
from .stage18_3_config import MetricMapping, Stage183Config, load_stage18_3_config
from .stage18_config import load_stage18_config
from .stage18_audit import Stage18Blocked, _atomic_csv, _atomic_text, frozen_hashes
from .stage18_reaudit import _stage17_fingerprint, _verify_records
from .storage.raw_store import file_record, file_sha256
from .storage.stage18_clean_store import Stage18CleanStore


HISTORY_CATEGORIES = (
    "financial_abstract", "financial_indicator", "balance_sheet",
    "income_statement", "cash_flow_statement",
)
PROTECTED_ROOTS = (
    "database/stage18", "data/features/stage18", "data/raw/stage19", "reports/stage19",
)
GOVERNANCE_COLUMNS = {
    "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "ORG_TYPE",
    "REPORT_DATE", "REPORT_TYPE", "REPORT_DATE_NAME", "SECURITY_TYPE_CODE",
    "NOTICE_DATE", "UPDATE_DATE", "CURRENCY", "DATE_TYPE_CODE", "START_DATE",
    "FISCAL_YEAR", "IS_CNY_CODE", "STD_REPORT_DATE", "STD_ITEM_CODE",
    "STD_ITEM_NAME", "AMOUNT", "OPINION_TYPE", "OSOPINION_TYPE", "LISTING_STATE",
    "日期", "选项", "指标",
}
HISTORY_COLUMNS = [
    "symbol", "market", "data_category", "provider", "source_interface",
    "source_variant", "report_date", "announcement_date", "update_date",
    "fiscal_year", "fiscal_period", "period_type", "currency", "currency_status",
    "source_field", "source_metric_name", "source_section", "canonical_name", "mapping_status",
    "value", "source_unit", "canonical_unit", "scale_factor", "normalized_value",
    "pit_status", "eligible_for_as_of_date_analysis", "dedup_status",
    "canonical_key", "source_run_id", "clean_run_id", "source_dataset_id",
    "source_sha256", "source_variants", "source_sections", "source_dataset_ids", "source_sha256s",
    "schema_version",
]
VALUATION_COLUMNS = [
    "symbol", "market", "data_category", "provider", "source_interface",
    "source_variant", "snapshot_time", "analysis_as_of_date",
    "eligible_for_as_of_date_analysis", "pit_status", "currency", "currency_status",
    "pe", "pb", "total_market_cap", "floating_market_cap",
    "pe_source_interface", "pb_source_interface", "market_cap_source_interface",
    "source_component_count", "source_interfaces", "source_variants",
    "source_dataset_ids", "source_sha256s", "source_run_id", "clean_run_id",
    "schema_version",
]


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Stage18Blocked(f"Missing or invalid Stage 18.3 evidence: {path}") from exc
    if not isinstance(value, dict):
        raise Stage18Blocked(f"Expected JSON object: {path}")
    return value


def _fingerprint_stage182(root: Path, config: Stage183Config) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_path = root / config.source_run_path
    manifest_path = root / config.source_manifest_path
    run = _json_object(run_path)
    manifest = _json_object(manifest_path)
    rows = manifest.get("result_rows")
    files = manifest.get("files")
    if (
        run.get("run_id") != config.source_run_id
        or run.get("status") != "PASS"
        or run.get("stage18_3_authorized") is not True
        or run.get("stage18_3_started") is not False
        or int(run.get("terminal_dataset_count", -1)) != config.expected_dataset_count
        or int(run.get("security_count", -1)) != config.expected_security_count
        or manifest.get("run_id") != config.source_run_id
        or manifest.get("status") != "PASS"
        or not isinstance(rows, list)
        or len(rows) != config.expected_dataset_count
        or not isinstance(files, list)
        or not files
    ):
        raise Stage18Blocked("Stage 18.2 PASS/authorization evidence differs")
    if len({str(row.get("dataset_id")) for row in rows}) != config.expected_dataset_count:
        raise Stage18Blocked("Stage 18.2 dataset ids are not a closed unique set")
    if any(
        row.get("status") != "PASS"
        or row.get("asset_role") != "fundamental_raw"
        or row.get("audit_only") is not False
        or row.get("eligible_for_stage18_3_standardization") is not True
        for row in rows
    ):
        raise Stage18Blocked("Stage 18.2 result rows are not eligible formal Raw")
    symbols = {(str(row["market"]), str(row["symbol"])) for row in rows}
    if (
        len(symbols) != 23
        or sum(market == "A" for market, _ in symbols) != 16
        or sum(market == "HK" for market, _ in symbols) != 7
    ):
        raise Stage18Blocked("Stage 18.2 security scope differs from 16 A + 7 HK")
    tree_hash = _verify_records(root, files, size_key="size")
    for row in rows:
        data_path = root / str(row["data_path"])
        metadata_path = root / str(row["metadata_path"])
        if (
            not data_path.is_file()
            or file_sha256(data_path) != str(row["sha256"])
            or not metadata_path.is_file()
        ):
            raise Stage18Blocked(f"Stage 18.2 Raw differs: {row['dataset_id']}")
        metadata = _json_object(metadata_path)
        if (
            metadata.get("run_id") != config.source_run_id
            or metadata.get("dataset_id") != row["dataset_id"]
            or metadata.get("data_sha256") != row["sha256"]
        ):
            raise Stage18Blocked(f"Stage 18.2 Raw lineage differs: {row['dataset_id']}")
    return ({
        "run_id": config.source_run_id,
        "run_sha256": file_sha256(run_path),
        "manifest_sha256": file_sha256(manifest_path),
        "manifest_file_count": len(files),
        "manifest_tree_sha256": tree_hash,
        "dataset_count": len(rows),
        "security_count": len(symbols),
    }, rows)


def _protected_state(root: Path) -> dict[str, Any]:
    full = _tree_state(root)
    return {key: full[key] for key in PROTECTED_ROOTS}


def _mapping_lookup(config: Stage183Config) -> dict[tuple[str, str, str], MetricMapping]:
    return {(item.market, item.category, item.source_field): item for item in config.mappings}


def _passthrough_name(market: str, category: str, source_field: str) -> str:
    payload = f"{market}|{category}|{source_field}".encode("utf-8")
    return "provider_field_" + hashlib.sha256(payload).hexdigest()[:16]


def _unit_info(
    *, market: str, category: str, source_field: str, currency: str,
    explicit_unit: str | None,
) -> tuple[str, str, float]:
    label = source_field
    if explicit_unit:
        base = explicit_unit
    elif "亿元" in label:
        base = "currency_100m"
    elif "万元" in label:
        base = "currency_10k"
    elif "港元" in label:
        base = "currency"
        currency = "HKD"
    elif "(%)" in label or "（%）" in label or label.endswith("_YOY"):
        base = "percent"
    elif "(元)" in label or "（元）" in label:
        base = "currency_per_share" if "每股" in label else "currency"
    elif "(股)" in label or "（股）" in label:
        base = "shares"
    elif "(天)" in label or "（天）" in label:
        base = "days"
    elif "(次)" in label or "（次）" in label:
        base = "times"
    elif category in {"balance_sheet", "income_statement", "cash_flow_statement"}:
        base = "currency"
    else:
        base = "ratio"
    scale = 100_000_000.0 if base == "currency_100m" else 10_000.0 if base == "currency_10k" else 1.0
    if base.startswith("currency"):
        code = currency if currency and currency != "UNAVAILABLE" else "CURRENCY_UNAVAILABLE"
        suffix = base.removeprefix("currency")
        source_unit = code + suffix
        canonical_unit = code + ("_per_share" if base == "currency_per_share" else "")
    else:
        source_unit = canonical_unit = base
    return source_unit, canonical_unit, scale


def _period_values(values: pd.Series) -> pd.DataFrame:
    dates = pd.to_datetime(values, errors="coerce")
    if dates.isna().any():
        raise Stage18Blocked("Stage 18.3 encountered an unparseable report date")
    month_day = dates.dt.strftime("%m-%d")
    period = month_day.map({"03-31": "Q1", "06-30": "H1", "09-30": "Q3", "12-31": "FY"}).fillna("OTHER")
    period_type = month_day.map({
        "03-31": "QUARTERLY", "06-30": "SEMIANNUAL",
        "09-30": "QUARTERLY", "12-31": "ANNUAL",
    }).fillna("OTHER")
    return pd.DataFrame({
        "report_date": dates.dt.normalize(), "fiscal_year": dates.dt.year.astype("int64"),
        "fiscal_period": period, "period_type": period_type,
    }, index=values.index)


def _pit_status(
    announcement: pd.Series, update: pd.Series, as_of_date: date,
) -> tuple[pd.Series, pd.Series]:
    ann = pd.to_datetime(announcement, errors="coerce")
    upd = pd.to_datetime(update, errors="coerce")
    cutoff = pd.Timestamp(as_of_date)
    status = pd.Series("PIT_ELIGIBLE", index=announcement.index, dtype="object")
    status.loc[ann.isna()] = "ANNOUNCEMENT_DATE_UNAVAILABLE"
    status.loc[ann.notna() & ann.gt(cutoff)] = "FUTURE_AS_OF_DATE"
    status.loc[ann.notna() & ann.le(cutoff) & upd.isna()] = "UPDATE_DATE_UNAVAILABLE"
    status.loc[ann.notna() & ann.le(cutoff) & upd.notna() & upd.gt(cutoff)] = "UPDATE_AFTER_AS_OF_DATE"
    eligible = status.eq("PIT_ELIGIBLE")
    return status, eligible


def _currency_for_frame(
    frame: pd.DataFrame, market: str, symbol: str, hk_currency: dict[str, str],
    default_a: str,
) -> tuple[pd.Series, pd.Series]:
    if "CURRENCY" in frame.columns:
        currency = frame["CURRENCY"].fillna("").astype(str).str.upper()
        fallback = hk_currency.get(symbol, "UNAVAILABLE") if market == "HK" else default_a
        currency = currency.mask(currency.eq(""), fallback)
        status = pd.Series("reported", index=frame.index)
        status.loc[frame["CURRENCY"].isna() | frame["CURRENCY"].astype(str).eq("")] = (
            "companion_financial_indicator" if market == "HK" else "market_default"
        )
        return currency, status
    if market == "HK":
        value = hk_currency.get(symbol, "UNAVAILABLE")
        return (
            pd.Series(value, index=frame.index),
            pd.Series("companion_financial_indicator" if value != "UNAVAILABLE" else "unavailable", index=frame.index),
        )
    return pd.Series(default_a, index=frame.index), pd.Series("market_default", index=frame.index)


def _schema_inventory(
    unit: dict[str, Any], frame: pd.DataFrame, lookup: dict[tuple[str, str, str], MetricMapping],
) -> list[dict[str, Any]]:
    rows = []
    for column in frame.columns:
        name = str(column)
        if unit["category"] == "financial_abstract" and re.fullmatch(r"\d{8}", name):
            role = "report_date_value_column"
            mapping_status = "STRUCTURAL_DATE"
            canonical = "value"
        elif name in GOVERNANCE_COLUMNS:
            role = "governance"
            mapping_status = "GOVERNANCE_FIELD"
            canonical = ""
        else:
            role = "metric"
            item = lookup.get((str(unit["market"]), str(unit["category"]), name))
            mapping_status = "CORE_MAPPED" if item else "PASSTHROUGH_STANDARDIZED"
            canonical = item.canonical_name if item else _passthrough_name(str(unit["market"]), str(unit["category"]), name)
        rows.append({
            "market": unit["market"], "category": unit["category"],
            "interface": unit["interface"], "variant": unit["variant"],
            "source_schema_hash": unit["schema_hash"], "source_field": name,
            "source_dtype": str(frame[column].dtype), "field_role": role,
            "mapping_status": mapping_status, "canonical_name": canonical,
        })
    return rows


def _history_source_long(
    unit: dict[str, Any], frame: pd.DataFrame, hk_currency: dict[str, str], config: Stage183Config,
) -> pd.DataFrame:
    market, category, symbol = str(unit["market"]), str(unit["category"]), str(unit["symbol"])
    if category == "financial_abstract":
        date_columns = [str(column) for column in frame.columns if re.fullmatch(r"\d{8}", str(column))]
        if not date_columns or "指标" not in frame.columns:
            raise Stage18Blocked(f"Financial abstract schema cannot be parsed: {unit['dataset_id']}")
        long = frame.melt(
            id_vars=[column for column in ("选项", "指标") if column in frame.columns],
            value_vars=date_columns, var_name="_report_date", value_name="value",
        )
        long["source_field"] = long["指标"].astype(str)
        long["source_metric_name"] = long["指标"].astype(str)
        long["source_section"] = long["选项"].astype(str)
        report = pd.to_datetime(long["_report_date"], format="%Y%m%d", errors="coerce")
        long["announcement_date"] = pd.NaT
        long["update_date"] = pd.NaT
        long["currency"] = config.a_share_default_currency
        long["currency_status"] = "market_default"
    elif market == "HK" and category in {"balance_sheet", "income_statement", "cash_flow_statement"}:
        required = {"REPORT_DATE", "STD_ITEM_CODE", "STD_ITEM_NAME", "AMOUNT"}
        if not required.issubset(frame.columns):
            raise Stage18Blocked(f"HK statement schema cannot be parsed: {unit['dataset_id']}")
        long = frame.copy()
        long["value"] = long["AMOUNT"]
        long["source_field"] = long["STD_ITEM_CODE"].astype(str)
        long["source_metric_name"] = long["STD_ITEM_NAME"].astype(str)
        long["source_section"] = ""
        report = pd.to_datetime(long["REPORT_DATE"], errors="coerce")
        long["announcement_date"] = pd.NaT
        long["update_date"] = pd.NaT
        currency = hk_currency.get(symbol, "UNAVAILABLE")
        long["currency"] = currency
        long["currency_status"] = "companion_financial_indicator" if currency != "UNAVAILABLE" else "unavailable"
    else:
        report_column = "日期" if "日期" in frame.columns else "REPORT_DATE"
        if report_column not in frame.columns:
            raise Stage18Blocked(f"Historical report date is missing: {unit['dataset_id']}")
        id_columns = [column for column in frame.columns if str(column) in GOVERNANCE_COLUMNS]
        value_columns = [column for column in frame.columns if column not in id_columns]
        if not value_columns:
            raise Stage18Blocked(f"Historical value fields are missing: {unit['dataset_id']}")
        long = frame.melt(id_vars=id_columns, value_vars=value_columns, var_name="source_field", value_name="value")
        long["source_field"] = long["source_field"].astype(str)
        long["source_metric_name"] = long["source_field"]
        long["source_section"] = ""
        report = pd.to_datetime(long[report_column], errors="coerce")
        long["announcement_date"] = pd.to_datetime(long["NOTICE_DATE"], errors="coerce") if "NOTICE_DATE" in long else pd.NaT
        long["update_date"] = pd.to_datetime(long["UPDATE_DATE"], errors="coerce") if "UPDATE_DATE" in long else pd.NaT
        currency, status = _currency_for_frame(long, market, symbol, hk_currency, config.a_share_default_currency)
        long["currency"], long["currency_status"] = currency, status
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.loc[long["value"].notna()].copy()
    if long.empty:
        raise Stage18Blocked(f"Historical Clean observations are empty: {unit['dataset_id']}")
    report = report.loc[long.index]
    period = _period_values(report)
    for column in period.columns:
        long[column] = period[column]
    long["announcement_date"] = pd.to_datetime(long["announcement_date"], errors="coerce").dt.normalize()
    long["update_date"] = pd.to_datetime(long["update_date"], errors="coerce").dt.normalize()
    pit, eligible = _pit_status(long["announcement_date"], long["update_date"], config.as_of_date)
    long["pit_status"], long["eligible_for_as_of_date_analysis"] = pit, eligible
    long["symbol"], long["market"], long["data_category"] = symbol, market, category
    long["provider"], long["source_interface"], long["source_variant"] = unit["provider"], unit["interface"], unit["variant"]
    long["source_run_id"], long["clean_run_id"] = config.source_run_id, ""
    long["source_dataset_id"], long["source_sha256"] = unit["dataset_id"], unit["sha256"]
    long["schema_version"] = config.clean_schema_version
    return long


def _apply_field_mapping(
    frame: pd.DataFrame, lookup: dict[tuple[str, str, str], MetricMapping],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    market = str(frame["market"].iloc[0])
    category = str(frame["data_category"].iloc[0])
    field_info: dict[str, tuple[str, str, str | None]] = {}
    report_rows = []
    for field in sorted(frame["source_field"].astype(str).unique()):
        item = lookup.get((market, category, field))
        canonical = item.canonical_name if item else _passthrough_name(market, category, field)
        status = "CORE_MAPPED" if item else "PASSTHROUGH_STANDARDIZED"
        explicit = item.canonical_unit if item else None
        field_info[field] = (canonical, status, explicit)
        report_rows.append({
            "market": market, "category": category, "source_field": field,
            "canonical_name": canonical, "mapping_status": status,
            "configured_unit": explicit or "inferred",
        })
    frame["canonical_name"] = frame["source_field"].map(lambda value: field_info[str(value)][0])
    frame["mapping_status"] = frame["source_field"].map(lambda value: field_info[str(value)][1])
    unit_cache: dict[tuple[str, str], tuple[str, str, float]] = {}
    source_units, canonical_units, scales = [], [], []
    for field, currency in zip(frame["source_field"].astype(str), frame["currency"].astype(str)):
        key = (field, currency)
        if key not in unit_cache:
            unit_cache[key] = _unit_info(
                market=market, category=category, source_field=field, currency=currency,
                explicit_unit=field_info[field][2],
            )
        source_unit, canonical_unit, scale = unit_cache[key]
        source_units.append(source_unit)
        canonical_units.append(canonical_unit)
        scales.append(scale)
    frame["source_unit"] = source_units
    frame["canonical_unit"] = canonical_units
    frame["scale_factor"] = np.asarray(scales, dtype="float64")
    frame["normalized_value"] = frame["value"].astype("float64") * frame["scale_factor"]
    return frame, report_rows


def _equivalent(values: Iterable[float], rtol: float, atol: float) -> bool:
    array = np.asarray(list(values), dtype="float64")
    return bool(len(array) <= 1 or np.allclose(array, array[0], rtol=rtol, atol=atol, equal_nan=True))


def deduplicate_hk_variants(
    frame: pd.DataFrame, *, priority: tuple[str, ...], rtol: float, atol: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if frame.empty:
        return frame, []
    if "source_section" not in frame.columns:
        frame = frame.copy()
        frame["source_section"] = ""
    rank = {name: index for index, name in enumerate(priority)}
    keys = ["symbol", "data_category", "report_date", "source_field"]
    duplicate_mask = frame.duplicated(keys, keep=False)
    unique = frame.loc[~duplicate_mask].copy()
    if not unique.empty:
        unique["dedup_status"] = "unique"
        unique["source_variants"] = unique["source_variant"].map(
            lambda value: json.dumps([str(value)], ensure_ascii=False)
        )
        unique["source_sections"] = unique["source_section"].map(
            lambda value: json.dumps([str(value)] if str(value) else [], ensure_ascii=False)
        )
        unique["source_dataset_ids"] = unique["source_dataset_id"].map(
            lambda value: json.dumps([str(value)], ensure_ascii=False)
        )
        unique["source_sha256s"] = unique["source_sha256"].map(
            lambda value: json.dumps([str(value)], ensure_ascii=False)
        )
    selected = []
    conflicts = []
    duplicates = frame.loc[duplicate_mask]
    for key, group in duplicates.groupby(keys, sort=True, dropna=False):
        group = group.copy()
        if not _equivalent(group["normalized_value"], rtol, atol):
            conflicts.append({
                "symbol": key[0], "category": key[1],
                "report_date": str(pd.Timestamp(key[2]).date()),
                "source_field": key[3],
                "source_variants": json.dumps(
                    sorted(group["source_variant"].astype(str).unique()), ensure_ascii=False
                ),
                "values": json.dumps([float(value) for value in group["normalized_value"]]),
                "status": "value_conflict",
            })
            continue
        group["_rank"] = group["source_variant"].map(
            lambda value: rank.get(str(value), 999)
        )
        group = group.sort_values(["_rank", "source_dataset_id"], kind="stable")
        row = group.iloc[0].copy()
        variants = sorted(
            set(group["source_variant"].astype(str)), key=lambda value: rank.get(value, 999)
        )
        row["dedup_status"] = "equivalent_duplicate"
        row["source_variants"] = json.dumps(variants, ensure_ascii=False)
        row["source_sections"] = json.dumps(
            sorted(set(group["source_section"].astype(str)) - {""}), ensure_ascii=False
        )
        row["source_dataset_ids"] = json.dumps(
            sorted(set(group["source_dataset_id"].astype(str))), ensure_ascii=False
        )
        row["source_sha256s"] = json.dumps(
            sorted(set(group["source_sha256"].astype(str))), ensure_ascii=False
        )
        selected.append(row)
    duplicate_result = pd.DataFrame(selected).drop(columns=["_rank"], errors="ignore")
    result = pd.concat([unique, duplicate_result], ignore_index=True)
    return result, conflicts

def _finalize_history(frame: pd.DataFrame, clean_run_id: str) -> pd.DataFrame:
    result = frame.copy()
    result["clean_run_id"] = clean_run_id
    if "dedup_status" not in result:
        result["dedup_status"] = "unique"
    if "source_variants" not in result:
        result["source_variants"] = result["source_variant"].map(lambda value: json.dumps([str(value)], ensure_ascii=False))
    if "source_sections" not in result:
        result["source_sections"] = result["source_section"].map(lambda value: json.dumps([str(value)] if str(value) else [], ensure_ascii=False))
    if "source_dataset_ids" not in result:
        result["source_dataset_ids"] = result["source_dataset_id"].map(lambda value: json.dumps([str(value)], ensure_ascii=False))
    if "source_sha256s" not in result:
        result["source_sha256s"] = result["source_sha256"].map(lambda value: json.dumps([str(value)], ensure_ascii=False))
    result["canonical_key"] = (
        result["symbol"].astype(str) + "|" + result["data_category"].astype(str) + "|"
        + result["report_date"].dt.strftime("%Y-%m-%d") + "|" + result["canonical_name"].astype(str)
    )
    duplicates = result["canonical_key"].duplicated(keep=False)
    if duplicates.any():
        sample = result.loc[duplicates, "canonical_key"].head(5).tolist()
        raise Stage18Blocked(f"Stage 18.3 canonical keys are not unique: {sample}")
    return result[HISTORY_COLUMNS].sort_values(
        ["market", "symbol", "report_date", "canonical_name"], kind="stable",
    ).reset_index(drop=True)


def _normalize_symbol(value: Any) -> str:
    token = str(value).upper().replace(".0", "")
    token = re.sub(r"\.(SH|SZ|BJ|HK)$", "", token)
    token = re.sub(r"^(SH|SZ|BJ|HK)", "", token)
    return token.lstrip("0") or "0"


def _valuation_clean(
    root: Path, units: list[dict[str, Any]], config: Stage183Config, clean_run_id: str,
) -> pd.DataFrame:
    output = []
    for market, symbol in sorted(
        {(str(row["market"]), str(row["symbol"])) for row in units}
    ):
        components = [row for row in units if row["market"] == market and row["symbol"] == symbol]
        values: dict[str, float] = {}
        interfaces: dict[str, str] = {}
        snapshot_times = []
        for unit in components:
            frame = pd.read_parquet(root / str(unit["data_path"]))
            if market == "A" and unit["variant"] == "valuation_comparison":
                mask = frame["代码"].map(_normalize_symbol).eq(_normalize_symbol(symbol))
                target = frame.loc[mask]
                if len(target) != 1:
                    raise Stage18Blocked(f"A valuation identity cannot be isolated: {unit['dataset_id']}")
                values["pe"] = float(pd.to_numeric(target["市盈率-TTM"], errors="coerce").iloc[0])
                values["pb"] = float(pd.to_numeric(target["市净率-MRQ"], errors="coerce").iloc[0])
                interfaces["pe"] = interfaces["pb"] = str(unit["interface"])
            elif market == "A" and unit["variant"] == "scale_comparison":
                mask = frame["代码"].map(_normalize_symbol).eq(_normalize_symbol(symbol))
                target = frame.loc[mask]
                if len(target) != 1:
                    raise Stage18Blocked(f"A scale identity cannot be isolated: {unit['dataset_id']}")
                values["total_market_cap"] = float(pd.to_numeric(target["总市值"], errors="coerce").iloc[0])
                values["floating_market_cap"] = float(pd.to_numeric(target["流通市值"], errors="coerce").iloc[0])
                interfaces["market_cap"] = str(unit["interface"])
            elif market == "HK":
                if len(frame) != 1:
                    raise Stage18Blocked(f"HK valuation response is not singular: {unit['dataset_id']}")
                values.update({
                    "pe": float(pd.to_numeric(frame["市盈率"], errors="coerce").iloc[0]),
                    "pb": float(pd.to_numeric(frame["市净率"], errors="coerce").iloc[0]),
                    "total_market_cap": float(pd.to_numeric(frame["总市值(港元)"], errors="coerce").iloc[0]),
                    "floating_market_cap": float(pd.to_numeric(frame["港股市值(港元)"], errors="coerce").iloc[0]),
                })
                interfaces["pe"] = interfaces["pb"] = interfaces["market_cap"] = str(unit["interface"])
            snapshot = pd.to_datetime(unit["snapshot_time"], utc=True, errors="coerce")
            if pd.isna(snapshot):
                raise Stage18Blocked(f"Valuation snapshot time is invalid: {unit['dataset_id']}")
            snapshot_times.append(snapshot)
        if set(values) != {"pe", "pb", "total_market_cap", "floating_market_cap"} or any(not np.isfinite(value) for value in values.values()):
            raise Stage18Blocked(f"Valuation canonical fields are incomplete: {market}/{symbol}")
        output.append({
            "symbol": symbol, "market": market, "data_category": "valuation_snapshot",
            "provider": "EastmoneyDataCenter", "source_interface": "composite" if market == "A" else components[0]["interface"],
            "source_variant": "composite_current" if market == "A" else "current",
            "snapshot_time": max(snapshot_times), "analysis_as_of_date": pd.Timestamp(config.as_of_date),
            "eligible_for_as_of_date_analysis": False, "pit_status": "SNAPSHOT_NOT_BASELINE",
            "currency": "CNY" if market == "A" else "HKD", "currency_status": "interface_contract",
            **values, "pe_source_interface": interfaces["pe"], "pb_source_interface": interfaces["pb"],
            "market_cap_source_interface": interfaces["market_cap"],
            "source_component_count": len(components),
            "source_interfaces": json.dumps(sorted({str(row["interface"]) for row in components}), ensure_ascii=False),
            "source_variants": json.dumps(sorted({str(row["variant"]) for row in components}), ensure_ascii=False),
            "source_dataset_ids": json.dumps(sorted(str(row["dataset_id"]) for row in components), ensure_ascii=False),
            "source_sha256s": json.dumps(sorted(str(row["sha256"]) for row in components), ensure_ascii=False),
            "source_run_id": config.source_run_id, "clean_run_id": clean_run_id,
            "schema_version": config.clean_schema_version,
        })
    result = pd.DataFrame(output, columns=VALUATION_COLUMNS)
    if len(result) != 23 or int(result["source_component_count"].sum()) != 39:
        raise Stage18Blocked("Stage 18.3 valuation merge must produce 23 rows from 39 components")
    return result.sort_values(["market", "symbol"], kind="stable").reset_index(drop=True)


def _hk_currency_lookup(root: Path, rows: list[dict[str, Any]]) -> dict[str, str]:
    output = {}
    for unit in rows:
        if unit["market"] != "HK" or unit["category"] != "financial_indicator":
            continue
        frame = pd.read_parquet(root / str(unit["data_path"]))
        if "CURRENCY" not in frame:
            continue
        values = sorted(set(frame["CURRENCY"].dropna().astype(str).str.upper()) - {""})
        if len(values) != 1:
            raise Stage18Blocked(f"HK reporting currency is ambiguous: {unit['dataset_id']}")
        prior = output.get(str(unit["symbol"]))
        if prior and prior != values[0]:
            raise Stage18Blocked(f"HK reporting currency conflicts: {unit['symbol']}")
        output[str(unit["symbol"])] = values[0]
    return output


def _summary_frames(
    *, schema_rows: list[dict[str, Any]], mapping_rows: list[dict[str, Any]],
    temporal_rows: list[dict[str, Any]], currency_rows: list[dict[str, Any]],
    clean_status: dict[tuple[str, str, str], str], symbols: list[tuple[str, str]],
    categories: tuple[str, ...], required_core: tuple[str, ...],
) -> dict[str, pd.DataFrame]:
    schema = pd.DataFrame(schema_rows).drop_duplicates().sort_values(
        ["market", "category", "interface", "variant", "source_field"], kind="stable",
    )
    mapping = pd.DataFrame(mapping_rows).drop_duplicates().sort_values(
        ["market", "category", "source_field"], kind="stable",
    )
    coverage_rows = []
    for (market, category), group in mapping.groupby(["market", "category"], sort=True):
        core = sorted(set(group.loc[group["mapping_status"].eq("CORE_MAPPED"), "canonical_name"]))
        coverage_rows.append({
            "market": market, "category": category, "raw_metric_field_count": len(group),
            "core_mapped_field_count": int(group["mapping_status"].eq("CORE_MAPPED").sum()),
            "passthrough_mapped_field_count": int(group["mapping_status"].eq("PASSTHROUGH_STANDARDIZED").sum()),
            "unmapped_field_count": 0, "core_fields_present": json.dumps(core, ensure_ascii=False),
        })
    observed_core = set(mapping.loc[mapping["mapping_status"].eq("CORE_MAPPED"), "canonical_name"])
    missing_core = sorted(set(required_core) - observed_core)
    coverage = pd.DataFrame(coverage_rows)
    coverage["required_core_fields_missing"] = json.dumps(missing_core, ensure_ascii=False)
    temporal = pd.DataFrame(temporal_rows)
    if not temporal.empty:
        temporal = temporal.groupby(
            ["market", "category", "pit_status", "eligible_for_as_of_date_analysis"],
            dropna=False, sort=True,
        ).size().reset_index(name="row_count")
    currency = pd.DataFrame(currency_rows)
    if not currency.empty:
        currency = currency.groupby(
            ["market", "category", "currency", "currency_status"], dropna=False, sort=True,
        ).size().reset_index(name="row_count")
    clean_rows = []
    for market, symbol in sorted(symbols):
        row = {"symbol": symbol, "market": market}
        for category in categories:
            row[category] = clean_status.get(
                (market, symbol, category),
                "NOT_PLANNED" if market == "HK" and category == "financial_abstract" else "MISSING",
            )
        clean_rows.append(row)
    return {
        "schema_inventory.csv": schema,
        "field_mapping.csv": mapping,
        "mapping_coverage.csv": coverage,
        "temporal_quality.csv": temporal,
        "currency_summary.csv": currency,
        "clean_coverage.csv": pd.DataFrame(clean_rows),
    }


def run_stage18_3_standardization(
    *, root: str | Path = ".", config_path: str | Path = "config/stage18_3.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], int]:
    project_root = Path(root).resolve()
    config = load_stage18_3_config(project_root / config_path)
    if as_of_date != config.as_of_date:
        raise Stage18Blocked("Stage 18.3 as-of date differs from configuration")
    if upstream_run_id is not None and upstream_run_id != config.source_run_id:
        raise Stage18Blocked("Stage 18.3 upstream run id differs from configuration")
    now = clock or (lambda: datetime.now(timezone.utc))
    stage0_before = frozen_hashes(project_root)
    stage182_before, source_rows = _fingerprint_stage182(project_root, config)
    stage182_config = load_stage18_2_config(project_root / "config/stage18_2.yml")
    base_config = load_stage18_config(project_root / "config/stage18.yml")
    stage17_before = _stage17_fingerprint(project_root, base_config)
    stage181_before = _stage181_fingerprint(project_root, stage182_config)
    protected_before = _protected_state(project_root)
    ready = {
        "stage": 18, "substage": "18.3", "status": "READY",
        "source_run_id": config.source_run_id, "source_dataset_count": len(source_rows),
        "security_count": len({(row["market"], row["symbol"]) for row in source_rows}),
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "writes_database": False, "writes_features": False, "writes_stage19": False,
    }
    if validate_only or dry_run:
        return ready, 0
    clean_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(clean_run_id)
    except ValueError as exc:
        raise Stage18Blocked("Stage 18.3 run_id must be a UUID") from exc
    report_dir = project_root / config.reports_root / clean_run_id
    clean_run_root = project_root / config.clean_root / f"run_id={clean_run_id}"
    if report_dir.exists() or clean_run_root.exists():
        raise Stage18Blocked(f"Stage 18.3 run already exists: {clean_run_id}")
    started_at = now().astimezone(timezone.utc).isoformat()
    lookup = _mapping_lookup(config)
    hk_currency = _hk_currency_lookup(project_root, source_rows)
    store = Stage18CleanStore(project_root / config.clean_root)
    schema_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    temporal_rows: list[dict[str, Any]] = []
    currency_rows: list[dict[str, Any]] = []
    duplicate_conflicts: list[dict[str, Any]] = []
    clean_records: list[dict[str, Any]] = []
    clean_status: dict[tuple[str, str, str], str] = {}
    for category in HISTORY_CATEGORIES:
        units = [row for row in source_rows if row["category"] == category]
        parts = []
        category_mapping_rows = []
        for unit in units:
            frame = pd.read_parquet(project_root / str(unit["data_path"]))
            schema_rows.extend(_schema_inventory(unit, frame, lookup))
            part = _history_source_long(unit, frame, hk_currency, config)
            part, mapped = _apply_field_mapping(part, lookup)
            category_mapping_rows.extend(mapped)
            parts.append(part)
        combined = pd.concat(parts, ignore_index=True)
        a_rows, a_conflicts = deduplicate_hk_variants(
            combined.loc[combined["market"].eq("A")].copy(),
            priority=("default", "report"), rtol=config.duplicate_rtol, atol=config.duplicate_atol,
        )
        hk_rows, hk_conflicts = deduplicate_hk_variants(
            combined.loc[combined["market"].eq("HK")].copy(),
            priority=config.variant_priority, rtol=config.duplicate_rtol, atol=config.duplicate_atol,
        )
        conflicts = a_conflicts + hk_conflicts
        duplicate_conflicts.extend(conflicts)
        if conflicts:
            raise Stage18Blocked(f"Stage 18.3 unresolved duplicate conflicts: {len(conflicts)}")
        clean = _finalize_history(pd.concat([a_rows, hk_rows], ignore_index=True), clean_run_id)
        mapping_rows.extend(category_mapping_rows)
        temporal_rows.extend(clean[[
            "market", "data_category", "pit_status", "eligible_for_as_of_date_analysis"
        ]].rename(columns={"data_category": "category"}).to_dict("records"))
        currency_rows.extend(clean[[
            "market", "data_category", "currency", "currency_status"
        ]].rename(columns={"data_category": "category"}).to_dict("records"))
        for market, symbol in clean[["market", "symbol"]].drop_duplicates().itertuples(index=False):
            clean_status[(market, symbol, category)] = "PASS"
        source_units = [unit["dataset_id"] for unit in units]
        metadata = {
            "stage": 18, "substage": "18.3", "run_id": clean_run_id,
            "category": category, "status": "PASS", "asset_role": config.asset_role,
            "source_stage18_2_run_id": config.source_run_id,
            "source_dataset_count": len(units), "source_dataset_ids": source_units,
            "analysis_as_of_date": config.as_of_date.isoformat(),
            "schema_version": config.clean_schema_version,
            "writes_database": False, "writes_features": False, "writes_stage19": False,
        }
        stored = store.write(run_id=clean_run_id, category=category, frame=clean, metadata=metadata)
        clean_records.append(stored)
        del combined, a_rows, hk_rows, clean, parts
    valuation_units = [row for row in source_rows if row["category"] == "valuation_snapshot"]
    for unit in valuation_units:
        frame = pd.read_parquet(project_root / str(unit["data_path"]))
        schema_rows.extend(_schema_inventory(unit, frame, lookup))
        for field in frame.columns:
            name = str(field)
            if name in GOVERNANCE_COLUMNS:
                continue
            item = lookup.get((str(unit["market"]), "valuation_snapshot", name))
            mapping_rows.append({
                "market": unit["market"], "category": "valuation_snapshot", "source_field": name,
                "canonical_name": item.canonical_name if item else _passthrough_name(str(unit["market"]), "valuation_snapshot", name),
                "mapping_status": "CORE_MAPPED" if item else "PASSTHROUGH_STANDARDIZED",
                "configured_unit": item.canonical_unit if item else "inferred",
            })
    valuation = _valuation_clean(project_root, valuation_units, config, clean_run_id)
    temporal_rows.extend(valuation[[
        "market", "data_category", "pit_status", "eligible_for_as_of_date_analysis"
    ]].rename(columns={"data_category": "category"}).to_dict("records"))
    currency_rows.extend(valuation[[
        "market", "data_category", "currency", "currency_status"
    ]].rename(columns={"data_category": "category"}).to_dict("records"))
    for market, symbol in valuation[["market", "symbol"]].itertuples(index=False):
        clean_status[(market, symbol, "valuation_snapshot")] = "PASS"
    stored = store.write(
        run_id=clean_run_id, category="valuation_snapshot", frame=valuation,
        metadata={
            "stage": 18, "substage": "18.3", "run_id": clean_run_id,
            "category": "valuation_snapshot", "status": "PASS", "asset_role": config.asset_role,
            "source_stage18_2_run_id": config.source_run_id,
            "source_dataset_count": len(valuation_units),
            "source_dataset_ids": [unit["dataset_id"] for unit in valuation_units],
            "source_component_count": int(valuation["source_component_count"].sum()),
            "analysis_as_of_date": config.as_of_date.isoformat(),
            "eligible_for_as_of_date_analysis": False,
            "schema_version": config.clean_schema_version,
            "writes_database": False, "writes_features": False, "writes_stage19": False,
        },
    )
    clean_records.append(stored)
    symbols = sorted({(str(row["market"]), str(row["symbol"])) for row in source_rows})
    reports = _summary_frames(
        schema_rows=schema_rows, mapping_rows=mapping_rows, temporal_rows=temporal_rows,
        currency_rows=currency_rows, clean_status=clean_status, symbols=symbols,
        categories=config.categories, required_core=config.required_core_fields,
    )
    duplicate_frame = pd.DataFrame(duplicate_conflicts, columns=[
        "symbol", "category", "report_date", "source_field", "source_variants", "values", "status",
    ])
    reports["duplicate_conflicts.csv"] = duplicate_frame
    mapping_missing = json.loads(reports["mapping_coverage.csv"]["required_core_fields_missing"].iloc[0])
    clean_coverage = reports["clean_coverage.csv"]
    missing_clean = int((clean_coverage.drop(columns=["symbol", "market"]) == "MISSING").sum().sum())
    stage0_after = frozen_hashes(project_root)
    stage182_after, _ = _fingerprint_stage182(project_root, config)
    stage17_after = _stage17_fingerprint(project_root, base_config)
    stage181_after = _stage181_fingerprint(project_root, stage182_config)
    protected_after = _protected_state(project_root)
    clean_files = sorted(path for path in clean_run_root.rglob("*") if path.is_file())
    tmp_count = sum(path.name.endswith(".tmp") for path in clean_files)
    hash_mismatch = 0
    for record in clean_records:
        if file_sha256(record["data_path"]) != record["data_sha256"]:
            hash_mismatch += 1
    checks = {
        "upstream_closed_set": (len(source_rows) == 175, len(source_rows), 175),
        "security_coverage": (len(symbols) == 23 and missing_clean == 0, len(symbols), 23),
        "six_categories": (len(clean_records) == 6, len(clean_records), 6),
        "key_mapping_missing": (not mapping_missing, len(mapping_missing), 0),
        "duplicate_conflicts": (duplicate_frame.empty, len(duplicate_frame), 0),
        "snapshot_governance": (
            len(valuation) == 23
            and int(valuation["source_component_count"].sum()) == 39
            and not valuation["eligible_for_as_of_date_analysis"].any(),
            len(valuation), 23,
        ),
        "stage0_unchanged": (stage0_before == stage0_after, stage0_after, stage0_before),
        "stage17_unchanged": (stage17_before == stage17_after, stage17_after, stage17_before),
        "stage18_1_unchanged": (stage181_before == stage181_after, stage181_after, stage181_before),
        "stage18_2_unchanged": (stage182_before == stage182_after, stage182_after, stage182_before),
        "protected_assets_unchanged": (protected_before == protected_after, protected_after, protected_before),
        "clean_closed_world": (len(clean_files) == 12, len(clean_files), 12),
        "clean_sha256": (hash_mismatch == 0, hash_mismatch, 0),
        "temporary_files": (tmp_count == 0, tmp_count, 0),
    }
    quality = pd.DataFrame([
        {
            "check_name": name, "status": "PASS" if value[0] else "BLOCKED",
            "observed": json.dumps(value[1], ensure_ascii=False, default=str) if not isinstance(value[1], (str, int, float, bool)) else value[1],
            "expected": json.dumps(value[2], ensure_ascii=False, default=str) if not isinstance(value[2], (str, int, float, bool)) else value[2],
        }
        for name, value in checks.items()
    ])
    reports["quality_report.csv"] = quality
    report_dir.mkdir(parents=True, exist_ok=False)
    for name, frame in reports.items():
        _atomic_csv(report_dir / name, frame, must_not_exist=True)
    status = "PASS" if quality["status"].eq("PASS").all() else "BLOCKED"
    report_files = [report_dir / name for name in reports]
    manifest_files = [
        file_record(path, project_root)
        for path in sorted(clean_files + report_files, key=lambda item: item.as_posix())
    ]
    finished_at = now().astimezone(timezone.utc).isoformat()
    run_report = {
        "stage": 18, "substage": "18.3", "run_id": clean_run_id, "status": status,
        "started_at": started_at, "finished_at": finished_at,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "upstream_stage18_2_run_id": config.source_run_id,
        "source_dataset_count": len(source_rows), "security_count": len(symbols),
        "clean_category_count": len(clean_records),
        "clean_row_counts": {record["category"]: record["row_count"] for record in clean_records},
        "clean_file_count": len(clean_files), "manifest_file_count": len(manifest_files),
        "key_mapping_missing_count": len(mapping_missing),
        "duplicate_conflict_count": len(duplicate_frame),
        "valuation_clean_row_count": len(valuation),
        "valuation_source_component_count": int(valuation["source_component_count"].sum()),
        "stage0_hashes_before": stage0_before, "stage0_hashes_after": stage0_after,
        "stage0_hashes_unchanged": stage0_before == stage0_after,
        "stage17_evidence_before": stage17_before, "stage17_evidence_after": stage17_after,
        "stage17_unchanged": stage17_before == stage17_after,
        "stage18_1_evidence_before": stage181_before, "stage18_1_evidence_after": stage181_after,
        "stage18_1_unchanged": stage181_before == stage181_after,
        "stage18_2_evidence_before": stage182_before, "stage18_2_evidence_after": stage182_after,
        "stage18_2_unchanged": stage182_before == stage182_after,
        "database_file_count": protected_after["database/stage18"]["file_count"],
        "feature_file_count": protected_after["data/features/stage18"]["file_count"],
        "stage19_asset_count": (
            protected_after["data/raw/stage19"]["file_count"]
            + protected_after["reports/stage19"]["file_count"]
        ),
        "stage18_4_authorized": status == "PASS", "stage18_4_started": False,
        "known_test_debt": {
            "node_id": "tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset",
            "signature": "expected returncode 1, observed returncode 0",
        },
    }
    manifest = {
        "stage": 18, "substage": "18.3", "run_id": clean_run_id, "status": status,
        "upstream_stage18_2_run_id": config.source_run_id,
        "clean_datasets": [
            {
                "category": record["category"], "row_count": record["row_count"],
                "schema_hash": record["schema_hash"], "data_sha256": record["data_sha256"],
                "data_path": str(Path(record["data_path"]).resolve().relative_to(project_root).as_posix()),
                "metadata_path": str(Path(record["metadata_path"]).resolve().relative_to(project_root).as_posix()),
            }
            for record in clean_records
        ],
        "files": manifest_files,
        "manifest_closed_world": status == "PASS",
    }
    _atomic_text(report_dir / "stage18_3_run.json", json.dumps(run_report, ensure_ascii=False, indent=2, default=str) + "\n")
    _atomic_text(report_dir / "stage18_3_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n")
    return run_report, 0 if status == "PASS" else 2
