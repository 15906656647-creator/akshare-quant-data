"""Stage 18.1.2 capability-oriented valuation provider audit."""
from __future__ import annotations

import json
import platform
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .adapters.stage18_valuation import Stage18ValuationAdapter, ValuationCall
from .stage18_audit import (
    Stage18Blocked, _atomic_csv, _atomic_text, _relative, frozen_hashes,
    select_samples, validate_upstream,
)
from .stage18_config import load_stage18_config
from .stage18_valuation_config import ProviderSpec, load_stage18_valuation_config
from .storage.raw_store import file_record, schema_hash
from .storage.stage18_raw_store import Stage18RawStore


INVENTORY_COLUMNS = [
    "run_id", "market", "symbol", "interface", "provider", "mode", "status",
    "rejection_reason", "fields_present", "required_fields", "missing_fields",
    "optional_fields_present", "pe_semantics", "pb_semantics",
    "market_cap_semantics", "snapshot_time", "observation_date", "identity_method",
    "quote_capability", "attempt_count", "attempts", "request_parameters",
    "raw_data_paths", "metadata_paths", "selected_for_stage18_2", "asset_role",
    "audit_only", "eligible_for_stage18_2_ingestion", "akshare_version",
    "function_signature", "schema_hashes",
]

FIELD_ALIASES = {
    "symbol": ("代码", "股票代码", "symbol", "code", "security_code", "stock_id"),
    "pe": ("市盈率", "市盈率ttm", "市盈率(t tm)", "pe", "pe_ttm", "per"),
    "pb": ("市净率", "pb", "pb_ttm"),
    "total_market_cap": (
        "总市值", "总市值(港元)", "total_market_cap", "market_cap", "mktcap",
        "totalmarketvalue", "total_market_value",
    ),
    "floating_market_cap": (
        "流通市值", "流通值", "nmc", "circulation_value", "float_market_cap",
        "negotiable_market_value",
    ),
    "hk_market_cap": ("港股市值", "港股市值(港元)", "hksk_market_cap"),
}
QUOTE_ALIASES = ("最新价", "trade", "price", "current_price", "now")
SENSITIVE_RE = re.compile(r"(?i)(token|cookie|authorization|password|api[_-]?key|proxy)")


def _normal(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).casefold())


def _column_for(frame: pd.DataFrame, field: str) -> str | None:
    aliases = {_normal(value) for value in FIELD_ALIASES[field]}
    for column in frame.columns:
        normalized = _normal(column)
        if normalized in aliases or any(alias and alias in normalized for alias in aliases):
            return str(column)
    return None


def _quote_capability(frame: pd.DataFrame) -> bool:
    columns = {_normal(column) for column in frame.columns}
    return any(_normal(alias) in columns for alias in QUOTE_ALIASES)


def _normalize_symbol(value: Any) -> str:
    token = str(value).upper().replace(".0", "").replace(".HK", "")
    token = re.sub(r"^(SH|SZ|BJ|HK)", "", token)
    return token.lstrip("0") or "0"


def _filter_symbol(frame: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, str]:
    code_column = _column_for(frame, "symbol")
    if code_column is None:
        raise ValueError("response has no recognizable security identity column")
    expected = _normalize_symbol(symbol)
    mask = frame[code_column].map(_normalize_symbol).eq(expected)
    return frame.loc[mask].copy(), f"response_column:{code_column}"


def _safe_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): ("<redacted>" if SENSITIVE_RE.search(str(key)) else value)
        for key, value in parameters.items()
    }


def _latest_observation(frame: pd.DataFrame) -> str:
    for column in frame.columns:
        if _normal(column) in {"date", "日期", "observationdate", "reportdate", "报告日期"}:
            parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
            if not parsed.empty:
                return parsed.max().date().isoformat()
    return ""


def _has_numeric_observation(frame: pd.DataFrame) -> bool:
    for column in frame.columns:
        if _normal(column) in {
            "date", "日期", "observationdate", "reportdate", "报告日期",
        }:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if isinstance(values, pd.Series) and values.notna().any():
            return True
    return False


def _metric_requests(spec: ProviderSpec, market: str, symbol: str) -> list[tuple[str, dict[str, Any]]]:
    plain = symbol.replace(".HK", "")
    if spec.interface == "stock_zh_valuation_baidu":
        return [
            ("pe", {"symbol": plain, "indicator": "市盈率(TTM)", "period": "近一年"}),
            ("pb", {"symbol": plain, "indicator": "市净率", "period": "近一年"}),
            ("total_market_cap", {"symbol": plain, "indicator": "总市值", "period": "近一年"}),
        ]
    if spec.interface == "stock_hk_valuation_baidu":
        return [
            ("pe", {"symbol": plain, "indicator": "市盈率(TTM)", "period": "近一年"}),
            ("pb", {"symbol": plain, "indicator": "市净率", "period": "近一年"}),
            ("total_market_cap", {"symbol": plain, "indicator": "总市值", "period": "近一年"}),
        ]
    if spec.interface == "stock_hk_indicator_eniu":
        eniu_symbol = "hk" + plain
        return [
            ("pe", {"symbol": eniu_symbol, "indicator": "市盈率"}),
            ("pb", {"symbol": eniu_symbol, "indicator": "市净率"}),
            ("total_market_cap", {"symbol": eniu_symbol, "indicator": "市值"}),
        ]
    raise ValueError(f"No metric request mapping for {market}/{spec.interface}")


def _direct_parameters(spec: ProviderSpec, symbol: str) -> dict[str, Any]:
    if spec.interface in {
        "stock_zh_valuation_comparison_em", "stock_zh_scale_comparison_em",
    }:
        exchange = "SH" if symbol.startswith("6") else "SZ"
        return {"symbol": exchange + symbol}
    if spec.interface == "stock_hk_financial_indicator_em":
        return {"symbol": symbol.replace(".HK", "")}
    return {}


def _write_call(
    *, call: ValuationCall, store: Stage18RawStore, root: Path, run_id: str,
    market: str, symbol: str, spec: ProviderSpec, variant: str,
    parameters: dict[str, Any], snapshot_time: str, signature: str,
    akshare_version: str, config: Any,
) -> dict[str, Any]:
    metadata = {
        "stage": 18, "substage": "18.1.2", "run_id": run_id,
        "market": market, "symbol": symbol, "interface": spec.interface,
        "provider": spec.provider, "mode": spec.mode, "variant": variant,
        "request_parameters": _safe_parameters(parameters),
        "snapshot_time": snapshot_time, "analysis_as_of_date": config.as_of_date.isoformat(),
        "status": call.status, "error_type": call.error_type,
        "error_message": call.error_message[:500], "attempt_count": call.attempt_count,
        "attempts": [item.__dict__ for item in call.attempts],
        "asset_role": config.asset_role, "audit_only": True,
        "eligible_for_stage18_2_ingestion": False,
        "akshare_version": akshare_version, "function_signature": signature,
    }
    directory = store.dataset_dir(
        run_id=run_id, category="valuation_provider_audit", market=market,
        symbol=symbol, interface=spec.interface, variant=variant,
    )
    return store.write(call.dataframe, directory, metadata)


def _summary_row(
    *, run_id: str, market: str, symbol: str, spec: ProviderSpec,
    root: Path,
    calls: list[tuple[str, dict[str, Any], ValuationCall, dict[str, Any]]],
    frame: pd.DataFrame | None, identity_method: str, config: Any,
    signature: str, akshare_version: str, snapshot_time: str,
) -> dict[str, Any]:
    required = set(config.required_capabilities[market])
    optional = set(config.optional_capabilities[market])
    fields = {"symbol", "snapshot_time"}
    observation_dates = []
    if spec.mode == "metric_series":
        for semantic, _parameters, call, _stored in calls:
            if call.status == "success" and call.dataframe is not None and not call.dataframe.empty:
                if _has_numeric_observation(call.dataframe):
                    fields.add(semantic)
                observed = _latest_observation(call.dataframe)
                if observed:
                    observation_dates.append(observed)
    elif frame is not None and not frame.empty:
        for semantic in ("pe", "pb", "total_market_cap", "floating_market_cap", "hk_market_cap"):
            column = _column_for(frame, semantic)
            if column is not None and pd.to_numeric(frame[column], errors="coerce").notna().any():
                fields.add(semantic)
        observed = _latest_observation(frame)
        if observed:
            observation_dates.append(observed)

    terminal_calls = [call for _variant, _params, call, _stored in calls]
    if any(call.status == "failed" for call in terminal_calls):
        status = "FAIL"
        rejection = next(call.error_type for call in terminal_calls if call.status == "failed")
    elif any(call.status == "unavailable" for call in terminal_calls):
        status, rejection = "UNAVAILABLE", "function_missing"
    elif any(call.status == "empty" for call in terminal_calls):
        status, rejection = "FAIL", "unexplained_empty_result"
    elif frame is not None and frame.empty and spec.mode == "shared_snapshot":
        status, rejection = "UNAVAILABLE", "symbol_not_supported_by_provider"
    else:
        missing = required - fields
        status = "PASS" if not missing else "UNAVAILABLE"
        rejection = "" if not missing else "missing_required_semantics:" + ",".join(sorted(missing))
    attempts = [item.__dict__ for call in terminal_calls for item in call.attempts]
    parameters = [
        {"variant": variant, "parameters": _safe_parameters(params)}
        for variant, params, _call, _stored in calls
    ]
    data_paths = [
        _relative(stored["data_path"], root=root)
        if stored.get("data_path") is not None else ""
        for _variant, _params, _call, stored in calls
    ]
    metadata_paths = [
        _relative(stored["metadata_path"], root=root)
        for _variant, _params, _call, stored in calls
    ]
    schemas = [
        schema_hash(call.dataframe) if call.dataframe is not None else ""
        for call in terminal_calls
    ]
    cap_semantics = "provider-reported total market capitalisation"
    if "floating_market_cap" in fields:
        cap_semantics += "; provider-reported circulating market capitalisation"
    if "hk_market_cap" in fields:
        cap_semantics += "; provider-reported HK-share market capitalisation"
    return {
        "run_id": run_id, "market": market, "symbol": symbol,
        "interface": spec.interface, "provider": spec.provider, "mode": spec.mode,
        "status": status, "rejection_reason": rejection,
        "fields_present": json.dumps(sorted(fields), ensure_ascii=False),
        "required_fields": json.dumps(sorted(required), ensure_ascii=False),
        "missing_fields": json.dumps(sorted(required-fields), ensure_ascii=False),
        "optional_fields_present": json.dumps(sorted(optional & fields), ensure_ascii=False),
        "pe_semantics": "provider-reported TTM/current PE" if "pe" in fields else "unavailable",
        "pb_semantics": "provider-reported current PB" if "pb" in fields else "unavailable",
        "market_cap_semantics": cap_semantics if "total_market_cap" in fields else "unavailable",
        "snapshot_time": snapshot_time,
        "observation_date": max(observation_dates) if observation_dates else "",
        "identity_method": identity_method,
        "quote_capability": bool(frame is not None and not frame.empty and _quote_capability(frame)),
        "attempt_count": len(attempts), "attempts": json.dumps(attempts, ensure_ascii=False),
        "request_parameters": json.dumps(parameters, ensure_ascii=False, sort_keys=True),
        "raw_data_paths": json.dumps(data_paths, ensure_ascii=False),
        "metadata_paths": json.dumps(metadata_paths, ensure_ascii=False),
        "selected_for_stage18_2": False, "asset_role": config.asset_role,
        "audit_only": True, "eligible_for_stage18_2_ingestion": False,
        "akshare_version": akshare_version, "function_signature": signature,
        "schema_hashes": json.dumps(schemas),
    }


def _frozen_rows(evidence: dict[str, Any], run_id: str, config: Any) -> list[dict[str, Any]]:
    rows = []
    for result in evidence["results"]:
        rows.append({
            "run_id": run_id, "market": result["market"], "symbol": "*",
            "interface": result["interface"], "provider": "EastmoneyPush2",
            "mode": "frozen_failed_shared_snapshot", "status": "FAIL",
            "rejection_reason": result["error_type"], "fields_present": "[]",
            "required_fields": json.dumps(sorted(config.required_capabilities[result["market"]])),
            "missing_fields": json.dumps(sorted(config.required_capabilities[result["market"]])),
            "optional_fields_present": "[]", "pe_semantics": "unavailable",
            "pb_semantics": "unavailable", "market_cap_semantics": "unavailable",
            "snapshot_time": evidence["finished_at"], "observation_date": "",
            "identity_method": "shared_request_not_returned", "quote_capability": False,
            "attempt_count": len(result["attempts"]),
            "attempts": json.dumps(result["attempts"], ensure_ascii=False),
            "request_parameters": "[]", "raw_data_paths": "[]", "metadata_paths": "[]",
            "selected_for_stage18_2": False, "asset_role": config.asset_role,
            "audit_only": True, "eligible_for_stage18_2_ingestion": False,
            "akshare_version": evidence["akshare_version"], "function_signature": "()",
            "schema_hashes": "[]",
        })
    return rows


def _validate_1811(root: Path, config: Any) -> dict[str, Any]:
    path = root / config.upstream_evidence_path
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Stage18Blocked("Stage 18.1.1 evidence is missing or invalid") from exc
    governance = evidence.get("governance", {})
    if (
        evidence.get("run_id") != config.upstream_run_id
        or governance.get("status") != config.upstream_status
        or governance.get("stage18_2_authorized") is not False
        or governance.get("next_permitted_task")
        != "Stage 18.1.2 alternative real-time valuation provider capability audit"
    ):
        raise Stage18Blocked("Stage 18.1.1 governance evidence does not authorize 18.1.2")
    results = {item.get("interface"): item for item in evidence.get("results", [])}
    for interface in config.frozen_failed_interfaces:
        item = results.get(interface)
        if item is None or item.get("terminal_status") != "FAIL" or item.get("error_type") != "connection_error":
            raise Stage18Blocked(f"Stage 18.1.1 frozen failure differs for {interface}")
    return evidence


def _render_markdown(run: dict[str, Any], inventory: pd.DataFrame, capability: pd.DataFrame) -> str:
    lines = [
        "# Stage 18.1.2 备用实时估值 Provider / 能力审计", "",
        f"- Run ID: `{run['run_id']}`", f"- 状态: `{run['status']}`",
        f"- AKShare: `{run['akshare_version']}`", f"- 基准日: `{run['analysis_as_of_date']}`",
        "- 审计资产不得直接进入 Stage 18.2。", "", "## 市场级能力结论", "",
        "|市场|能力状态|选定Provider|缺口|", "|---|---|---|---|",
    ]
    for row in capability.itertuples(index=False):
        lines.append(f"|{row.market}|{row.status}|{row.selected_provider or '-'}|{row.reason or '-'}|")
    lines.extend(["", "## Provider终态", "", "|市场|证券|接口|Provider|状态|选用|拒绝原因|", "|---|---|---|---|---|---|---|"])
    for row in inventory.itertuples(index=False):
        lines.append(
            f"|{row.market}|{row.symbol}|`{row.interface}`|{row.provider}|{row.status}|"
            f"{row.selected_for_stage18_2}|{str(row.rejection_reason).replace('|', '/')}|"
        )
    lines.extend([
        "", "## 治理", "",
        "Eastmoney `stock_zh_a_spot_em` 与 `stock_hk_spot_em` 的既有 `FAIL/connection_error` 原样保留，未降级为 `UNAVAILABLE`。",
        "Provider失败与市场级估值能力失败分开判定；只有语义完整且覆盖全部审计样本的Provider可被选择。",
        "全部证据均为 `asset_role=valuation_provider_audit`、`audit_only=true`、`eligible_for_stage18_2_ingestion=false`。",
        "本任务不重跑完整 Stage 18.1，不授权或启动 Stage 18.2。", "",
        "本报告仅用于数据能力研究与测试，不构成投资建议。", "",
    ])
    return "\n".join(lines)



def _estimated_network_calls(config: Any, samples: list[Any]) -> int:
    total = 0
    for market in ("A", "HK"):
        sample_count = sum(item.market == market for item in samples)
        for spec in config.registry[market]:
            if spec.mode == "shared_snapshot":
                total += 1
            elif spec.mode == "metric_series":
                total += sample_count * 3
            else:
                total += sample_count
    return total

def run_stage18_valuation_audit(
    *, root: str | Path = ".", config_path: str | Path = "config/stage18_valuation_audit.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False, adapter: Any | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, Any], int]:
    repo = Path(root).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = repo / config_file
    config = load_stage18_valuation_config(config_file)
    if as_of_date != config.as_of_date:
        raise ValueError("Stage 18.1.2 as_of_date differs from frozen configuration")
    if upstream_run_id is not None and upstream_run_id != config.upstream_run_id:
        raise ValueError("Stage 18.1.2 upstream run_id differs from frozen configuration")
    evidence = _validate_1811(repo, config)
    base_config_path = repo / config.stage18_config_path
    base_config = load_stage18_config(base_config_path)
    if base_config.as_of_date != config.as_of_date:
        raise Stage18Blocked("Stage 18.1 and 18.1.2 baseline dates differ")
    stage0_before = frozen_hashes(repo)
    securities = validate_upstream(repo, base_config)
    samples, reasons = select_samples(securities)
    actual_adapter = adapter or Stage18ValuationAdapter()
    discovered = [
        row for row in actual_adapter.discover(config.scan_keywords)
        if row["interface"].startswith("stock_")
    ]
    preview = {
        "stage": 18, "substage": "18.1.2", "status": "READY",
        "upstream_stage18_1_1_run_id": config.upstream_run_id,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "sample_symbols": [item.symbol for item in samples], "sample_reasons": reasons,
        "configured_providers": {
            market: [item.interface for item in config.registry[market]] for market in ("A", "HK")
        },
        "discovered_function_count": len(discovered), "network_calls": _estimated_network_calls(config, samples),
    }
    if validate_only or dry_run:
        return preview, 0

    actual_run_id = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(actual_run_id)
    except ValueError as exc:
        raise ValueError("Stage 18.1.2 run_id must be a UUID") from exc
    report_dir = repo / config.reports_root / actual_run_id
    if report_dir.exists():
        raise FileExistsError(f"Stage 18.1.2 report run already exists: {report_dir}")
    store = Stage18RawStore(repo / config.raw_root)
    started_at = clock().astimezone(timezone.utc).isoformat()
    rows = _frozen_rows(evidence, actual_run_id, config)
    shared_cache: dict[str, tuple[ValuationCall, dict[str, Any], str]] = {}
    for market in ("A", "HK"):
        market_samples = [item for item in samples if item.market == market]
        for spec in config.registry[market]:
            exists, signature, _module, _source = actual_adapter.inspect_function(spec.interface)
            if not exists:
                signature = ""
            for security in market_samples:
                snapshot_time = clock().astimezone(timezone.utc).isoformat()
                calls = []
                frame = None
                identity_method = "request_parameter"
                if spec.mode == "shared_snapshot":
                    if spec.interface not in shared_cache:
                        parameters = {}
                        call = actual_adapter.call(
                            spec.interface, parameters, max_attempts=config.max_attempts,
                            retry_delay_seconds=config.retry_delay_seconds,
                            timeout_seconds=config.request_timeout_seconds,
                        )
                        stored = _write_call(
                            call=call, store=store, root=repo, run_id=actual_run_id,
                            market=market, symbol="ALL", spec=spec, variant="shared",
                            parameters=parameters, snapshot_time=snapshot_time,
                            signature=signature, akshare_version=actual_adapter.akshare_version,
                            config=config,
                        )
                        shared_cache[spec.interface] = (call, stored, snapshot_time)
                    call, stored, snapshot_time = shared_cache[spec.interface]
                    calls = [("shared", {}, call, stored)]
                    if call.dataframe is not None and not call.dataframe.empty:
                        try:
                            frame, identity_method = _filter_symbol(call.dataframe, security.symbol)
                        except ValueError as exc:
                            call = ValuationCall(None, "failed", "identity_schema_error", str(exc), call.attempts)
                            calls = [("shared", {}, call, stored)]
                elif spec.mode == "symbol_snapshot":
                    parameters = _direct_parameters(spec, security.symbol)
                    call = actual_adapter.call(
                        spec.interface, parameters, max_attempts=config.max_attempts,
                        retry_delay_seconds=config.retry_delay_seconds,
                        timeout_seconds=config.request_timeout_seconds,
                    )
                    stored = _write_call(
                        call=call, store=store, root=repo, run_id=actual_run_id,
                        market=market, symbol=security.symbol, spec=spec, variant="snapshot",
                        parameters=parameters, snapshot_time=snapshot_time,
                        signature=signature, akshare_version=actual_adapter.akshare_version,
                        config=config,
                    )
                    calls = [("snapshot", parameters, call, stored)]
                    frame = call.dataframe
                else:
                    for semantic, parameters in _metric_requests(spec, market, security.symbol):
                        call = actual_adapter.call(
                            spec.interface, parameters, max_attempts=config.max_attempts,
                            retry_delay_seconds=config.retry_delay_seconds,
                            timeout_seconds=config.request_timeout_seconds,
                        )
                        stored = _write_call(
                            call=call, store=store, root=repo, run_id=actual_run_id,
                            market=market, symbol=security.symbol, spec=spec, variant=semantic,
                            parameters=parameters, snapshot_time=snapshot_time,
                            signature=signature, akshare_version=actual_adapter.akshare_version,
                            config=config,
                        )
                        calls.append((semantic, parameters, call, stored))
                rows.append(_summary_row(
                    run_id=actual_run_id, market=market, symbol=security.symbol,
                    root=repo,
                    spec=spec, calls=calls, frame=frame, identity_method=identity_method,
                    config=config, signature=signature,
                    akshare_version=actual_adapter.akshare_version, snapshot_time=snapshot_time,
                ))

    inventory = pd.DataFrame(rows, columns=INVENTORY_COLUMNS)
    capability_rows = []
    for market in ("A", "HK"):
        market_symbols = {item.symbol for item in samples if item.market == market}
        selected = ""
        for spec in config.registry[market]:
            mask = inventory["market"].eq(market) & inventory["interface"].eq(spec.interface) & inventory["symbol"].isin(market_symbols)
            if int(mask.sum()) == len(market_symbols) and inventory.loc[mask, "status"].eq("PASS").all():
                selected = spec.interface
                inventory.loc[mask, "selected_for_stage18_2"] = True
                break
        if not selected and market == "A":
            composite_interfaces = {
                "stock_zh_valuation_comparison_em", "stock_zh_scale_comparison_em",
            }
            composite = inventory[
                inventory["market"].eq("A")
                & inventory["symbol"].isin(market_symbols)
                & inventory["interface"].isin(composite_interfaces)
            ]
            complete = set(composite["interface"]) == composite_interfaces
            for symbol in market_symbols:
                symbol_rows = composite.loc[composite["symbol"].eq(symbol)]
                union = set()
                for value in symbol_rows["fields_present"]:
                    union.update(json.loads(value))
                complete = complete and set(
                    config.required_capabilities["A"]
                ).issubset(union)
                complete = complete and not symbol_rows["status"].eq("FAIL").any()
            if complete:
                selected = "EastmoneyDataCenter[valuation_comparison+scale_comparison]"
                inventory.loc[composite.index, "selected_for_stage18_2"] = True
        configured_mask = inventory["market"].eq(market) & inventory["symbol"].isin(market_symbols)
        if selected:
            cap_status, reason = "PASS", ""
        elif inventory.loc[configured_mask, "status"].eq("FAIL").any():
            cap_status, reason = "BLOCKED", "unresolved_provider_failure_without_complete_alternative"
        else:
            cap_status, reason = "UNAVAILABLE", "all_audited_providers_have_explicit_semantic_gaps"
        capability_rows.append({
            "run_id": actual_run_id, "market": market, "status": cap_status,
            "selected_provider": selected, "reason": reason,
            "required_capabilities": json.dumps(config.required_capabilities[market]),
        })
    capability = pd.DataFrame(capability_rows)
    stage0_after = frozen_hashes(repo)
    status = "PASS" if not capability["status"].eq("BLOCKED").any() and stage0_before == stage0_after else "BLOCKED"
    finished_at = clock().astimezone(timezone.utc).isoformat()
    run_payload = {
        "stage": 18, "substage": "18.1.2", "run_id": actual_run_id,
        "status": status, "started_at": started_at, "finished_at": finished_at,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "upstream_stage18_1_1_run_id": config.upstream_run_id,
        "frozen_failed_interfaces": list(config.frozen_failed_interfaces),
        "sample_symbols": [item.symbol for item in samples], "sample_reasons": reasons,
        "provider_status_counts": {k: int(v) for k, v in inventory["status"].value_counts().items()},
        "valuation_capabilities": capability.to_dict("records"),
        "akshare_version": actual_adapter.akshare_version,
        "python_version": platform.python_version(), "discovered_functions": discovered,
        "stage0_hashes_before": stage0_before, "stage0_hashes_after": stage0_after,
        "stage0_hashes_unchanged": stage0_before == stage0_after,
        "raw_closed_world": True, "full_stage18_1_rerun_recommended": status == "PASS",
        "stage18_2_authorized": False, "stage18_2_started": False,
    }
    inventory_path = report_dir / "valuation_provider_inventory.csv"
    capability_path = report_dir / "valuation_capability_matrix.csv"
    scan_path = report_dir / "valuation_function_scan.csv"
    report_path = report_dir / "valuation_provider_audit.md"
    _atomic_csv(inventory_path, inventory, must_not_exist=True)
    _atomic_csv(capability_path, capability, must_not_exist=True)
    _atomic_csv(scan_path, pd.DataFrame(discovered), must_not_exist=True)
    _atomic_text(report_path, _render_markdown(run_payload, inventory, capability), must_not_exist=True)
    raw_run_root = repo / config.raw_root / f"run_id={actual_run_id}"
    files = [file_record(path, repo) for path in sorted(raw_run_root.rglob("*")) if path.is_file()]
    files.extend(file_record(path, repo) for path in (inventory_path, capability_path, scan_path, report_path))
    manifest = {
        "stage": 18, "substage": "18.1.2", "run_id": actual_run_id,
        "status": status, "inventory_columns": INVENTORY_COLUMNS,
        "inventory_rows": inventory.to_dict("records"),
        "capability_rows": capability.to_dict("records"), "files": files,
        "raw_manifest_closed_world": True,
    }
    _atomic_text(report_dir / "stage18_1_2_run.json", json.dumps(run_payload, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    _atomic_text(report_dir / "stage18_1_2_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    return run_payload, 0 if status == "PASS" else 2
