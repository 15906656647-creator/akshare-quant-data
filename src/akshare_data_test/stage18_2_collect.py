"""Stage 18.2 formal 23-security fundamental Raw collection."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .adapters.stage18_valuation import Stage18ValuationAdapter
from .stage18_2_config import CollectionSpec, Stage182Config, load_stage18_2_config
from .stage18_audit import (
    ANNOUNCEMENT_TOKENS, REPORT_DATE_TOKENS, Security, Stage18Blocked,
    _atomic_csv, _atomic_text, _date_evidence, _relative, frozen_hashes,
    validate_upstream,
)
from .stage18_config import load_stage18_config
from .stage18_reaudit import _stage17_fingerprint, _verify_records
from .stage18_valuation_audit import _column_for
from .storage.raw_store import file_record, file_sha256, schema_hash
from .storage.stage18_fundamental_raw_store import Stage18FundamentalRawStore


UPDATE_TOKENS = ("update_date", "updated_at", "update_time", "更新时间", "更新日期")
CURRENCY_TOKENS = ("currency", "币种", "货币")
SENSITIVE_RE = re.compile(r"(?i)(token|cookie|authorization|password|api[_-]?key|proxy)")
STATUS_PRIORITY = {"BLOCKED": 4, "FAIL": 3, "UNAVAILABLE": 2, "PASS": 1}
COVERAGE_CATEGORIES = (
    "financial_abstract", "financial_indicator", "balance_sheet",
    "income_statement", "cash_flow_statement", "valuation_snapshot",
)
DOWNSTREAM_ROOTS = (
    "data/clean/stage18", "data/features/stage18", "database/stage18",
    "data/raw/stage19", "reports/stage19",
)


@dataclass(frozen=True)
class PlanUnit:
    dataset_id: str
    market: str
    symbol: str
    category: str
    interface: str
    provider: str
    variant: str
    parameters: dict[str, Any]
    expected_temporality: str
    required_identity: str


PLAN_COLUMNS = [
    "dataset_id", "market", "symbol", "category", "interface", "provider",
    "variant", "parameters", "expected_temporality", "required_identity",
]
RESULT_COLUMNS = PLAN_COLUMNS + [
    "status", "request_time", "finished_at", "snapshot_time", "attempt_count",
    "attempts", "row_count", "columns", "schema_hash", "earliest_date",
    "latest_date", "report_date_field", "announcement_date_field",
    "update_date_field", "currency", "currency_field", "identity_status",
    "available_valuation_fields", "error_type", "error_message", "sha256",
    "data_path", "metadata_path", "asset_role", "audit_only",
    "eligible_for_as_of_date_analysis", "eligible_for_stage18_3_standardization",
]


def _safe_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): ("<redacted>" if SENSITIVE_RE.search(str(key)) else value)
        for key, value in parameters.items()
    }


def _parameters(security: Security, spec: CollectionSpec, variant: str) -> dict[str, Any]:
    plain = security.symbol.replace(".HK", "")
    if security.market == "A":
        em = security.exchange + plain
        if spec.interface == "stock_financial_abstract":
            return {"symbol": plain}
        if spec.interface == "stock_financial_analysis_indicator":
            return {"symbol": plain, "start_year": "1900"}
        if spec.interface in {
            "stock_balance_sheet_by_report_em", "stock_profit_sheet_by_report_em",
            "stock_cash_flow_sheet_by_report_em", "stock_zh_valuation_comparison_em",
            "stock_zh_scale_comparison_em",
        }:
            return {"symbol": em}
    indicator = "年度" if variant == "annual" else "报告期"
    if spec.interface == "stock_financial_hk_analysis_indicator_em":
        return {"symbol": plain, "indicator": indicator}
    if spec.interface == "stock_financial_hk_report_em":
        statement = {
            "balance_sheet": "资产负债表", "income_statement": "利润表",
            "cash_flow_statement": "现金流量表",
        }[spec.category]
        return {"stock": plain, "symbol": statement, "indicator": indicator}
    if spec.interface == "stock_hk_financial_indicator_em":
        return {"symbol": plain}
    raise ValueError(f"No Stage 18.2 parameter mapping for {spec.interface}/{variant}")


def build_collection_plan(
    securities: list[Security], config: Stage182Config,
) -> list[PlanUnit]:
    ordered = sorted(securities, key=lambda item: (item.market != "A", item.symbol))
    rows = []
    for security in ordered:
        for spec in config.collections[security.market]:
            for variant in spec.variants:
                dataset_id = ":".join((
                    security.market, security.symbol, spec.category, spec.interface, variant,
                ))
                rows.append(PlanUnit(
                    dataset_id=dataset_id, market=security.market, symbol=security.symbol,
                    category=spec.category, interface=spec.interface,
                    provider=spec.provider, variant=variant,
                    parameters=_parameters(security, spec, variant),
                    expected_temporality=(
                        "snapshot" if spec.category == "valuation_snapshot" else "history"
                    ),
                    required_identity="request_parameter_bound",
                ))
    if len(rows) != 175 or len({item.dataset_id for item in rows}) != 175:
        raise Stage18Blocked("Stage 18.2 collection plan is not the expected 175-unit closed set")
    return rows


def _plan_frame(plan: list[PlanUnit]) -> pd.DataFrame:
    rows = []
    for item in plan:
        row = asdict(item)
        row["parameters"] = json.dumps(_safe_parameters(item.parameters), ensure_ascii=False, sort_keys=True)
        rows.append(row)
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Stage18Blocked(f"Missing or invalid Stage 18.2 upstream evidence: {path}") from exc
    if not isinstance(value, dict):
        raise Stage18Blocked(f"Expected JSON object: {path}")
    return value


def _stage181_fingerprint(root: Path, config: Stage182Config) -> dict[str, Any]:
    run_path = root / config.stage18_1_run_path
    manifest_path = root / config.stage18_1_manifest_path
    run = _json_object(run_path)
    manifest = _json_object(manifest_path)
    if (
        run.get("run_id") != config.stage18_1_run_id
        or run.get("status") != config.stage18_1_status
        or run.get("stage18_2_authorized") is not config.stage18_2_authorized
        or run.get("stage18_2_started") is not False
        or manifest.get("run_id") != config.stage18_1_run_id
        or manifest.get("status") != config.stage18_1_status
    ):
        raise Stage18Blocked("Stage 18.1 PASS/authorization evidence differs")
    rows = manifest.get("inventory_rows", [])
    if not rows or not all(
        item.get("asset_role") == "interface_audit"
        and item.get("audit_only") is True
        and item.get("eligible_for_stage18_2_ingestion") is False
        for item in rows if item.get("provider_role") != "frozen_rejected_provider"
    ):
        raise Stage18Blocked("Stage 18.1 audit Raw isolation evidence differs")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise Stage18Blocked("Stage 18.1 manifest files are missing")
    return {
        "run_id": config.stage18_1_run_id,
        "run_sha256": file_sha256(run_path),
        "manifest_sha256": file_sha256(manifest_path),
        "file_count": len(files),
        "tree_sha256": _verify_records(root, files, size_key="size"),
    }


def _tree_state(root: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for relative in DOWNSTREAM_ROOTS:
        target = root / relative
        files = sorted(item for item in target.rglob("*") if item.is_file()) if target.exists() else []
        payload = [(item.relative_to(root).as_posix(), item.stat().st_size, file_sha256(item)) for item in files]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        result[relative] = {
            "file_count": len(files),
            "tree_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }
    return result


def _field_names(frame: pd.DataFrame, tokens: tuple[str, ...]) -> list[str]:
    result = []
    for column in frame.columns:
        lowered = str(column).casefold()
        if any(token in lowered for token in tokens):
            result.append(str(column))
    return result


def _date_metadata(frame: pd.DataFrame) -> dict[str, Any]:
    earliest, latest, _announcement = _date_evidence(frame)
    report_fields = _field_names(frame, REPORT_DATE_TOKENS)
    announcement_fields = _field_names(frame, ANNOUNCEMENT_TOKENS)
    update_fields = _field_names(frame, UPDATE_TOKENS)
    if not report_fields:
        report_fields = [
            str(column) for column in frame.columns
            if _parse_column_date(column)
        ]
    currency_fields = _field_names(frame, CURRENCY_TOKENS)
    currency_values = []
    for field in currency_fields:
        currency_values.extend(str(value) for value in frame[field].dropna().unique()[:10])
    return {
        "earliest_date": earliest, "latest_date": latest,
        "report_date_field": json.dumps(report_fields, ensure_ascii=False),
        "announcement_date_field": json.dumps(announcement_fields, ensure_ascii=False),
        "update_date_field": json.dumps(update_fields, ensure_ascii=False),
        "currency_field": json.dumps(currency_fields, ensure_ascii=False),
        "currency": json.dumps(sorted(set(currency_values)), ensure_ascii=False),
    }


def _parse_column_date(value: Any) -> bool:
    try:
        parsed = pd.to_datetime(str(value), errors="raise")
    except (ValueError, TypeError, OverflowError):
        return False
    return 1900 <= parsed.year <= 2100


def _normalize_symbol(value: Any) -> str:
    token = str(value).upper().replace(".0", "")
    token = re.sub(r"\.(SH|SZ|BJ|HK)$", "", token)
    token = re.sub(r"^(SH|SZ|BJ|HK)", "", token)
    return token.lstrip("0") or "0"


def _identity_status(frame: pd.DataFrame, unit: PlanUnit) -> str:
    code_column = _column_for(frame, "symbol")
    if code_column is None:
        return "request_parameter_bound"
    expected = _normalize_symbol(unit.symbol)
    observed = set(frame[code_column].dropna().map(_normalize_symbol))
    return "response_identity_match" if expected in observed else "response_identity_mismatch"


def _valuation_fields(frame: pd.DataFrame) -> set[str]:
    fields = {"symbol", "snapshot_time"}
    for semantic in ("pe", "pb", "total_market_cap", "floating_market_cap", "hk_market_cap"):
        column = _column_for(frame, semantic)
        if column is not None and pd.to_numeric(frame[column], errors="coerce").notna().any():
            fields.add(semantic)
    return fields


def _required_component_fields(unit: PlanUnit) -> set[str]:
    if unit.interface == "stock_zh_valuation_comparison_em":
        return {"symbol", "pe", "pb", "snapshot_time"}
    if unit.interface == "stock_zh_scale_comparison_em":
        return {"symbol", "total_market_cap", "floating_market_cap", "snapshot_time"}
    if unit.interface == "stock_hk_financial_indicator_em":
        return {"symbol", "pe", "pb", "total_market_cap", "snapshot_time"}
    return set()


def _collect_one(
    unit: PlanUnit, *, root: Path, run_id: str, config: Stage182Config,
    store: Stage18FundamentalRawStore, adapter: Any,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    exists, signature, _module, _source = adapter.inspect_function(unit.interface)
    request_time = clock().astimezone(timezone.utc).isoformat()
    call = adapter.call(
        unit.interface, unit.parameters, max_attempts=config.max_attempts,
        retry_delay_seconds=config.retry_delay_seconds,
        timeout_seconds=config.request_timeout_seconds,
    )
    finished_at = clock().astimezone(timezone.utc).isoformat()
    frame = call.dataframe
    identity = "not_checked"
    date_info = {
        "earliest_date": "", "latest_date": "", "report_date_field": "[]",
        "announcement_date_field": "[]", "update_date_field": "[]",
        "currency_field": "[]", "currency": "[]",
    }
    fields: set[str] = set()
    if frame is not None and not frame.empty:
        identity = _identity_status(frame, unit)
        date_info = _date_metadata(frame)
        if unit.expected_temporality == "snapshot":
            fields = _valuation_fields(frame)
    if not exists or call.status == "unavailable" or call.error_type == "function_missing":
        status, error_type = "UNAVAILABLE", "function_missing"
    elif call.status != "success" or frame is None or frame.empty:
        status, error_type = "FAIL", call.error_type or "unexplained_empty_result"
    elif identity == "response_identity_mismatch":
        status, error_type = "FAIL", "identity_mismatch"
    elif unit.expected_temporality == "history" and not date_info["earliest_date"]:
        status, error_type = "FAIL", "report_date_unparseable"
    elif unit.expected_temporality == "snapshot" and not _required_component_fields(unit).issubset(fields):
        status, error_type = "FAIL", "valuation_semantic_gap"
    else:
        status, error_type = "PASS", ""
    snapshot_time = finished_at if unit.expected_temporality == "snapshot" else ""
    error_message = call.error_message[:500]
    metadata = {
        "stage": 18, "substage": "18.2", "run_id": run_id,
        "dataset_id": unit.dataset_id, "symbol": unit.symbol, "market": unit.market,
        "provider": unit.provider, "interface": unit.interface,
        "request_parameters": _safe_parameters(unit.parameters),
        "request_time": request_time, "finished_at": finished_at,
        "report_variant": unit.variant, "expected_temporality": unit.expected_temporality,
        **date_info, "snapshot_time": snapshot_time,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "eligible_for_as_of_date_analysis": False,
        "identity_status": identity, "available_valuation_fields": sorted(fields),
        "status": status, "error_type": error_type, "error_message": error_message,
        "attempt_count": call.attempt_count,
        "attempts": [item.__dict__ for item in call.attempts],
        "akshare_version": adapter.akshare_version, "function_signature": signature,
        "asset_role": "fundamental_raw", "audit_only": False,
        "eligible_for_stage18_3_standardization": status == "PASS",
        "source_stage17_run_id": config.stage17_run_id,
        "authorization_stage18_1_run_id": config.stage18_1_run_id,
    }
    directory = store.dataset_dir(
        category=unit.category, run_id=run_id, market=unit.market,
        symbol=unit.symbol, variant=unit.variant,
    )
    try:
        stored = store.write(
            frame if status == "PASS" and frame is not None and not frame.empty else None,
            directory,
            metadata,
        )
    except Exception as exc:
        status, error_type, error_message = "BLOCKED", "raw_write_error", str(exc)[:500]
        stored = {
            "data_path": None, "metadata_path": directory / "metadata.json",
            "data_sha256": "", "row_count": 0, "columns": [], "schema_hash": "",
        }
    result = asdict(unit)
    result["parameters"] = json.dumps(_safe_parameters(unit.parameters), ensure_ascii=False, sort_keys=True)
    result.update({
        "status": status, "request_time": request_time, "finished_at": finished_at,
        "snapshot_time": snapshot_time, "attempt_count": call.attempt_count,
        "attempts": json.dumps([item.__dict__ for item in call.attempts], ensure_ascii=False),
        "row_count": int(stored.get("row_count", 0)),
        "columns": json.dumps(stored.get("columns", []), ensure_ascii=False),
        "schema_hash": stored.get("schema_hash", ""), **date_info,
        "identity_status": identity,
        "available_valuation_fields": json.dumps(sorted(fields), ensure_ascii=False),
        "error_type": error_type, "error_message": error_message,
        "sha256": stored.get("data_sha256", ""),
        "data_path": "" if stored.get("data_path") is None else _relative(stored["data_path"], root),
        "metadata_path": _relative(stored["metadata_path"], root),
        "asset_role": "fundamental_raw", "audit_only": False,
        "eligible_for_as_of_date_analysis": False,
        "eligible_for_stage18_3_standardization": status == "PASS",
    })
    return result


def _aggregate_status(values: pd.Series) -> str:
    tokens = [str(item) for item in values]
    return max(tokens, key=lambda item: STATUS_PRIORITY[item]) if tokens else "NOT_PLANNED"


def _coverage(results: pd.DataFrame, securities: list[Security]) -> pd.DataFrame:
    rows = []
    for security in sorted(securities, key=lambda item: (item.market != "A", item.symbol)):
        subset = results[results["symbol"].eq(security.symbol)]
        row = {"symbol": security.symbol, "market": security.market}
        for category in COVERAGE_CATEGORIES:
            row[category] = _aggregate_status(subset.loc[subset["category"].eq(category), "status"])
        rows.append(row)
    return pd.DataFrame(rows)


def _provider_summary(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby(["market", "provider", "interface", "category", "status"], dropna=False)
        .agg(dataset_count=("dataset_id", "count"), total_rows=("row_count", "sum"))
        .reset_index()
    )


def _quality_rows(checks: dict[str, tuple[bool, Any, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "check_name": name, "status": "PASS" if passed else "BLOCKED",
            "observed": json.dumps(observed, ensure_ascii=False, default=str),
            "expected": json.dumps(expected, ensure_ascii=False, default=str),
        }
        for name, (passed, observed, expected) in checks.items()
    ])


def run_stage18_2_collection(
    *, root: str | Path = ".", config_path: str | Path = "config/stage18_2.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False, adapter: Any | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, Any], int]:
    repo = Path(root).resolve()
    path = Path(config_path)
    if not path.is_absolute():
        path = repo / path
    config = load_stage18_2_config(path)
    if as_of_date != config.as_of_date:
        raise ValueError("Stage 18.2 as_of_date differs from frozen configuration")
    if upstream_run_id is not None and upstream_run_id != config.stage18_1_run_id:
        raise ValueError("Stage 18.2 upstream run_id must be the frozen Stage 18.1 run")
    base_path = config.stage18_config_path
    if not base_path.is_absolute():
        base_path = repo / base_path
    base_config = load_stage18_config(base_path)
    if base_config.upstream_run_id != config.stage17_run_id:
        raise Stage18Blocked("Stage 18.2 Stage 17 lineage differs")
    stage0_before = frozen_hashes(repo)
    securities = validate_upstream(repo, base_config)
    if (
        sum(item.market == "A" for item in securities) != config.expected_a_shares
        or sum(item.market == "HK" for item in securities) != config.expected_h_shares
    ):
        raise Stage18Blocked("Stage 18.2 security scope differs from 16 A + 7 H")
    stage181_before = _stage181_fingerprint(repo, config)
    stage17_before = _stage17_fingerprint(repo, base_config)
    downstream_before = _tree_state(repo)
    plan = build_collection_plan(securities, config)
    preview = {
        "stage": 18, "substage": "18.2", "status": "READY",
        "upstream_stage17_run_id": config.stage17_run_id,
        "upstream_stage18_1_run_id": config.stage18_1_run_id,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "security_count": len(securities), "a_share_count": 16, "h_share_count": 7,
        "planned_dataset_count": len(plan), "network_call_count": len(plan),
        "writes_formal_raw": True, "writes_database": False,
        "writes_features": False, "starts_stage19": False,
    }
    if validate_only or dry_run:
        return preview, 0
    actual_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(actual_run_id)
    except ValueError as exc:
        raise ValueError("Stage 18.2 run_id must be a UUID") from exc
    report_dir = repo / config.reports_root / actual_run_id
    if report_dir.exists():
        raise FileExistsError(f"Stage 18.2 report run already exists: {report_dir}")
    for category in COVERAGE_CATEGORIES:
        if (repo / config.raw_root / category / f"run_id={actual_run_id}").exists():
            raise FileExistsError(f"Stage 18.2 Raw run already exists: {actual_run_id}")
    plan_path = report_dir / "fundamental_collection_plan.csv"
    _atomic_csv(plan_path, _plan_frame(plan), must_not_exist=True)
    store = Stage18FundamentalRawStore(repo / config.raw_root)
    actual_adapter = adapter or Stage18ValuationAdapter()
    started_at = clock().astimezone(timezone.utc).isoformat()
    rows = [
        _collect_one(
            item, root=repo, run_id=actual_run_id, config=config, store=store,
            adapter=actual_adapter, clock=clock,
        )
        for item in plan
    ]
    results = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    coverage = _coverage(results, securities)
    provider = _provider_summary(results)
    stage0_after = frozen_hashes(repo)
    stage17_after = _stage17_fingerprint(repo, base_config)
    stage181_after = _stage181_fingerprint(repo, config)
    downstream_after = _tree_state(repo)
    raw_files = []
    for category in COVERAGE_CATEGORIES:
        category_root = repo / config.raw_root / category / f"run_id={actual_run_id}"
        raw_files.extend(item for item in category_root.rglob("*") if item.is_file())
    raw_files = sorted(raw_files)
    metadata_paths = [item for item in raw_files if item.name == "metadata.json"]
    metadata = [_json_object(item) for item in metadata_paths]
    success = results[results["status"].eq("PASS")]
    hash_ok = all(
        row.sha256 and file_sha256(repo / row.data_path) == row.sha256
        for row in success.itertuples(index=False)
    )
    metadata_ok = all(
        item.get("asset_role") == "fundamental_raw"
        and item.get("audit_only") is False
        and item.get("run_id") == actual_run_id
        for item in metadata
    )
    snapshot_rows = results[results["expected_temporality"].eq("snapshot")]
    snapshot_time_ok = (
        snapshot_rows["snapshot_time"].astype(str).str.len().gt(0).all()
        and not snapshot_rows["eligible_for_as_of_date_analysis"].any()
    )
    checks = {
        "security_scope": (len(securities) == 23, len(securities), 23),
        "collection_plan_closed_set": (len(plan) == 175, len(plan), 175),
        "all_plan_units_terminal": (len(results) == 175 and results["status"].notna().all(), len(results), 175),
        "fail_count": (not results["status"].eq("FAIL").any(), int(results["status"].eq("FAIL").sum()), 0),
        "blocked_count": (not results["status"].eq("BLOCKED").any(), int(results["status"].eq("BLOCKED").sum()), 0),
        "successful_raw_nonempty": ((success["row_count"] > 0).all(), int((success["row_count"] > 0).sum()), len(success)),
        "successful_raw_hash": (hash_ok, hash_ok, True),
        "raw_metadata_identity": (metadata_ok and len(metadata) == 175, len(metadata), 175),
        "snapshot_time_governance": (snapshot_time_ok, snapshot_time_ok, True),
        "raw_closed_world": (len(raw_files) == len(metadata) + len(success), len(raw_files), len(metadata) + len(success)),
        "temporary_files": (not any(item.suffix == ".tmp" for item in raw_files), sum(item.suffix == ".tmp" for item in raw_files), 0),
        "stage0_hash_unchanged": (stage0_before == stage0_after, stage0_after, stage0_before),
        "stage17_raw_unchanged": (stage17_before == stage17_after, stage17_after, stage17_before),
        "stage18_1_audit_unchanged": (stage181_before == stage181_after, stage181_after, stage181_before),
        "downstream_assets_unchanged": (downstream_before == downstream_after, downstream_after, downstream_before),
    }
    quality = _quality_rows(checks)
    status = "PASS" if quality["status"].eq("PASS").all() else "BLOCKED"
    finished_at = clock().astimezone(timezone.utc).isoformat()
    coverage_path = report_dir / "fundamental_coverage.csv"
    provider_path = report_dir / "provider_summary.csv"
    quality_path = report_dir / "quality_report.csv"
    _atomic_csv(coverage_path, coverage, must_not_exist=True)
    _atomic_csv(provider_path, provider, must_not_exist=True)
    _atomic_csv(quality_path, quality, must_not_exist=True)
    run_payload = {
        "stage": 18, "substage": "18.2", "run_id": actual_run_id,
        "status": status, "started_at": started_at, "finished_at": finished_at,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "upstream_stage17_run_id": config.stage17_run_id,
        "upstream_stage18_1_run_id": config.stage18_1_run_id,
        "security_count": 23, "a_share_count": 16, "h_share_count": 7,
        "planned_dataset_count": len(plan), "terminal_dataset_count": len(results),
        "status_counts": {key: int(value) for key, value in results["status"].value_counts().items()},
        "successful_raw_dataset_count": len(success),
        "raw_file_count": len(raw_files), "metadata_count": len(metadata),
        "raw_closed_world": checks["raw_closed_world"][0],
        "sha256_mismatch_count": 0 if hash_ok else 1,
        "tmp_file_count": sum(item.suffix == ".tmp" for item in raw_files),
        "stage0_hashes_before": stage0_before, "stage0_hashes_after": stage0_after,
        "stage0_hashes_unchanged": stage0_before == stage0_after,
        "stage17_evidence_before": stage17_before, "stage17_evidence_after": stage17_after,
        "stage17_raw_unchanged": stage17_before == stage17_after,
        "stage18_1_evidence_before": stage181_before, "stage18_1_evidence_after": stage181_after,
        "stage18_1_audit_raw_unchanged": stage181_before == stage181_after,
        "downstream_assets_before": downstream_before,
        "downstream_assets_after": downstream_after,
        "formal_fact_table_count": 0, "feature_count": 0, "stage19_asset_count": 0,
        "stage18_3_authorized": status == "PASS", "stage18_3_started": False,
        "akshare_version": actual_adapter.akshare_version,
        "python_version": platform.python_version(),
        "known_test_debt": {
            "node_id": "tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset",
            "signature": "expected returncode 1, observed returncode 0",
        },
    }
    output_files = [plan_path, coverage_path, provider_path, quality_path]
    manifest = {
        "stage": 18, "substage": "18.2", "run_id": actual_run_id,
        "status": status, "upstream_stage17_run_id": config.stage17_run_id,
        "upstream_stage18_1_run_id": config.stage18_1_run_id,
        "collection_plan_rows": _plan_frame(plan).to_dict("records"),
        "result_rows": results.to_dict("records"),
        "files": [file_record(item, repo) for item in raw_files + output_files],
        "raw_manifest_closed_world": True,
    }
    _atomic_text(report_dir / "stage18_2_run.json", json.dumps(run_payload, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    _atomic_text(report_dir / "stage18_2_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    return run_payload, 0 if status == "PASS" else 2
