"""Stage 18.1.3 full capability-oriented interface re-audit."""
from __future__ import annotations

import hashlib
import json
import platform
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .adapters.stage18_fundamentals import Stage18FundamentalAdapter
from .adapters.stage18_valuation import Stage18ValuationAdapter
from .stage18_audit import (
    INVENTORY_COLUMNS as BASE_COLUMNS,
    Stage18Blocked,
    _atomic_csv,
    _atomic_text,
    _audit_one,
    _relative,
    build_requests,
    frozen_hashes,
    select_samples,
    validate_upstream,
)
from .stage18_config import load_stage18_config
from .stage18_reaudit_config import Stage18ReauditConfig, load_stage18_reaudit_config
from .stage18_valuation_audit import _column_for, _direct_parameters
from .stage18_valuation_config import ProviderSpec
from .storage.raw_store import file_record, file_sha256, schema_hash
from .storage.stage18_raw_store import Stage18RawStore


EXTRA_COLUMNS = [
    "capability", "provider_role", "selected_provider", "affects_capability",
    "evidence_run_id", "fields_present", "required_fields", "missing_fields",
    "attempts",
]
INVENTORY_COLUMNS = BASE_COLUMNS + EXTRA_COLUMNS
HISTORICAL_CAPABILITIES = {
    "A": (
        "financial_abstract", "financial_indicator", "balance_sheet",
        "income_statement", "cash_flow_statement",
    ),
    "HK": (
        "financial_indicator", "balance_sheet", "income_statement",
        "cash_flow_statement",
    ),
}
COMPONENT_FIELDS = {
    "stock_zh_valuation_comparison_em": {"symbol", "pe", "pb", "snapshot_time"},
    "stock_zh_scale_comparison_em": {
        "symbol", "total_market_cap", "floating_market_cap", "snapshot_time",
    },
    "stock_hk_financial_indicator_em": {
        "symbol", "pe", "pb", "total_market_cap", "snapshot_time",
    },
}
FORMAL_STAGE_ASSET_ROOTS = (
    "data/raw/stage18/financial_abstract",
    "data/raw/stage18/financial_indicator",
    "data/raw/stage18/balance_sheet",
    "data/raw/stage18/income_statement",
    "data/raw/stage18/cash_flow_statement",
    "data/raw/stage18/valuation_snapshot",
    "data/clean/stage18",
    "data/features/stage18",
    "data/raw/stage19",
    "reports/stage19",
)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Stage18Blocked(f"Missing or invalid governance evidence: {path}") from exc
    if not isinstance(value, dict):
        raise Stage18Blocked(f"Governance evidence is not an object: {path}")
    return value


def _verify_records(root: Path, records: list[dict[str, Any]], *, size_key: str) -> str:
    canonical = []
    for record in records:
        path = root / str(record["path"])
        expected_size = int(record[size_key])
        expected_hash = str(record["sha256"])
        if (
            not path.is_file() or path.stat().st_size != expected_size
            or file_sha256(path) != expected_hash
        ):
            raise Stage18Blocked(f"Evidence file differs from manifest: {record['path']}")
        canonical.append((str(record["path"]), expected_size, expected_hash))
    payload = json.dumps(sorted(canonical), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stage17_fingerprint(root: Path, base_config: Any) -> dict[str, Any]:
    manifest_path = (
        root / base_config.stage17_reports_root / base_config.upstream_run_id
        / "stage17_manifest.json"
    )
    manifest = _json_object(manifest_path)
    if manifest.get("run_id") != base_config.upstream_run_id or manifest.get("status") != "PASS":
        raise Stage18Blocked("Stage 17 formal manifest identity/status differs")
    records = manifest.get("raw_files")
    if not isinstance(records, list) or len(records) != 196:
        raise Stage18Blocked("Stage 17 formal Raw manifest must contain exactly 196 files")
    return {
        "manifest_path": _relative(manifest_path, root),
        "manifest_sha256": file_sha256(manifest_path),
        "raw_file_count": len(records),
        "raw_tree_sha256": _verify_records(root, records, size_key="size_bytes"),
    }


def _validate_valuation_evidence(root: Path, config: Stage18ReauditConfig) -> dict[str, Any]:
    run_path = root / config.valuation_run_path
    manifest_path = root / config.valuation_manifest_path
    run = _json_object(run_path)
    manifest = _json_object(manifest_path)
    if (
        run.get("run_id") != config.valuation_run_id
        or run.get("status") != config.valuation_status
        or run.get("stage18_2_authorized") is not False
        or manifest.get("run_id") != config.valuation_run_id
        or manifest.get("status") != config.valuation_status
    ):
        raise Stage18Blocked("Stage 18.1.2 PASS evidence differs from frozen configuration")
    selected = {
        item.get("market"): item.get("selected_provider")
        for item in run.get("valuation_capabilities", [])
    }
    if selected != {
        "A": "EastmoneyDataCenter[valuation_comparison+scale_comparison]",
        "HK": "stock_hk_financial_indicator_em",
    }:
        raise Stage18Blocked("Stage 18.1.2 selected providers differ")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise Stage18Blocked("Stage 18.1.2 manifest file list is missing")
    digest = _verify_records(root, files, size_key="size")
    return {
        "run_id": config.valuation_run_id,
        "run_sha256": file_sha256(run_path),
        "manifest_sha256": file_sha256(manifest_path),
        "evidence_file_count": len(files),
        "evidence_tree_sha256": digest,
        "selected_providers": selected,
    }


def _validate_frozen_failures(root: Path, config: Stage18ReauditConfig) -> dict[str, Any]:
    path = root / config.frozen_evidence_path
    evidence = _json_object(path)
    if evidence.get("run_id") != config.frozen_run_id:
        raise Stage18Blocked("Stage 18.1.1 frozen evidence run differs")
    results = {item.get("interface"): item for item in evidence.get("results", [])}
    for interface in config.frozen_interfaces:
        item = results.get(interface)
        if (
            item is None or item.get("terminal_status") != "FAIL"
            or item.get("error_type") != "connection_error"
            or len(item.get("attempts", [])) != 3
        ):
            raise Stage18Blocked(f"Frozen Push2 failure differs for {interface}")
    return evidence


def _formal_asset_counts(root: Path) -> dict[str, int]:
    return {
        relative: sum(1 for item in (root / relative).rglob("*") if item.is_file())
        if (root / relative).exists() else 0
        for relative in FORMAL_STAGE_ASSET_ROOTS
    }


def _base_inventory_row() -> dict[str, Any]:
    return {column: "" for column in INVENTORY_COLUMNS}


def _history_row(row: dict[str, Any]) -> dict[str, Any]:
    result = _base_inventory_row()
    result.update(row)
    result.update({
        "capability": row["data_category"], "provider_role": "selected_historical",
        "selected_provider": True, "affects_capability": True,
        "evidence_run_id": "", "fields_present": row["columns"],
        "required_fields": "[]", "missing_fields": "[]", "attempts": "[]",
    })
    return result


def _valuation_fields(frame: pd.DataFrame | None, interface: str, snapshot_time: str) -> set[str]:
    fields = {"symbol", "snapshot_time"} if snapshot_time else {"symbol"}
    if frame is None or frame.empty:
        return fields
    for semantic in ("pe", "pb", "total_market_cap", "floating_market_cap"):
        column = _column_for(frame, semantic)
        if column is not None and pd.to_numeric(frame[column], errors="coerce").notna().any():
            fields.add(semantic)
    return fields


def _valuation_row(
    *, root: Path, store: Stage18RawStore, run_id: str, market: str,
    symbol: str, interface: str, provider: str, config: Stage18ReauditConfig,
    adapter: Any, clock: Callable[[], datetime],
) -> dict[str, Any]:
    spec = ProviderSpec(interface, provider, "symbol_snapshot")
    exists, signature, _module, _source = adapter.inspect_function(interface)
    parameters = _direct_parameters(spec, symbol)
    request_time = clock().astimezone(timezone.utc).isoformat()
    call = adapter.call(
        interface, parameters, max_attempts=config.max_attempts,
        retry_delay_seconds=config.retry_delay_seconds,
        timeout_seconds=config.request_timeout_seconds,
    )
    snapshot_time = clock().astimezone(timezone.utc).isoformat()
    frame = call.dataframe
    fields = _valuation_fields(frame, interface, snapshot_time)
    required = COMPONENT_FIELDS[interface]
    missing = required - fields
    if not exists or call.status == "unavailable":
        status, error_type = "FAIL", "selected_provider_unavailable"
    elif call.status != "success" or frame is None or frame.empty:
        status, error_type = "FAIL", call.error_type or "empty_result"
    elif missing:
        status, error_type = "FAIL", "selected_provider_semantic_gap"
    else:
        status, error_type = "PASS", ""
    error_message = call.error_message or (
        "Missing selected component fields: " + ",".join(sorted(missing)) if missing else ""
    )
    metadata = {
        "stage": 18, "substage": "18.1.3", "run_id": run_id,
        "market": market, "symbol": symbol, "interface": interface,
        "provider": provider, "request_parameters": parameters,
        "request_time": request_time, "snapshot_time": snapshot_time,
        "analysis_as_of_date": config.as_of_date.isoformat(), "status": status,
        "error_type": error_type, "error_message": error_message[:500],
        "attempt_count": call.attempt_count,
        "attempts": [item.__dict__ for item in call.attempts],
        "data_category": "valuation_snapshot", "data_temporality": "snapshot",
        "asset_role": "interface_audit", "audit_only": True,
        "eligible_for_stage18_2_ingestion": False,
        "eligible_for_capability_assessment": status == "PASS",
        "akshare_version": adapter.akshare_version, "function_signature": signature,
        "fields_present": sorted(fields), "required_component_fields": sorted(required),
    }
    directory = store.dataset_dir(
        run_id=run_id, category="valuation_snapshot", market=market, symbol=symbol,
        interface=interface, variant="selected",
    )
    try:
        stored = store.write(frame if frame is not None and not frame.empty else None, directory, metadata)
    except Exception as exc:
        status, error_type, error_message = "BLOCKED", "raw_write_error", str(exc)[:500]
        stored = {"data_path": None, "metadata_path": directory / "metadata.json", "data_sha256": ""}
    result = _base_inventory_row()
    result.update({
        "run_id": run_id, "interface": interface, "function_signature": signature,
        "market": market, "symbol": symbol, "provider": provider,
        "request_parameters": json.dumps(parameters, ensure_ascii=False, sort_keys=True),
        "request_time": request_time, "outcome": "success" if status == "PASS" else "failure",
        "status": status, "row_count": 0 if frame is None else len(frame),
        "columns": json.dumps([] if frame is None else [str(x) for x in frame.columns], ensure_ascii=False),
        "report_period_type": "snapshot", "announcement_date_available": False,
        "error_type": error_type, "error_message": error_message[:500],
        "attempt_count": call.attempt_count,
        "duration_ms": round(sum(item.duration_ms for item in call.attempts), 3),
        "data_category": "valuation_snapshot", "data_temporality": "snapshot",
        "akshare_version": adapter.akshare_version, "snapshot_time": snapshot_time,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "asset_role": "interface_audit", "audit_only": True,
        "eligible_for_stage18_2_ingestion": False,
        "eligible_for_capability_assessment": status == "PASS",
        "schema_hash": "" if frame is None else schema_hash(frame),
        "sha256": stored.get("data_sha256", ""),
        "raw_data_path": "" if stored.get("data_path") is None else _relative(stored["data_path"], root),
        "metadata_path": _relative(stored["metadata_path"], root),
        "capability": "valuation", "provider_role": "selected_valuation_component",
        "selected_provider": True, "affects_capability": True,
        "evidence_run_id": "", "fields_present": json.dumps(sorted(fields)),
        "required_fields": json.dumps(sorted(required)),
        "missing_fields": json.dumps(sorted(missing)),
        "attempts": json.dumps([item.__dict__ for item in call.attempts], ensure_ascii=False),
    })
    return result


def _frozen_rows(run_id: str, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in evidence["results"]:
        result = _base_inventory_row()
        result.update({
            "run_id": run_id, "interface": item["interface"], "function_signature": "()",
            "market": item["market"], "symbol": "*", "provider": "EastmoneyPush2",
            "request_parameters": "{}", "request_time": evidence["started_at"],
            "outcome": "failure", "status": "FAIL", "row_count": 0, "columns": "[]",
            "error_type": "frozen_connection_error",
            "error_message": "not_retried: previously reproduced connection_error",
            "attempt_count": len(item["attempts"]), "duration_ms": round(sum(x["duration_ms"] for x in item["attempts"]), 3),
            "data_category": "valuation_snapshot", "data_temporality": "snapshot",
            "snapshot_time": evidence["finished_at"],
            "analysis_as_of_date": evidence["analysis_as_of_date"],
            "asset_role": "interface_audit", "audit_only": True,
            "eligible_for_stage18_2_ingestion": False,
            "eligible_for_capability_assessment": False,
            "capability": "valuation", "provider_role": "frozen_rejected_provider",
            "selected_provider": False, "affects_capability": False,
            "evidence_run_id": evidence["run_id"], "fields_present": "[]",
            "required_fields": "[]", "missing_fields": "[]",
            "attempts": json.dumps(item["attempts"], ensure_ascii=False),
        })
        rows.append(result)
    return rows


def _capability_matrix(
    inventory: pd.DataFrame, samples: list[Any], run_id: str,
    config: Stage18ReauditConfig,
) -> pd.DataFrame:
    rows = []
    for market, capabilities in HISTORICAL_CAPABILITIES.items():
        symbols = {item.symbol for item in samples if item.market == market}
        for capability in capabilities:
            subset = inventory[
                inventory["market"].eq(market)
                & inventory["capability"].eq(capability)
                & inventory["affects_capability"].eq(True)
            ]
            expected = len(symbols) * (2 if market == "HK" else 1)
            passed = int(subset["status"].eq("PASS").sum())
            status = "PASS" if len(subset) == expected and passed == expected else "BLOCKED"
            interfaces = sorted(set(subset["interface"].astype(str)))
            rows.append({
                "run_id": run_id, "market": market, "capability": capability,
                "status": status, "selected_provider": "+".join(interfaces),
                "planned_unit_count": expected, "observed_unit_count": len(subset),
                "pass_count": passed,
                "reason": "" if status == "PASS" else "historical_capability_unit_not_pass",
            })
    for market in ("A", "HK"):
        symbols = {item.symbol for item in samples if item.market == market}
        selection = config.valuation[market]
        subset = inventory[
            inventory["market"].eq(market)
            & inventory["capability"].eq("valuation")
            & inventory["provider_role"].eq("selected_valuation_component")
        ]
        complete = len(subset) == len(symbols) * len(selection.interfaces)
        complete = complete and subset["status"].eq("PASS").all()
        for symbol in symbols:
            union: set[str] = set()
            for value in subset.loc[subset["symbol"].eq(symbol), "fields_present"]:
                union.update(json.loads(value))
            complete = complete and set(selection.required_fields).issubset(union)
        provider = (
            "EastmoneyDataCenter[valuation_comparison+scale_comparison]"
            if market == "A" else selection.interfaces[0]
        )
        rows.append({
            "run_id": run_id, "market": market, "capability": "valuation",
            "status": "PASS" if complete else "BLOCKED", "selected_provider": provider,
            "planned_unit_count": len(symbols) * len(selection.interfaces),
            "observed_unit_count": len(subset),
            "pass_count": int(subset["status"].eq("PASS").sum()),
            "reason": "" if complete else "selected_valuation_provider_incomplete",
        })
    return pd.DataFrame(rows)


def _render_markdown(run: dict[str, Any], capability: pd.DataFrame, inventory: pd.DataFrame) -> str:
    lines = [
        "# Stage 18.1 完整能力重新验收（18.1.3）", "",
        f"- Run ID: `{run['run_id']}`", f"- 状态: `{run['status']}`",
        f"- Stage 18.2 授权: `{str(run['stage18_2_authorized']).lower()}`",
        f"- 上游 Stage 17: `{run['upstream_stage17_run_id']}`",
        f"- 基准日: `{run['analysis_as_of_date']}`", "",
        "## 正式能力矩阵", "",
        "|市场|能力|状态|选定Provider|通过/计划|", "|---|---|---|---|---:|",
    ]
    for row in capability.itertuples(index=False):
        lines.append(
            f"|{row.market}|{row.capability}|{row.status}|{row.selected_provider}|"
            f"{row.pass_count}/{row.planned_unit_count}|"
        )
    rejected = inventory[inventory["provider_role"].eq("frozen_rejected_provider")]
    lines.extend(["", "## 冻结拒绝 Provider", ""])
    for row in rejected.itertuples(index=False):
        lines.append(
            f"- `{row.interface}`：`FAIL / frozen_connection_error`，未重试、未选用；"
            f"证据 run `{row.evidence_run_id}`。"
        )
    lines.extend([
        "", "## 治理结论", "",
        "历史财务和估值样本全部位于同一个新 run；没有复用或拼接旧 Stage 18 Raw。",
        "全部新资产均为 `asset_role=interface_audit`、`audit_only=true`、"
        "`eligible_for_stage18_2_ingestion=false`。",
        "A 股估值由同一 Eastmoney Data Center Provider 的两个组件共同满足；"
        "组件单独不要求覆盖完整市场级语义。",
        "本 run 只给出 Stage 18.2 入口授权，没有启动 Stage 18.2，也没有创建正式财务 Raw、"
        "Fact、Feature 或 Stage 19 资产。", "",
        "本项目仅用于数据能力研究与测试，不构成投资建议。", "",
    ])
    return "\n".join(lines)


def run_stage18_full_reaudit(
    *, root: str | Path = ".", config_path: str | Path = "config/stage18_reaudit.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    fundamental_adapter: Any | None = None, valuation_adapter: Any | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, Any], int]:
    repo = Path(root).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = repo / config_file
    config = load_stage18_reaudit_config(config_file)
    base_path = config.stage18_config_path
    if not base_path.is_absolute():
        base_path = repo / base_path
    base_config = load_stage18_config(base_path)
    if as_of_date != config.as_of_date or base_config.as_of_date != config.as_of_date:
        raise ValueError("Stage 18.1.3 as_of_date differs from frozen configuration")
    if upstream_run_id is not None and upstream_run_id != base_config.upstream_run_id:
        raise ValueError("Stage 18.1.3 upstream Stage 17 run_id differs")
    stage0_before = frozen_hashes(repo)
    securities = validate_upstream(repo, base_config)
    samples, reasons = select_samples(securities)
    expected_samples = ["600763", "000100", "603259", "08365.HK", "09669.HK"]
    if [item.symbol for item in samples] != expected_samples:
        raise Stage18Blocked("Stage 18.1.3 deterministic samples differ")
    valuation_evidence = _validate_valuation_evidence(repo, config)
    frozen_evidence = _validate_frozen_failures(repo, config)
    stage17_before = _stage17_fingerprint(repo, base_config)
    formal_before = _formal_asset_counts(repo)
    history_requests = [item for item in build_requests(samples) if item.temporality == "history"]
    preview = {
        "stage": 18, "substage": "18.1.3", "status": "READY",
        "upstream_stage17_run_id": base_config.upstream_run_id,
        "upstream_valuation_audit_run_id": config.valuation_run_id,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "sample_symbols": expected_samples, "sample_reasons": reasons,
        "historical_unit_count": len(history_requests), "valuation_unit_count": 8,
        "planned_capability_count": 11, "network_call_count": 39,
        "frozen_interfaces_not_retried": list(config.frozen_interfaces),
    }
    if validate_only or dry_run:
        return preview, 0
    actual_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(actual_run_id)
    except ValueError as exc:
        raise ValueError("Stage 18.1.3 run_id must be a UUID") from exc
    report_dir = repo / config.reports_root / actual_run_id
    raw_run_root = repo / config.raw_root / f"run_id={actual_run_id}"
    if report_dir.exists() or raw_run_root.exists():
        raise FileExistsError(f"Stage 18.1.3 run already exists: {actual_run_id}")
    store = Stage18RawStore(repo / config.raw_root)
    fundamental = fundamental_adapter or Stage18FundamentalAdapter()
    valuation = valuation_adapter or Stage18ValuationAdapter()
    started_at = clock().astimezone(timezone.utc).isoformat()
    cache: dict[str, tuple[Any, str, str, float]] = {}
    rows = [
        _history_row(_audit_one(
            request, adapter=fundamental, config=base_config, store=store, root=repo,
            run_id=actual_run_id, clock=clock, cache=cache,
        ))
        for request in history_requests
    ]
    for market in ("A", "HK"):
        for security in (item for item in samples if item.market == market):
            for interface in config.valuation[market].interfaces:
                rows.append(_valuation_row(
                    root=repo, store=store, run_id=actual_run_id, market=market,
                    symbol=security.symbol, interface=interface,
                    provider=config.valuation[market].provider, config=config,
                    adapter=valuation, clock=clock,
                ))
    rows.extend(_frozen_rows(actual_run_id, frozen_evidence))
    inventory = pd.DataFrame(rows, columns=INVENTORY_COLUMNS)
    capability = _capability_matrix(inventory, samples, actual_run_id, config)
    stage0_after = frozen_hashes(repo)
    stage17_after = _stage17_fingerprint(repo, base_config)
    formal_after = _formal_asset_counts(repo)
    raw_files = [item for item in raw_run_root.rglob("*") if item.is_file()]
    metadata = [
        _json_object(item) for item in raw_files if item.name == "metadata.json"
    ]
    raw_governance_ok = all(
        item.get("asset_role") == "interface_audit"
        and item.get("audit_only") is True
        and item.get("eligible_for_stage18_2_ingestion") is False
        for item in metadata
    )
    no_tmp = not any(item.suffix == ".tmp" for item in raw_files)
    capability_pass = len(capability) == 11 and capability["status"].eq("PASS").all()
    boundary_ok = formal_before == formal_after and all(value == 0 for value in formal_after.values())
    status = "PASS" if all((
        capability_pass, stage0_before == stage0_after,
        stage17_before == stage17_after, raw_governance_ok, no_tmp, boundary_ok,
    )) else "BLOCKED"
    finished_at = clock().astimezone(timezone.utc).isoformat()
    run_payload = {
        "stage": 18, "substage": "18.1", "closure_substage": "18.1.3",
        "run_id": actual_run_id, "status": status,
        "stage18_1_status": status, "stage18_2_authorized": status == "PASS",
        "stage18_2_started": False, "started_at": started_at, "finished_at": finished_at,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "upstream_stage17_run_id": base_config.upstream_run_id,
        "upstream_valuation_audit_run_id": config.valuation_run_id,
        "sample_symbols": expected_samples, "sample_reasons": reasons,
        "planned_capability_count": 11,
        "capability_status_counts": {k: int(v) for k, v in capability["status"].value_counts().items()},
        "provider_status_counts": {k: int(v) for k, v in inventory["status"].value_counts().items()},
        "selected_valuation_providers": valuation_evidence["selected_providers"],
        "frozen_rejected_interfaces": list(config.frozen_interfaces),
        "frozen_failure_evidence_run_id": config.frozen_run_id,
        "historical_network_call_count": len(cache), "valuation_network_call_count": 8,
        "akshare_version": valuation.akshare_version,
        "python_version": platform.python_version(),
        "stage0_hashes_before": stage0_before, "stage0_hashes_after": stage0_after,
        "stage0_hashes_unchanged": stage0_before == stage0_after,
        "stage17_evidence_before": stage17_before, "stage17_evidence_after": stage17_after,
        "stage17_raw_unchanged": stage17_before == stage17_after,
        "valuation_audit_evidence": valuation_evidence,
        "audit_raw_file_count": len(raw_files), "audit_metadata_count": len(metadata),
        "audit_raw_closed_world": True, "audit_raw_governance_pass": raw_governance_ok,
        "tmp_file_count": sum(item.suffix == ".tmp" for item in raw_files),
        "formal_asset_counts_before": formal_before, "formal_asset_counts_after": formal_after,
        "stage18_formal_raw_count": 0, "formal_fact_table_count": 0,
        "fundamental_feature_count": 0, "stage19_asset_count": 0,
        "known_test_debt": {
            "node_id": "tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset",
            "signature": "expected returncode 1, observed returncode 0",
        },
    }
    inventory_path = report_dir / "interface_inventory.csv"
    capability_path = report_dir / "capability_matrix.csv"
    report_path = report_dir / "interface_inventory.md"
    _atomic_csv(inventory_path, inventory, must_not_exist=True)
    _atomic_csv(capability_path, capability, must_not_exist=True)
    _atomic_text(report_path, _render_markdown(run_payload, capability, inventory), must_not_exist=True)
    report_files = [inventory_path, capability_path, report_path]
    records = [file_record(path, repo) for path in sorted(raw_files)]
    records.extend(file_record(path, repo) for path in report_files)
    manifest = {
        "stage": 18, "substage": "18.1", "closure_substage": "18.1.3",
        "run_id": actual_run_id, "status": status,
        "upstream_stage17_run_id": base_config.upstream_run_id,
        "inventory_columns": INVENTORY_COLUMNS,
        "inventory_rows": inventory.to_dict("records"),
        "capability_rows": capability.to_dict("records"),
        "files": records, "raw_manifest_closed_world": True,
    }
    _atomic_text(report_dir / "stage18_1_run.json", json.dumps(run_payload, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    _atomic_text(report_dir / "stage18_1_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    _atomic_csv(repo / config.reports_root / "interface_inventory.csv", inventory)
    _atomic_csv(repo / config.reports_root / "capability_matrix.csv", capability)
    _atomic_text(repo / config.reports_root / "interface_inventory.md", _render_markdown(run_payload, capability, inventory))
    return run_payload, 0 if status == "PASS" else 2
