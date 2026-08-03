"""Stage 11 ETHUSDT capability-validation orchestration."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import duckdb

from .assets import AssetIdentity, AssetType, TradingCalendar
from .crypto_evidence import raw_projection_hash, validate_raw_evidence
from .crypto_market import (
    build_crypto_profile, compute_crypto_indicators, load_stage11_config,
    identity_contract_from_config, normalize_crypto_bars,
)
from .quality.crypto_checks import run_stage11_quality_checks
from .storage.crypto_repository import read_stage11_run, write_stage11_run


CANONICAL_PRICE_COLUMNS = [
    "requested_instrument", "raw_instrument", "normalized_instrument",
    "data_provider", "raw_exchange", "normalized_exchange", "instrument_type",
    "bar_interval", "confirmed", "symbol", "exchange", "market", "interval",
    "trade_time", "open", "high", "low", "close", "volume", "quote_volume",
    "source", "run_id",
]


def _now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def _frame_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    sort_columns = [name for name in ("symbol", "exchange", "market", "interval", "trade_time") if name in columns]
    normalized = frame[columns].copy().sort_values(sort_columns, kind="mergesort", na_position="first")
    for column in normalized:
        if "time" in column:
            parsed = pd.to_datetime(normalized[column], errors="coerce", utc=True)
            normalized[column] = parsed.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ").where(parsed.notna(), None)
        elif column in {"open", "high", "low", "close", "volume", "quote_volume"}:
            numeric = pd.to_numeric(normalized[column], errors="coerce")
            normalized[column] = numeric.map(lambda value: None if pd.isna(value) else format(float(value), ".12g"))
        else:
            normalized[column] = normalized[column].astype("string").where(normalized[column].notna(), None)
    payload = normalized.to_dict("records")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _canonical_row_hashes(frame: pd.DataFrame) -> list[str]:
    missing = sorted(set(CANONICAL_PRICE_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"canonical price fields missing: {missing}")
    normalized = frame[CANONICAL_PRICE_COLUMNS].copy()
    normalized["trade_time"] = pd.to_datetime(normalized["trade_time"], errors="raise", utc=True)
    normalized = normalized.sort_values(
        ["run_id", "normalized_instrument", "normalized_exchange", "bar_interval", "trade_time"],
        kind="mergesort",
    )
    hashes: list[str] = []
    for record in normalized.to_dict("records"):
        safe = _json_safe(record)
        for name in ("open", "high", "low", "close", "volume", "quote_volume"):
            safe[name] = format(float(safe[name]), ".12g")
        payload = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        hashes.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return hashes


def validate_stage11_inputs(
    *, config_path: Path, input_csv: Path | None, output_database: Path,
    input_json: Path | None = None, raw_evidence_dir: Path | None = None,
    run_id: str | None = None, as_of_date: pd.Timestamp | None = None,
    strict_artifacts: bool = False,
) -> dict[str, Any]:
    """Read-only validation of an existing run; never creates or repairs artifacts."""
    blockers: list[str] = []
    try:
        config, config_hash = load_stage11_config(config_path)
        identity = identity_contract_from_config(config)
    except (OSError, ValueError) as exc:
        return {"status": "BLOCKED", "blocking_reasons": [str(exc)]}
    protected = {"akshare_features_stage7.duckdb", "akshare_limit_events_stage8.duckdb", "akshare_style_stage9.duckdb", "akshare_fundamental_stage10.duckdb"}
    if output_database.name.lower() in protected:
        blockers.append("output_database_is_protected_baseline")
    if not strict_artifacts:
        if input_csv is not None and not input_csv.is_file():
            blockers.append(f"input CSV does not exist: {input_csv}")
        return {
            "status": "READY" if not blockers else "BLOCKED",
            "blocking_reasons": blockers, "config_hash": config_hash,
            "config_version": config["schema_version"], "symbol": config["symbol"],
            "asset_type": config["asset_type"], "trading_calendar": config["trading_calendar"],
        }
    if not run_id:
        blockers.append("run_id is required for strict validate-only")
    if as_of_date is None:
        blockers.append("as_of_date is required for strict validate-only")
    required_paths = {
        "CSV": input_csv, "JSON": input_json, "DuckDB": output_database,
        "Raw evidence": raw_evidence_dir,
    }
    for label, path in required_paths.items():
        if path is None or not path.exists():
            blockers.append(f"{label} does not exist: {path}")
        elif path.is_file() and path.stat().st_size == 0:
            blockers.append(f"{label} is empty: {path}")
    if blockers:
        return {"status": "BLOCKED", "blocking_reasons": blockers, "config_hash": config_hash}
    raw_result = validate_raw_evidence(raw_evidence_dir, run_id=run_id, expected=identity)  # type: ignore[arg-type]
    blockers.extend(raw_result["blocking_reasons"])
    frames: dict[str, pd.DataFrame] = {}
    try:
        frames["CSV"] = pd.read_csv(input_csv)  # type: ignore[arg-type]
    except Exception as exc:
        blockers.append(f"CSV parse failed: {exc}")
    try:
        payload = json.loads(input_json.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        if not isinstance(payload, list) or not payload:
            raise ValueError("root must be a non-empty array")
        frames["JSON"] = pd.DataFrame(payload)
    except Exception as exc:
        blockers.append(f"JSON parse failed: {exc}")
    persisted: dict[str, pd.DataFrame] = {}
    try:
        persisted = read_stage11_run(output_database, run_id)  # type: ignore[arg-type]
        frames["DuckDB"] = persisted["clean"]
    except (duckdb.Error, KeyError, ValueError) as exc:
        blockers.append(f"DuckDB validation read failed: {exc}")
    end = pd.Timestamp(as_of_date).normalize() + pd.Timedelta(days=1)  # type: ignore[arg-type]
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    start = end - pd.Timedelta(days=int(config["time"]["lookback_days"]))
    row_hashes: dict[str, list[str]] = {}
    for label, frame in frames.items():
        try:
            if frame.empty:
                raise ValueError("artifact contains no rows")
            if sorted(frame["run_id"].dropna().astype(str).unique()) != [run_id]:
                raise ValueError("run_id is missing or inconsistent")
            quality = run_stage11_quality_checks(
                frame, run_id=run_id, as_of_date=as_of_date, interval=identity.bar_interval,
                expected_symbol=identity.normalized_instrument, checked_at=_now(),
                expected_start=start, expected_end_exclusive=end,
            )
            failures = quality.loc[quality["status"].eq("FAIL"), "check_name"].astype(str).tolist()
            if failures:
                raise ValueError(f"quality checks failed: {failures}")
            row_hashes[label] = _canonical_row_hashes(frame)
            if raw_projection_hash(frame) != raw_result.get("raw_projection_sha256"):
                raise ValueError("artifact Raw projection does not match preserved response")
        except Exception as exc:
            blockers.append(f"{label} artifact invalid: {exc}")
    if len(row_hashes) == 3:
        reference = row_hashes["CSV"]
        for label in ("JSON", "DuckDB"):
            if row_hashes[label] != reference:
                blockers.append(f"CSV/JSON/DuckDB canonical row hashes mismatch: {label}")
    if persisted:
        expected_rows = len(frames.get("DuckDB", []))
        for name in ("raw", "clean", "indicators"):
            if len(persisted.get(name, [])) != expected_rows:
                blockers.append(f"DuckDB {name} row count mismatch")
        if len(persisted.get("profile", [])) != 1:
            blockers.append("DuckDB profile row count must be 1")
        quality_frame = persisted.get("quality", pd.DataFrame())
        if quality_frame.empty or quality_frame["status"].ne("PASS").any():
            blockers.append("DuckDB quality results are missing or contain failure")
        audit = persisted.get("audit", pd.DataFrame())
        if len(audit) != 1 or audit.iloc[0].get("run_status") != "PASS":
            blockers.append("DuckDB audit PASS record is missing or invalid")
    return {
        "status": "READY" if not blockers else "BLOCKED",
        "blocking_reasons": sorted(set(blockers)), "config_hash": config_hash,
        "config_version": config["schema_version"], "symbol": config["symbol"],
        "asset_type": config["asset_type"], "trading_calendar": config["trading_calendar"],
        "run_id": run_id, "row_count": len(frames.get("CSV", [])),
        "canonical_sha256": hashlib.sha256("".join(row_hashes.get("CSV", [])).encode()).hexdigest() if "CSV" in row_hashes else None,
        "raw_evidence": raw_result,
    }


def _render_validation(report: dict[str, Any]) -> str:
    blockers = "\n".join(f"- {item}" for item in report["blocking_reasons"]) or "- 无"
    return f"""# 阶段 11 ETHUSDT 验证与加密资产适配

- run_id：`{report['run_id']}`
- run_status：**{report['run_status']}**
- publication_status：`{report['publication_status']}`
- 数据来源：`{report['source']}`；AKShare `crypto_js_spot` 仅用于精确交易对能力探针，不替代历史 K 线来源
- AKShare 精确交易对能力：`{report['akshare_capability_status']}`（exact_match={report['akshare_exact_match']}）
- 资产：`{report['symbol']}` / `{report['exchange']}` / `crypto`
- 时间口径：UTC 为标准时间，Asia/Shanghai 为展示转换；`{report['interval']}` K 线；24/7 连续交易，不使用股票交易日历
- 截止日期：{report['as_of_date']}
- K 线：{report['row_count']} 行；指标：{report['indicator_row_count']} 行

## 指标适配

波动率、ATR、布林带、趋势、箱体和假突破均可迁移为描述性统计。年化因子按连续交易调整为日线 365、小时线 8760；成交量来自交易所且不等同于股票换手率。箱体和假突破依赖窗口与数据源，不能解释为价格预测。

## 质量门禁

- PASS：{report['quality_passed']}
- FAIL：{report['quality_failed']}
- 阻塞项：
{blockers}

## 隔离与限制

- `fundamental_analysis` 对 `asset_type=crypto` 返回 `not_applicable`，ETHUSDT 不进入股票财务分析。
- AKShare 历史 ETHUSDT K 线能力未被伪造；若使用 Binance 公共接口，来源明确标为 `binance_public_api`。
- 本阶段只输出统计特征，未形成价格预测、交易策略或投资结论。
"""


def _write_reports(root: Path, report: dict[str, Any], bars: pd.DataFrame, profile: pd.DataFrame, quality: pd.DataFrame) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    bars.to_csv(reports / "stage11_crypto_price.csv", index=False, encoding="utf-8-sig")
    (reports / "stage11_crypto_price.json").write_text(
        json.dumps(_json_safe(bars.to_dict("records")), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    quality.to_csv(reports / "stage11_quality.csv", index=False, encoding="utf-8-sig")
    payload = {**report, "profile": _json_safe(profile.to_dict("records"))}
    (reports / "stage11_run.json").write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    validation = _render_validation(report)
    (reports / "stage11_validation.md").write_text(validation, encoding="utf-8")
    audit = f"""# 阶段 11 独立验收状态

- run_id：`{report['run_id']}`
- 自测结论：**{report['run_status']}**
- 独立验收：`PENDING`
- 已覆盖：24/7 时间连续性、周末、UTC/本地转换、OHLCV、未来数据、run_id、指标迁移、财务隔离、CSV/JSON/DuckDB 一致性。
- 独立验收应核对真实来源许可、AKShare 精确交易对探针证据、历史 K 线覆盖与缺 K 线处理。
- 结果仅为统计特征验证，未形成投资结论。
"""
    (reports / "stage11_independent_audit.md").write_text(audit, encoding="utf-8")
    columns = CANONICAL_PRICE_COLUMNS
    csv_hash = _frame_hash(pd.read_csv(reports / "stage11_crypto_price.csv"), columns)
    json_hash = _frame_hash(pd.DataFrame(json.loads((reports / "stage11_crypto_price.json").read_text(encoding="utf-8"))), columns)
    if csv_hash != report["artifact_hash"] or json_hash != report["artifact_hash"]:
        raise RuntimeError("Stage 11 CSV/JSON artifacts do not match the canonical projection")


def analyze_stage11(
    *, root: Path, as_of_date: pd.Timestamp, input_frame: pd.DataFrame,
    interval: str, source: str, config_path: Path, output_database: Path,
    run_id: str | None = None, dry_run: bool = False,
    akshare_capability: dict[str, Any] | None = None,
    raw_evidence_dir: Path | None = None,
) -> tuple[dict[str, Any], int]:
    config, config_hash = load_stage11_config(config_path)
    identity = identity_contract_from_config(config)
    if interval not in config["time"]["supported_intervals"]:
        raise ValueError(f"unsupported interval: {interval}")
    run_id = run_id or str(uuid.uuid4())
    started = _now()
    if raw_evidence_dir is None:
        raise ValueError("raw_evidence_dir is required; Stage 11 cannot trust bars without Raw evidence")
    raw_validation = validate_raw_evidence(raw_evidence_dir, run_id=run_id, expected=identity)
    if raw_validation["status"] != "READY":
        raise ValueError("; ".join(raw_validation["blocking_reasons"]))
    if raw_projection_hash(input_frame) != raw_validation.get("raw_projection_sha256"):
        raise ValueError("input bars do not match preserved Raw response")
    asset = AssetIdentity(config["symbol"], config["exchange"], config["market"], AssetType.CRYPTO, TradingCalendar.CONTINUOUS_24_7)
    bars = normalize_crypto_bars(
        input_frame, asset=asset, interval=interval,
        local_timezone=config["time"]["local_timezone"], source=source,
        run_id=run_id, identity=identity,
    )
    indicators = compute_crypto_indicators(bars, interval=interval, config=config, run_id=run_id)
    profile = build_crypto_profile(indicators, config=config, as_of_date=as_of_date, run_id=run_id)
    profile["exchange"] = identity.normalized_exchange
    end = pd.Timestamp(as_of_date).normalize() + pd.Timedelta(days=1)
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    start = end - pd.Timedelta(days=int(config["time"]["lookback_days"]))
    quality = run_stage11_quality_checks(
        bars, run_id=run_id, as_of_date=as_of_date, interval=interval,
        expected_symbol=config["symbol"], checked_at=_now(),
        expected_start=start, expected_end_exclusive=end,
    )
    data_columns = CANONICAL_PRICE_COLUMNS
    artifact_hash = _frame_hash(bars, data_columns)
    failures = quality.loc[(quality["severity"] == "ERROR") & (quality["status"] == "FAIL")]
    blockers = quality.loc[quality["status"].eq("FAIL"), "check_name"].astype(str).tolist()
    run_status = "PASS" if failures.empty else "BLOCKED"
    report = {
        "run_id": run_id, "run_status": run_status,
        "publication_status": "descriptive_statistics" if run_status == "PASS" else "blocked",
        "as_of_date": pd.Timestamp(as_of_date).date().isoformat(), "symbol": config["symbol"],
        "exchange": identity.normalized_exchange, "interval": interval, "source": source,
        "requested_instrument": identity.requested_instrument,
        "raw_instrument": identity.raw_instrument,
        "normalized_instrument": identity.normalized_instrument,
        "data_provider": identity.data_provider,
        "raw_exchange": identity.raw_exchange,
        "normalized_exchange": identity.normalized_exchange,
        "instrument_type": identity.instrument_type,
        "bar_interval": identity.bar_interval,
        "row_count": len(bars), "indicator_row_count": len(indicators), "profile_row_count": len(profile),
        "quality_passed": int(quality["status"].eq("PASS").sum()), "quality_failed": int(quality["status"].eq("FAIL").sum()),
        "blocking_reasons": blockers, "config_hash": config_hash,
        "output_type": "dry_run" if dry_run else "stage11_validation",
        "started_at": started, "completed_at": _now(), "artifact_hash": artifact_hash,
        "fundamental_analysis_status": "not_applicable",
        "akshare_capability_status": (akshare_capability or {}).get("status", "not_run"),
        "akshare_exact_match": bool((akshare_capability or {}).get("exact_match", False)),
        "akshare_eth_matches": list((akshare_capability or {}).get("eth_matches", [])),
        "akshare_evidence_path": (akshare_capability or {}).get("evidence_path"),
    }
    audit = pd.DataFrame([{
        "run_id": run_id, "run_status": run_status, "publication_status": report["publication_status"],
        "started_at": report["started_at"], "completed_at": report["completed_at"],
        "as_of_date": report["as_of_date"], "symbol": config["symbol"], "exchange": identity.normalized_exchange,
        "interval": interval, "source": source, "row_count": len(bars), "indicator_row_count": len(indicators),
        "requested_instrument": identity.requested_instrument, "raw_instrument": identity.raw_instrument,
        "normalized_instrument": identity.normalized_instrument, "data_provider": identity.data_provider,
        "raw_exchange": identity.raw_exchange, "normalized_exchange": identity.normalized_exchange,
        "instrument_type": identity.instrument_type, "bar_interval": identity.bar_interval,
        "profile_row_count": len(profile), "quality_passed": report["quality_passed"], "quality_failed": report["quality_failed"],
        "config_hash": config_hash, "output_type": report["output_type"],
        "blocking_reasons_json": json.dumps(blockers, ensure_ascii=False),
        "manifest_json": json.dumps({"artifact_hash": artifact_hash, "asset_type": "crypto", "trading_calendar": "continuous_24_7", "akshare_capability": akshare_capability or {"status": "not_run"}}, ensure_ascii=False),
    }])
    if failures.empty and raw_validation["row_count"] != len(bars):
        failures = pd.DataFrame([{"check_name": "raw_response_row_count"}])
        blockers.append("raw_response_row_count")
        report["run_status"] = "BLOCKED"
        report["publication_status"] = "blocked"
        report["blocking_reasons"] = blockers
    if not dry_run:
        if not failures.empty:
            return report, 1
        frames = {"raw": bars, "clean": bars.copy(), "indicators": indicators, "profile": profile, "quality": quality, "audit": audit}
        write_stage11_run(output_database, schema_path=root / "sql" / "stage11_schema.sql", frames=frames, run_id=run_id)
        persisted = read_stage11_run(output_database, run_id)
        database_hash = _frame_hash(persisted["clean"], data_columns)
        if database_hash != artifact_hash:
            raise RuntimeError("Stage 11 DuckDB persistence does not match canonical price projection")
        _write_reports(root, report, bars, profile, quality)
        reports = root / "reports"
        csv_hash = _frame_hash(pd.read_csv(reports / "stage11_crypto_price.csv"), data_columns)
        json_hash = _frame_hash(pd.DataFrame(json.loads((reports / "stage11_crypto_price.json").read_text(encoding="utf-8"))), data_columns)
        consistency_passed = len({artifact_hash, database_hash, csv_hash, json_hash}) == 1
        quality = pd.concat([quality, pd.DataFrame([{
            "run_id": run_id, "check_name": "csv_json_duckdb_consistency",
            "severity": "ERROR", "status": "PASS" if consistency_passed else "FAIL",
            "observed_value": json.dumps({"memory": artifact_hash, "duckdb": database_hash, "csv": csv_hash, "json": json_hash}, sort_keys=True),
            "expected_value": "all canonical hashes equal",
            "message": "post-write full canonical Stage 11 price projection comparison",
            "checked_at": _now(),
        }])], ignore_index=True)
        if not consistency_passed:
            raise RuntimeError("Stage 11 post-write CSV/JSON/DuckDB consistency failed")
        report["quality_passed"] = int(quality["status"].eq("PASS").sum())
        audit.loc[0, "quality_passed"] = report["quality_passed"]
        frames["quality"], frames["audit"] = quality, audit
        write_stage11_run(output_database, schema_path=root / "sql" / "stage11_schema.sql", frames=frames, run_id=run_id)
        _write_reports(root, report, bars, profile, quality)
    return report, 0 if report["run_status"] == "PASS" else 1
