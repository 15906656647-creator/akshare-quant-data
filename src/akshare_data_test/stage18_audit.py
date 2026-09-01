"""Stage 18.1 fundamental interface capability audit."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import pandas as pd

from .adapters.stage18_fundamentals import Stage18FundamentalAdapter
from .stage18_config import Stage18Config, load_stage18_config
from .storage.raw_store import file_record, file_sha256, schema_hash
from .storage.stage18_raw_store import Stage18RawStore


FROZEN_STAGE0_FILES = (
    "config/universe.yml",
    "config/metric_definition.yml",
    "docs/stage0_scope.md",
)
INVENTORY_COLUMNS = [
    "run_id", "interface", "function_signature", "market", "symbol", "provider",
    "request_parameters", "request_time", "outcome", "status", "row_count",
    "columns", "earliest_date", "latest_date", "report_period_type",
    "announcement_date_available", "error_type", "error_message", "attempt_count",
    "duration_ms", "data_category", "data_temporality", "akshare_version",
    "snapshot_time", "analysis_as_of_date", "asset_role", "audit_only",
    "eligible_for_stage18_2_ingestion", "eligible_for_capability_assessment",
    "schema_hash", "sha256", "raw_data_path", "metadata_path",
]
REPORT_DATE_TOKENS = (
    "report_date", "reportdate", "std_report_date", "报告期", "报告日期", "截止日期", "日期",
)
ANNOUNCEMENT_TOKENS = (
    "announcement_date", "notice_date", "publish_date", "公告日期", "公告日", "披露日期",
)
VALUATION_TOKENS = (
    "pe", "pb", "市盈率", "市净率", "总市值", "流通市值", "market_cap",
)
SENSITIVE_RE = re.compile(
    r"(?i)(api[_-]?key|password|passwd|cookie|authorization|proxy|token)"
)


@dataclass(frozen=True)
class Security:
    symbol: str
    market: str
    exchange: str
    listing_date: date
    profile_metadata_path: str


@dataclass(frozen=True)
class AuditRequest:
    interface: str
    market: str
    symbol: str
    provider: str
    parameters: dict[str, Any]
    category: str
    temporality: str
    report_period_type: str
    variant: str
    filter_symbol: bool = False
    valuation_capability_required: bool = False


class Stage18Blocked(RuntimeError):
    """A governance precondition prevented the audit from calling the network."""


def _sanitize_error_message(value: Any) -> str:
    message = str(value).replace("\r", " ").replace("\n", " ")
    message = re.sub(
        r"(?i)([?&](?:ut|token|api[_-]?key|key|cookie|authorization|password)=)[^&\s]+",
        r"\1<redacted>", message,
    )
    return re.sub(r"\s+", " ", message).strip()[:500]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def frozen_hashes(root: Path) -> dict[str, str]:
    return {name: file_sha256(root / name) for name in FROZEN_STAGE0_FILES}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Stage18Blocked(f"Expected JSON object: {path}")
    return payload


def validate_upstream(root: Path, config: Stage18Config) -> list[Security]:
    report_dir = root / config.stage17_reports_root / config.upstream_run_id
    run_path = report_dir / "stage17_run.json"
    coverage_path = report_dir / "daily_coverage.csv"
    if not run_path.is_file() or not coverage_path.is_file():
        raise Stage18Blocked("Stage 17 run or daily coverage evidence is missing")
    run = _load_json(run_path)
    checks = {
        "run_id": run.get("run_id") == config.upstream_run_id,
        "status": run.get("status") == config.upstream_status,
        "stage18_authorized": run.get("stage18_authorized") is config.upstream_authorized,
        "blocked_risks": run.get("blocked_risks") == [],
        "unavailable_items": run.get("unavailable_items") == [],
        "daily_quality_pass_count": (
            run.get("counts", {}).get("daily_quality_pass_count")
            == config.expected_daily_pass
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise Stage18Blocked("Stage 17 authorization mismatch: " + ", ".join(failed))

    coverage = pd.read_csv(coverage_path, dtype={"symbol": str})
    required = {"symbol", "market", "listing_date", "quality_status"}
    missing = sorted(required.difference(coverage.columns))
    if missing:
        raise Stage18Blocked(f"Stage 17 daily coverage missing columns: {missing}")
    if len(coverage) != config.expected_daily_pass:
        raise Stage18Blocked(
            f"Stage 17 daily coverage rows={len(coverage)}, expected={config.expected_daily_pass}"
        )
    if set(coverage["quality_status"].astype(str)) != {"PASS"}:
        raise Stage18Blocked("Stage 17 daily coverage contains non-PASS rows")
    unique = coverage[["symbol", "market", "listing_date"]].drop_duplicates()

    profile_root = (
        root / config.stage17_raw_root / "equity_profile"
        / f"run_id={config.upstream_run_id}"
    )
    metadata_paths = sorted(profile_root.glob("market=*/symbol=*/metadata.json"))
    if len(metadata_paths) != config.expected_a_shares + config.expected_h_shares:
        raise Stage18Blocked(
            f"Stage 17 security profile count={len(metadata_paths)}, expected=23"
        )
    profiles: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata_path in metadata_paths:
        metadata = _load_json(metadata_path)
        key = (str(metadata.get("market")), str(metadata.get("symbol")))
        data_path = metadata_path.with_name("data.parquet")
        if (
            metadata.get("run_id") != config.upstream_run_id
            or metadata.get("quality_status") != "PASS"
            or not data_path.is_file()
            or file_sha256(data_path) != metadata.get("data_sha256")
        ):
            raise Stage18Blocked(f"Invalid Stage 17 security profile: {key}")
        profiles[key] = metadata

    securities: list[Security] = []
    for row in unique.itertuples(index=False):
        key = (str(row.market), str(row.symbol))
        metadata = profiles.get(key)
        if metadata is None:
            raise Stage18Blocked(f"Missing Stage 17 profile for {key}")
        try:
            listed = date.fromisoformat(str(row.listing_date))
        except ValueError as exc:
            raise Stage18Blocked(f"Invalid listing date for {key}") from exc
        securities.append(Security(
            symbol=key[1], market=key[0], exchange=str(metadata.get("exchange", "")),
            listing_date=listed,
            profile_metadata_path=_relative(
                profile_root / f"market={key[0]}" / f"symbol={key[1]}" / "metadata.json",
                root,
            ),
        ))
    a_count = sum(item.market == "A" for item in securities)
    h_count = sum(item.market == "HK" for item in securities)
    if (a_count, h_count) != (config.expected_a_shares, config.expected_h_shares):
        raise Stage18Blocked(
            f"Stage 17 security market counts={(a_count, h_count)}, expected="
            f"{(config.expected_a_shares, config.expected_h_shares)}"
        )
    return securities


def select_samples(securities: list[Security]) -> tuple[list[Security], list[dict[str, str]]]:
    a_shares = [item for item in securities if item.market == "A"]
    h_shares = [item for item in securities if item.market == "HK"]
    sh = sorted(
        (item for item in a_shares if item.exchange == "SH"),
        key=lambda item: (item.listing_date, item.symbol),
    )
    sz = sorted(
        (item for item in a_shares if item.exchange == "SZ"),
        key=lambda item: (item.listing_date, item.symbol),
    )
    if not sh or not sz or len(h_shares) < 2:
        raise Stage18Blocked("Cannot apply deterministic Stage 18.1 sample policy")
    selected = [sh[0], sz[0]]
    remaining_a = [item for item in a_shares if item not in selected]
    latest_date = max(item.listing_date for item in remaining_a)
    selected.append(sorted(
        (item for item in remaining_a if item.listing_date == latest_date),
        key=lambda item: item.symbol,
    )[0])
    ordered_h = sorted(h_shares, key=lambda item: (item.listing_date, item.symbol))
    selected.extend([ordered_h[0], ordered_h[-1]])
    reasons = [
        {"symbol": selected[0].symbol, "reason": "earliest_listed_SH"},
        {"symbol": selected[1].symbol, "reason": "earliest_listed_SZ"},
        {"symbol": selected[2].symbol, "reason": "latest_listed_remaining_A"},
        {"symbol": selected[3].symbol, "reason": "earliest_listed_HK"},
        {"symbol": selected[4].symbol, "reason": "latest_listed_HK"},
    ]
    return selected, reasons


def build_requests(samples: list[Security]) -> list[AuditRequest]:
    requests: list[AuditRequest] = []
    for security in samples:
        plain = security.symbol.replace(".HK", "")
        if security.market == "A":
            em_symbol = f"{security.exchange}{plain}"
            definitions = [
                ("stock_financial_abstract", {"symbol": plain}, "financial_abstract", "history"),
                ("stock_financial_analysis_indicator", {"symbol": plain, "start_year": "1900"}, "financial_indicator", "history"),
                ("stock_balance_sheet_by_report_em", {"symbol": em_symbol}, "balance_sheet", "history"),
                ("stock_profit_sheet_by_report_em", {"symbol": em_symbol}, "income_statement", "history"),
                ("stock_cash_flow_sheet_by_report_em", {"symbol": em_symbol}, "cash_flow_statement", "history"),
                ("stock_zh_a_spot_em", {}, "valuation_snapshot", "snapshot"),
            ]
            for interface, parameters, category, temporality in definitions:
                requests.append(AuditRequest(
                    interface, "A", security.symbol,
                    "Sina" if interface in {
                        "stock_financial_abstract", "stock_financial_analysis_indicator",
                    } else "Eastmoney",
                    parameters, category, temporality,
                    "snapshot" if temporality == "snapshot" else "all_available",
                    "default", filter_symbol=not parameters,
                    valuation_capability_required=temporality == "snapshot",
                ))
        else:
            for period_label, indicator in (("annual", "年度"), ("report_period", "报告期")):
                requests.append(AuditRequest(
                    "stock_financial_hk_analysis_indicator_em", "HK", security.symbol,
                    "Eastmoney", {"symbol": plain, "indicator": indicator},
                    "financial_indicator", "history", period_label, period_label,
                ))
                for statement, category, variant in (
                    ("资产负债表", "balance_sheet", "balance"),
                    ("利润表", "income_statement", "income"),
                    ("现金流量表", "cash_flow_statement", "cashflow"),
                ):
                    requests.append(AuditRequest(
                        "stock_financial_hk_report_em", "HK", security.symbol,
                        "Eastmoney", {"stock": plain, "symbol": statement, "indicator": indicator},
                        category, "history", period_label, f"{variant}_{period_label}",
                    ))
            requests.append(AuditRequest(
                "stock_hk_financial_indicator_em", "HK", security.symbol,
                "Eastmoney", {"symbol": plain}, "valuation_snapshot", "snapshot",
                "snapshot", "latest_indicator", valuation_capability_required=True,
            ))
            requests.append(AuditRequest(
                "stock_hk_spot_em", "HK", security.symbol, "Eastmoney", {},
                "valuation_snapshot", "snapshot", "snapshot", "spot",
                filter_symbol=True, valuation_capability_required=True,
            ))
    return requests


def _sanitize_parameters(parameters: dict[str, Any]) -> str:
    clean = {
        str(key): ("<redacted>" if SENSITIVE_RE.search(str(key)) else value)
        for key, value in parameters.items()
    }
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _filter_spot(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    code_column = next((
        column for column in frame.columns
        if str(column).casefold() in {"代码", "symbol", "security_code", "证券代码"}
    ), None)
    if code_column is None:
        raise ValueError("spot response has no recognizable security-code column")
    expected = symbol.replace(".HK", "").lstrip("0") or "0"
    normalized = frame[code_column].astype(str).str.replace(r"\.0$", "", regex=True)
    match = normalized.str.replace(".HK", "", regex=False).str.lstrip("0").replace("", "0")
    return frame.loc[match.eq(expected)].copy()


def _date_evidence(frame: pd.DataFrame) -> tuple[str, str, bool]:
    dates: list[pd.Timestamp] = []
    announcement = False
    for column in frame.columns:
        name = str(column)
        lowered = name.casefold()
        is_announcement = any(token in lowered for token in ANNOUNCEMENT_TOKENS)
        if is_announcement:
            announcement = True
        is_date_column = (
            not is_announcement
            and any(token in lowered for token in REPORT_DATE_TOKENS)
        )
        if is_date_column:
            parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
            dates.extend(pd.Timestamp(value) for value in parsed.tolist())
        try:
            label_date = pd.to_datetime(name, errors="raise")
        except (ValueError, TypeError, OverflowError):
            continue
        if 1900 <= label_date.year <= 2100:
            dates.append(pd.Timestamp(label_date))
    if not dates:
        return "", "", announcement
    return min(dates).date().isoformat(), max(dates).date().isoformat(), announcement


def _has_valuation_capability(frame: pd.DataFrame) -> bool:
    return any(
        any(token in str(column).casefold() for token in VALUATION_TOKENS)
        for column in frame.columns
    )


def _inventory_outcome(status: str) -> str:
    return {"PASS": "success", "UNAVAILABLE": "unavailable"}.get(status, "failure")


def _audit_one(
    request: AuditRequest, *, adapter: Any, config: Stage18Config,
    store: Stage18RawStore, root: Path, run_id: str,
    clock: Callable[[], datetime], cache: dict[str, tuple[Any, str, str, float]],
) -> dict[str, Any]:
    exists, signature = adapter.inspect_function(request.interface)
    cache_key = request.interface + "|" + _sanitize_parameters(request.parameters)
    request_time = clock().astimezone(timezone.utc).isoformat()
    if not exists:
        call = adapter.call(
            request.interface, request.parameters,
            max_attempts=config.max_attempts,
            retry_delay_seconds=config.retry_delay_seconds,
        )
        duration_ms = 0.0
        finished_at = request_time
    elif cache_key in cache:
        call, request_time, finished_at, duration_ms = cache[cache_key]
    else:
        started = perf_counter()
        call = adapter.call(
            request.interface, request.parameters,
            max_attempts=config.max_attempts,
            retry_delay_seconds=config.retry_delay_seconds,
        )
        duration_ms = round((perf_counter() - started) * 1000, 3)
        finished_at = clock().astimezone(timezone.utc).isoformat()
        cache[cache_key] = (call, request_time, finished_at, duration_ms)

    frame = call.dataframe
    error_type = call.error_type
    error_message = call.error_message
    if frame is not None and request.filter_symbol:
        try:
            frame = _filter_spot(frame, request.symbol)
        except ValueError as exc:
            frame = None
            error_type = "schema_mismatch"
            error_message = str(exc)
            call.status = "failed"

    if call.status == "unavailable" or error_type == "function_missing":
        status = "UNAVAILABLE"
    elif call.status != "success" or frame is None or frame.empty:
        status = "FAIL"
        error_type = error_type or "empty_result"
        error_message = error_message or "Returned empty DataFrame"
    elif request.valuation_capability_required and not _has_valuation_capability(frame):
        status = "UNAVAILABLE"
        error_type = "capability_not_exposed"
        error_message = "Interface response exposes no PE/PB/market-cap field"
    else:
        status = "PASS"

    earliest, latest, announcement = ("", "", False)
    if frame is not None and not frame.empty:
        earliest, latest, announcement = _date_evidence(frame)
        if request.temporality == "history" and not earliest and status == "PASS":
            status = "FAIL"
            error_type = "schema_mismatch"
            error_message = "Historical response has no recognizable report date"
    error_message = _sanitize_error_message(error_message)

    snapshot_time = finished_at if request.temporality == "snapshot" else ""
    metadata = {
        "stage": 18, "substage": "18.1", "run_id": run_id,
        "interface": request.interface, "market": request.market,
        "symbol": request.symbol, "provider": request.provider,
        "request_parameters": json.loads(_sanitize_parameters(request.parameters)),
        "request_time": request_time, "finished_at": finished_at,
        "attempt_count": call.attempt_count, "duration_ms": duration_ms,
        "status": status, "error_type": error_type, "error_message": error_message[:500],
        "data_category": request.category, "data_temporality": request.temporality,
        "report_period_type": request.report_period_type,
        "announcement_date_available": announcement,
        "earliest_date": earliest, "latest_date": latest,
        "snapshot_time": snapshot_time,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "asset_role": "interface_audit",
        "audit_only": True,
        "eligible_for_stage18_2_ingestion": False,
        "eligible_for_capability_assessment": status == "PASS",
        "akshare_version": adapter.akshare_version,
        "function_signature": signature,
    }
    directory = store.dataset_dir(
        run_id=run_id, category=request.category, market=request.market,
        symbol=request.symbol, interface=request.interface, variant=request.variant,
    )
    try:
        stored = store.write(frame if frame is not None and not frame.empty else None, directory, metadata)
    except Exception as exc:
        status = "BLOCKED"
        error_type = "raw_write_error"
        error_message = str(exc)[:500]
        stored = {"data_sha256": "", "data_path": None, "metadata_path": directory / "metadata.json"}

    columns = [] if frame is None else [str(item) for item in frame.columns]
    return {
        "run_id": run_id, "interface": request.interface,
        "function_signature": signature, "market": request.market,
        "symbol": request.symbol, "provider": request.provider,
        "request_parameters": _sanitize_parameters(request.parameters),
        "request_time": request_time, "outcome": _inventory_outcome(status),
        "status": status, "row_count": 0 if frame is None else int(len(frame)),
        "columns": json.dumps(columns, ensure_ascii=False),
        "earliest_date": earliest, "latest_date": latest,
        "report_period_type": request.report_period_type,
        "announcement_date_available": announcement,
        "error_type": error_type, "error_message": error_message[:500],
        "attempt_count": int(call.attempt_count), "duration_ms": duration_ms,
        "data_category": request.category, "data_temporality": request.temporality,
        "akshare_version": adapter.akshare_version,
        "snapshot_time": snapshot_time,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "asset_role": "interface_audit",
        "audit_only": True,
        "eligible_for_stage18_2_ingestion": False,
        "eligible_for_capability_assessment": status == "PASS",
        "schema_hash": "" if frame is None else schema_hash(frame),
        "sha256": stored.get("data_sha256", ""),
        "raw_data_path": "" if stored.get("data_path") is None else _relative(stored["data_path"], root),
        "metadata_path": _relative(stored["metadata_path"], root),
    }


def _atomic_text(path: Path, text: str, *, must_not_exist: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if must_not_exist and path.exists():
        raise FileExistsError(f"Report already exists: {path}")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary report exists: {temporary}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_csv(path: Path, frame: pd.DataFrame, *, must_not_exist: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if must_not_exist and path.exists():
        raise FileExistsError(f"Report already exists: {path}")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary report exists: {temporary}")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def render_inventory_markdown(
    frame: pd.DataFrame, *, run_payload: dict[str, Any], samples: list[Security],
    reasons: list[dict[str, str]], candidates: list[Security],
) -> str:
    counts = frame["status"].value_counts().to_dict()
    lines = [
        "# Stage 18.1 基本面接口能力审计", "",
        f"- Run ID: `{run_payload['run_id']}`",
        f"- 上游 Stage 17: `{run_payload['upstream_stage17_run_id']}` (`PASS`)",
        f"- AKShare: `{run_payload['akshare_version']}`",
        f"- Python: `{run_payload['python_version']}`",
        f"- 分析基准日: `{run_payload['analysis_as_of_date']}`",
        f"- 审计状态: `{run_payload['status']}`",
        f"- 结果计数: `{json.dumps(counts, ensure_ascii=False, sort_keys=True)}`", "",
        "## 样本选择", "",
        "|市场|代码|上市日期|选择理由|", "|---|---|---|---|",
    ]
    reason_map = {item["symbol"]: item["reason"] for item in reasons}
    for item in samples:
        lines.append(
            f"|{item.market}|{item.symbol}|{item.listing_date.isoformat()}|"
            f"{reason_map[item.symbol]}|"
        )
    lines.extend(["", "候选证券均来自指定 Stage 17 批次，共 " + str(len(candidates)) + " 只。", ""])
    lines.extend([
        "## 能力矩阵", "",
        "|市场|接口|类别|时态|PASS|UNAVAILABLE|FAIL|BLOCKED|", "|---|---|---|---|---:|---:|---:|---:|",
    ])
    grouped = frame.groupby(["market", "interface", "data_category", "data_temporality"], dropna=False)
    for key, group in grouped:
        status_counts = group["status"].value_counts()
        lines.append(
            f"|{key[0]}|`{key[1]}`|{key[2]}|{key[3]}|"
            f"{status_counts.get('PASS', 0)}|{status_counts.get('UNAVAILABLE', 0)}|"
            f"{status_counts.get('FAIL', 0)}|{status_counts.get('BLOCKED', 0)}|"
        )
    issues = frame.loc[frame["status"].ne("PASS")]
    lines.extend(["", "## 非 PASS 明细", ""])
    if issues.empty:
        lines.append("无。")
    else:
        lines.extend(["|状态|市场|代码|接口|错误类型|说明|", "|---|---|---|---|---|---|"])
        for row in issues.itertuples(index=False):
            message = str(row.error_message).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"|{row.status}|{row.market}|{row.symbol}|`{row.interface}`|"
                f"{row.error_type}|{message}|"
            )
    lines.extend([
        "", "## 时间治理", "",
        "本目录中的历史财务与实时估值均仅用于接口能力审计，统一标记 "
        "`asset_role=interface_audit`、`audit_only=true`、"
        "`eligible_for_stage18_2_ingestion=false`。只有状态为 `PASS` 的样本可标记 "
        "`eligible_for_capability_assessment=true`；任何审计样本都不得直接进入正式采集、"
        "基准日分析或事实表。",
        "", "## 已知测试债务", "",
        "Stage 8 既有失败属于人工规则数据与旧测试前置假设冲突；本审计不修改 Stage 8，"
        "完整测试结果必须单独核对，任何新增失败均阻止 Stage 18.1 通过。",
        "", "## Stage 18.2 建议", "",
        "仅可对本清单中状态为 `PASS` 的类别规划全量 Raw 采集。`UNAVAILABLE` 保持显式缺口；"
        "存在 `FAIL` 或 `BLOCKED` 时不得授权 Stage 18.2。", "",
        "本报告仅用于数据能力研究与测试，不构成投资建议。", "",
    ])
    return "\n".join(lines)


def run_stage18_interface_audit(
    *, root: str | Path = ".", config_path: str | Path = "config/stage18.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    adapter: Any | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, Any], int]:
    repo = Path(root).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = repo / config_file
    config = load_stage18_config(config_file)
    if as_of_date != config.as_of_date:
        raise ValueError(
            f"Stage 18.1 as_of_date {as_of_date} must equal configured {config.as_of_date}"
        )
    if upstream_run_id is not None and upstream_run_id != config.upstream_run_id:
        raise ValueError("Stage 18.1 upstream run_id differs from frozen configuration")
    stage0_before = frozen_hashes(repo)
    securities = validate_upstream(repo, config)
    samples, reasons = select_samples(securities)
    requests = build_requests(samples)
    preview = {
        "stage": 18, "substage": "18.1", "status": "READY",
        "upstream_stage17_run_id": config.upstream_run_id,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "sample_symbols": [item.symbol for item in samples],
        "sample_reasons": reasons, "inventory_row_count": len(requests),
        "network_calls": len({
            item.interface + "|" + _sanitize_parameters(item.parameters)
            for item in requests
        }),
    }
    if validate_only or dry_run:
        return preview, 0

    actual_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(actual_run_id)
    except ValueError as exc:
        raise ValueError("Stage 18.1 run_id must be a UUID") from exc
    reports_root = repo / config.reports_root
    report_dir = reports_root / actual_run_id
    if report_dir.exists():
        raise FileExistsError(f"Stage 18.1 report run already exists: {report_dir}")
    store = Stage18RawStore(repo / config.raw_root)
    actual_adapter = adapter or Stage18FundamentalAdapter()
    started_at = clock().astimezone(timezone.utc).isoformat()
    cache: dict[str, tuple[Any, str, str, float]] = {}
    rows = [
        _audit_one(
            item, adapter=actual_adapter, config=config, store=store, root=repo,
            run_id=actual_run_id, clock=clock, cache=cache,
        )
        for item in requests
    ]
    inventory = pd.DataFrame(rows, columns=INVENTORY_COLUMNS)
    failed = inventory["status"].isin(["FAIL", "BLOCKED"])
    status = "BLOCKED" if bool(failed.any()) else "PASS"
    finished_at = clock().astimezone(timezone.utc).isoformat()
    stage0_after = frozen_hashes(repo)
    if stage0_after != stage0_before:
        status = "BLOCKED"
    run_payload = {
        "stage": 18, "substage": "18.1", "run_id": actual_run_id,
        "status": status, "started_at": started_at, "finished_at": finished_at,
        "upstream_stage17_run_id": config.upstream_run_id,
        "upstream_status": "PASS", "analysis_as_of_date": config.as_of_date.isoformat(),
        "snapshot_policy": config.snapshot_policy,
        "sample_symbols": [item.symbol for item in samples], "sample_reasons": reasons,
        "candidate_security_count": len(securities), "inventory_row_count": len(inventory),
        "network_call_count": len(cache),
        "status_counts": {key: int(value) for key, value in inventory["status"].value_counts().items()},
        "akshare_version": actual_adapter.akshare_version,
        "python_version": platform.python_version(),
        "stage0_hashes_before": stage0_before, "stage0_hashes_after": stage0_after,
        "stage0_hashes_unchanged": stage0_before == stage0_after,
        "stage18_2_planning_authorized": status == "PASS",
        "known_test_debt": ["Stage 8 manual-rule fixture precondition conflict"],
    }
    markdown = render_inventory_markdown(
        inventory, run_payload=run_payload, samples=samples,
        reasons=reasons, candidates=securities,
    )
    run_csv = report_dir / "interface_inventory.csv"
    run_md = report_dir / "interface_inventory.md"
    _atomic_csv(run_csv, inventory, must_not_exist=True)
    _atomic_text(run_md, markdown, must_not_exist=True)
    _atomic_csv(reports_root / "interface_inventory.csv", inventory)
    _atomic_text(reports_root / "interface_inventory.md", markdown)

    raw_files = []
    raw_run_root = repo / config.raw_root / f"run_id={actual_run_id}"
    for path in sorted(raw_run_root.rglob("*")):
        if path.is_file():
            raw_files.append(file_record(path, repo))
    manifest = {
        "stage": 18, "substage": "18.1", "run_id": actual_run_id,
        "status": status, "upstream_stage17_run_id": config.upstream_run_id,
        "inventory_columns": INVENTORY_COLUMNS, "inventory_rows": rows,
        "files": raw_files + [file_record(run_csv, repo), file_record(run_md, repo)],
        "raw_manifest_closed_world": True,
    }
    _atomic_text(
        report_dir / "stage18_1_run.json",
        json.dumps(run_payload, ensure_ascii=False, indent=2) + "\n",
        must_not_exist=True,
    )
    _atomic_text(
        report_dir / "stage18_1_manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        must_not_exist=True,
    )
    return run_payload, 0 if status == "PASS" else 2
