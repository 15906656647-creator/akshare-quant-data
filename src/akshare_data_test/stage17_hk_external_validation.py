"""Stage 17.6.3 isolated 09669.HK source comparison and external validation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .adapters.hk_external import ExternalHistoryCall, YahooHkAdapter
from .paths import project_root
from .stage17_hk_tencent_validation import _quality, _relative, _verify_listing_evidence
from .storage.stage17_raw_store import Stage17RawStore


SYMBOL = "09669.HK"
ADJUSTMENTS = ("raw", "qfq", "hfq")
COMPARISON_COLUMNS = (
    "provider", "interface", "adjust", "trade_date", "open", "high", "low",
    "close", "error_type", "error_detail", "source_run_id", "source_data_path",
    "source_sha256",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _dataset_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("datasets")
    if not isinstance(rows, list):
        raise ValueError("Evidence manifest has no datasets list")
    return [row for row in rows if isinstance(row, dict)]


def _normalize_existing(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "date": ("date", "日期", "trade_date"), "open": ("open", "开盘"),
        "high": ("high", "最高"), "low": ("low", "最低"),
        "close": ("close", "收盘"),
    }
    columns = {str(column).strip().casefold(): column for column in frame.columns}
    resolved: dict[str, Any] = {}
    for field, names in aliases.items():
        found = next((columns[name.casefold()] for name in names if name.casefold() in columns), None)
        if found is None:
            raise ValueError(f"Evidence candidate missing {field}")
        resolved[field] = found
    return frame[[resolved[field] for field in aliases]].rename(
        columns={resolved[field]: field for field in aliases}
    ).copy()


def _row_errors(row: pd.Series) -> list[str]:
    values = {field: pd.to_numeric(pd.Series([row[field]]), errors="coerce").iloc[0]
              for field in ("open", "high", "low", "close")}
    if any(pd.isna(value) for value in values.values()):
        return ["null_or_nonnumeric_ohlc"]
    errors: list[str] = []
    if values["open"] > values["high"]:
        errors.append("open_gt_high")
    if values["close"] > values["high"]:
        errors.append("close_gt_high")
    if values["open"] < values["low"]:
        errors.append("open_lt_low")
    if values["close"] < values["low"]:
        errors.append("close_lt_low")
    return errors


def _find_record(
    manifest: dict[str, Any], *, provider: str, adjust: str,
) -> dict[str, Any]:
    candidates = [
        row for row in _dataset_rows(manifest)
        if row.get("symbol") == SYMBOL and row.get("adjust") == adjust
        and (row.get("provider") == provider or row.get("source") == provider)
        and (row.get("kind") in (None, "equity_daily_candidate"))
    ]
    if len(candidates) != 1:
        raise ValueError(f"Expected one {provider}/{adjust} evidence record, got {len(candidates)}")
    return candidates[0]


def build_provider_comparison(
    *, root: Path, sina_run_id: str, tencent_run_id: str, eastmoney_run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifests = {
        "sina": _load_json(root / "reports/stage17" / sina_run_id / "stage17_manifest.json"),
        "tencent": _load_json(
            root / "reports/stage17_hk_tencent_validation" / tencent_run_id / "manifest.json"
        ),
        "eastmoney": _load_json(
            root / "reports/stage17_hk_eastmoney_validation" / eastmoney_run_id / "manifest.json"
        ),
    }
    run_ids = {"sina": sina_run_id, "tencent": tencent_run_id, "eastmoney": eastmoney_run_id}
    interfaces = {"sina": "stock_hk_daily", "tencent": "stock_zh_ah_daily", "eastmoney": "stock_hk_hist"}
    rows: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for provider in ("sina", "tencent", "eastmoney"):
        manifest = manifests[provider]
        if manifest.get("run_id") != run_ids[provider]:
            raise ValueError(f"{provider} evidence run identity mismatch")
        for adjust in ADJUSTMENTS:
            record = _find_record(manifest, provider=provider, adjust=adjust)
            path_value = record.get("data_path") or ""
            digest = record.get("data_sha256") or ""
            evidence_row = {
                "provider": provider, "adjust": adjust, "run_id": run_ids[provider],
                "status": record.get("status"), "quality_status": record.get("quality_status"),
                "error_type": record.get("error_type") or "",
                "error_message": record.get("error_message") or record.get("quality_errors") or "",
                "data_path": path_value, "data_sha256": digest,
            }
            evidence.append(evidence_row)
            if not path_value:
                rows.append({
                    "provider": provider, "interface": interfaces[provider], "adjust": adjust,
                    "trade_date": "", "open": "", "high": "", "low": "", "close": "",
                    "error_type": record.get("error_type") or "source_data_unavailable",
                    "error_detail": record.get("error_message") or record.get("quality_errors") or "",
                    "source_run_id": run_ids[provider], "source_data_path": "", "source_sha256": "",
                })
                continue
            path = root / path_value
            if not path.is_file() or not digest or _sha256(path) != digest:
                raise ValueError(f"{provider}/{adjust} evidence hash mismatch")
            frame = _normalize_existing(pd.read_parquet(path))
            invalid_count = 0
            for _, item in frame.iterrows():
                errors = _row_errors(item)
                if not errors:
                    continue
                invalid_count += 1
                rows.append({
                    "provider": provider, "interface": interfaces[provider], "adjust": adjust,
                    "trade_date": str(pd.to_datetime(item["date"]).date()),
                    "open": item["open"], "high": item["high"], "low": item["low"],
                    "close": item["close"], "error_type": "|".join(errors),
                    "error_detail": "strict_ohlc_envelope_violation",
                    "source_run_id": run_ids[provider], "source_data_path": path_value,
                    "source_sha256": digest,
                })
            if invalid_count == 0:
                rows.append({
                    "provider": provider, "interface": interfaces[provider], "adjust": adjust,
                    "trade_date": "", "open": "", "high": "", "low": "", "close": "",
                    "error_type": "no_ohlc_error", "error_detail": "candidate_has_no_ohlc_violation",
                    "source_run_id": run_ids[provider], "source_data_path": path_value,
                    "source_sha256": digest,
                })
    return rows, evidence


def _synchronized_dates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if not row["trade_date"] or row["error_type"] in {"no_ohlc_error", "source_data_unavailable"}:
            continue
        grouped.setdefault((row["adjust"], row["trade_date"]), set()).add(row["provider"])
    return [
        {"adjust": adjust, "trade_date": trade_date, "providers": sorted(providers)}
        for (adjust, trade_date), providers in sorted(grouped.items()) if len(providers) >= 2
    ]


def _atomic_bytes(path: Path, content: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"External Raw already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"External Raw temporary file already exists: {temporary}")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _write_yahoo_raw(
    *, root: Path, run_id: str, call: ExternalHistoryCall, fetched_at: datetime,
    listing_date: date, as_of_date: date,
) -> list[dict[str, Any]]:
    if call.raw_response is None:
        return []
    directory = (
        root / "data/raw/stage17/hk_external_source_response" / f"run_id={run_id}"
        / "market=HK" / f"symbol={SYMBOL}" / "source=yahoo"
    )
    response_path = directory / "response.json"
    metadata_path = directory / "metadata.json"
    _atomic_bytes(response_path, call.raw_response)
    metadata = {
        "stage": 17, "task": "stage17_6_3_09669_external_validation",
        "run_id": run_id, "symbol": SYMBOL, "provider": "yahoo",
        "provider_symbol": call.provider_symbol, "interface": "chart_v8",
        "request_time": fetched_at.isoformat(), "listing_date": listing_date.isoformat(),
        "as_of_date": as_of_date.isoformat(), "response_url": call.response_url,
        "provider_timezone": call.provider_timezone, "call_status": call.status,
        "attempt_count": call.attempt_count, "raw_response_sha256": _sha256(response_path),
        "provider_adjust_semantics": (
            "raw OHLC plus provider-native adjusted close; not equivalent to project qfq/hfq"
        ),
        "stage17_formal_dataset": False, "provider_registry_built": False,
        "stage18_authorized": False,
    }
    _atomic_bytes(
        metadata_path,
        (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return [
        {"role": "source_response", "path": _relative(response_path, root),
         "size_bytes": response_path.stat().st_size, "sha256": _sha256(response_path)},
        {"role": "source_metadata", "path": _relative(metadata_path, root),
         "size_bytes": metadata_path.stat().st_size, "sha256": _sha256(metadata_path)},
    ]


def _write_reports(
    *, root: Path, run_id: str, as_of_date: date, started_at: datetime,
    finished_at: datetime, comparison: list[dict[str, Any]], evidence: list[dict[str, Any]],
    synchronized: list[dict[str, Any]], external_results: list[dict[str, Any]],
    raw_files: list[dict[str, Any]], listing_evidence: list[dict[str, Any]],
) -> Path:
    reports_root = root / "reports/stage17_hk_external_validation"
    reports_root.mkdir(parents=True, exist_ok=True)
    target = reports_root / run_id
    if target.exists():
        raise FileExistsError(f"External validation report already exists: {target}")
    temp = Path(tempfile.mkdtemp(prefix=f".stage17-hk-external-{run_id}-", dir=reports_root))
    try:
        csv_path = temp / "09669_provider_comparison.csv"
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COMPARISON_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(comparison)
        yahoo_raw = next(row for row in external_results if row["provider"] == "yahoo" and row["adjust"] == "raw")
        yahoo_qfq = next(row for row in external_results if row["provider"] == "yahoo" and row["adjust"] == "qfq")
        yahoo_hfq = next(row for row in external_results if row["provider"] == "yahoo" and row["adjust"] == "hfq")
        external_pass = all(row["status"] == "PASS" for row in (yahoo_raw, yahoo_qfq, yahoo_hfq))
        synchronization_text = "\n".join(
            f"- `{row['adjust']}` `{row['trade_date']}`：{', '.join(row['providers'])}"
            for row in synchronized
        ) or "- 未发现两个以上来源在同一复权口径和日期同步触发OHLC异常。"
        provider_table = "\n".join(
            f"| {row['provider']} | {row['adjust']} | {row['status']} | {row['quality_status']} | {row['semantics']} | {row['reason'] or '-'} |"
            for row in external_results
        )
        report = f"""# Stage 17.6.3：09669.HK 外部数据源专项验证

验证批次：`{run_id}`
业务基准日：`{as_of_date.isoformat()}`

## 结论

- 专项状态：`{'PASS' if external_pass else 'BLOCKED'}`。
- Stage 17正式状态仍为：`BLOCKED`；Stage 18授权：`false`。
- 本批未建设Provider Registry，未重跑正式Stage 17。
- 既有三源证据表明腾讯raw通过但qfq/hfq接口失败；新浪和东方财富的09669候选存在OHLC异常。

## 跨源同步异常

{synchronization_text}

完整异常行、接口失败占位行和既有Raw哈希见`09669_provider_comparison.csv`。比较过程只读并
校验既有Raw，不重写、不删除、不插值，也不把raw当作复权行情。

## 外部来源结果

| provider | requested_adjust | status | quality | provider semantics | reason |
| --- | --- | --- | --- | --- | --- |
{provider_table}

Yahoo的`Adj Close`仅是Provider原生调整收盘序列，不包含调整后的完整OHLC，也没有证据可
证明其同时等价于本项目的前复权和后复权。因此即使Yahoo raw OHLC通过，也不能用于冒充
`qfq/hfq`。Alpha Vantage没有配置API密钥时不发起请求；HKEX未配置授权数据产品时不将
公开网页或推断值冒充历史复权数据。

## 后续门禁

只有可审计来源为`09669.HK`同时提供合法raw、qfq、hfq完整OHLC并覆盖已核验上市日期，
才具备进入独立Provider Registry任务的条件。否则应保持Stage 17 `BLOCKED`，或另行执行
Stage 17.6.4范围调整治理评估；本任务不作范围调整。
"""
        report_path = temp / "09669_source_validation.md"
        report_path.write_text(report, encoding="utf-8")
        manifest = {
            "stage": 17, "task": "stage17_6_3_09669_external_validation",
            "run_id": run_id, "symbol": SYMBOL, "as_of_date": as_of_date.isoformat(),
            "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
            "validation_status": "PASS" if external_pass else "BLOCKED",
            "stage17_formal_status_before": "BLOCKED",
            "stage17_formal_status_after": "BLOCKED", "stage17_formal_rerun": False,
            "provider_registry_built": False, "stage18_authorized": False,
            "existing_provider_evidence": evidence, "synchronized_anomalies": synchronized,
            "external_provider_results": external_results,
            "verified_listing_evidence": listing_evidence,
            "raw_manifest_closed_world": True, "raw_files": raw_files,
            "outputs": [
                {"path": (target / path.name).relative_to(root).as_posix(),
                 "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
                for path in (csv_path, report_path)
            ],
        }
        (temp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return target


def run_external_validation(
    *, evidence_run_id: str, tencent_run_id: str, eastmoney_run_id: str,
    as_of_date: date, run_id: str | None = None, validate_only: bool = False,
    dry_run: bool = False, root: Path | None = None,
    yahoo_adapter: YahooHkAdapter | None = None,
) -> dict[str, Any]:
    if validate_only and dry_run:
        raise ValueError("validate_only and dry_run are mutually exclusive")
    root = (root or project_root()).resolve()
    for value in (evidence_run_id, tencent_run_id, eastmoney_run_id):
        uuid.UUID(value)
    listing_dates, listing_evidence, _, _ = _verify_listing_evidence(
        root=root, evidence_run_id=evidence_run_id, as_of_date=as_of_date,
    )
    comparison, evidence = build_provider_comparison(
        root=root, sina_run_id=evidence_run_id, tencent_run_id=tencent_run_id,
        eastmoney_run_id=eastmoney_run_id,
    )
    plan = {
        "stage": 17, "task": "stage17_6_3_09669_external_validation",
        "symbol": SYMBOL, "as_of_date": as_of_date.isoformat(),
        "existing_provider_combinations": 9, "external_provider": "yahoo",
        "external_semantics": "raw_ohlc_plus_provider_native_adjusted_close",
        "stage17_formal_rerun": False, "provider_registry_built": False,
        "stage18_authorized": False,
    }
    if validate_only:
        return {**plan, "mode": "validate_only", "network_calls": 0, "outputs_written": False}
    if dry_run:
        return {**plan, "mode": "dry_run", "network_calls": 0, "outputs_written": False}
    if run_id is None:
        raise ValueError("Formal external validation requires an explicit run_id")
    uuid.UUID(run_id)
    raw_root = root / "data/raw/stage17"
    report_target = root / "reports/stage17_hk_external_validation" / run_id
    if report_target.exists() or any(raw_root.rglob(f"run_id={run_id}")):
        raise FileExistsError(f"External validation run_id already exists: {run_id}")
    listing_date = listing_dates[SYMBOL]
    started_at = datetime.now(timezone.utc)
    fetched_at = datetime.now(timezone.utc)
    adapter = yahoo_adapter or YahooHkAdapter()
    call = adapter.fetch_history(symbol=SYMBOL, listing_date=listing_date, as_of_date=as_of_date)
    raw_files = _write_yahoo_raw(
        root=root, run_id=run_id, call=call, fetched_at=fetched_at,
        listing_date=listing_date, as_of_date=as_of_date,
    )
    quality: dict[str, Any] | None = None
    candidate_result: dict[str, Any] | None = None
    if call.status == "success" and call.dataframe is not None:
        quality = _quality(
            call.dataframe[["date", "open", "high", "low", "close", "volume"]],
            listing_date=listing_date, as_of_date=as_of_date,
        )
        store = Stage17RawStore(raw_root)
        directory = store.dataset_dir(
            dataset="hk_external_candidate", run_id=run_id, market="HK",
            symbol=SYMBOL, adjust="provider_native", source="yahoo",
        )
        metadata = {
            "stage": 17, "task": "stage17_6_3_09669_external_validation",
            "run_id": run_id, "symbol": SYMBOL, "provider": "yahoo",
            "provider_symbol": call.provider_symbol, "interface": "chart_v8",
            "request_time": fetched_at.isoformat(), "listing_date": listing_date.isoformat(),
            "as_of_date": as_of_date.isoformat(), "provider_timezone": call.provider_timezone,
            "quality": quality, "provider_adjust_semantics": (
                "raw OHLC plus provider-native adjusted close; not project qfq or hfq"
            ),
            "stage17_formal_dataset": False, "provider_registry_built": False,
            "stage18_authorized": False,
        }
        candidate_result = store.write_dataset(call.dataframe, directory, metadata)
        for role, key in (("candidate_data", "data_path"), ("candidate_metadata", "metadata_path")):
            path = Path(candidate_result[key])
            raw_files.append({
                "role": role, "path": _relative(path, root), "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
    raw_pass = call.status == "success" and quality is not None and quality["status"] == "PASS"
    if call.dataframe is not None and candidate_result is not None:
        yahoo_path = _relative(Path(candidate_result["data_path"]), root)
        yahoo_hash = str(candidate_result["data_sha256"])
        yahoo_invalid_count = 0
        for _, item in call.dataframe.iterrows():
            errors = _row_errors(item)
            if not errors:
                continue
            yahoo_invalid_count += 1
            comparison.append({
                "provider": "yahoo", "interface": "chart_v8", "adjust": "raw",
                "trade_date": str(pd.to_datetime(item["date"]).date()),
                "open": item["open"], "high": item["high"], "low": item["low"],
                "close": item["close"], "error_type": "|".join(errors),
                "error_detail": "strict_ohlc_envelope_violation",
                "source_run_id": run_id, "source_data_path": yahoo_path,
                "source_sha256": yahoo_hash,
            })
        if yahoo_invalid_count == 0:
            comparison.append({
                "provider": "yahoo", "interface": "chart_v8", "adjust": "raw",
                "trade_date": "", "open": "", "high": "", "low": "", "close": "",
                "error_type": "no_ohlc_error", "error_detail": "candidate_has_no_ohlc_violation",
                "source_run_id": run_id, "source_data_path": yahoo_path,
                "source_sha256": yahoo_hash,
            })
    for adjust, error_type in (
        ("qfq", "adjusted_close_is_not_verified_qfq_ohlc"),
        ("hfq", "adjusted_close_is_not_verified_hfq_ohlc"),
    ):
        comparison.append({
            "provider": "yahoo", "interface": "chart_v8", "adjust": adjust,
            "trade_date": "", "open": "", "high": "", "low": "", "close": "",
            "error_type": error_type, "error_detail": "incompatible_adjust_semantics",
            "source_run_id": run_id,
            "source_data_path": _relative(Path(candidate_result["data_path"]), root)
            if candidate_result else "",
            "source_sha256": str(candidate_result["data_sha256"]) if candidate_result else "",
        })
    semantics = "provider_native_raw_ohlc_and_adjusted_close_only"
    external_results = [
        {
            "provider": "yahoo", "interface": "chart_v8", "adjust": "raw",
            "status": "PASS" if raw_pass else "FAIL",
            "quality_status": quality["status"] if quality else "NOT_RUN",
            "semantics": semantics,
            "reason": "" if raw_pass else ("|".join(quality.get("errors", [])) if quality else call.error_type),
            "row_count": len(call.dataframe) if call.dataframe is not None else 0,
            "raw_response_sha256": raw_files[0]["sha256"] if raw_files else "",
        },
        {
            "provider": "yahoo", "interface": "chart_v8", "adjust": "qfq",
            "status": "FAIL", "quality_status": "NOT_RUN", "semantics": semantics,
            "reason": "adjusted_close_is_not_verified_qfq_ohlc", "row_count": 0,
            "raw_response_sha256": raw_files[0]["sha256"] if raw_files else "",
        },
        {
            "provider": "yahoo", "interface": "chart_v8", "adjust": "hfq",
            "status": "FAIL", "quality_status": "NOT_RUN", "semantics": semantics,
            "reason": "adjusted_close_is_not_verified_hfq_ohlc", "row_count": 0,
            "raw_response_sha256": raw_files[0]["sha256"] if raw_files else "",
        },
        {
            "provider": "alpha_vantage", "interface": "TIME_SERIES_DAILY_ADJUSTED",
            "adjust": "capability", "status": "UNAVAILABLE", "quality_status": "NOT_RUN",
            "semantics": "provider_adjusted_daily_not_assumed_qfq_or_hfq",
            "reason": "api_key_not_configured; no request sent", "row_count": 0,
            "raw_response_sha256": "",
        },
        {
            "provider": "hkex", "interface": "licensed_historical_data_product",
            "adjust": "capability", "status": "UNAVAILABLE", "quality_status": "NOT_RUN",
            "semantics": "no licensed adjusted-history interface configured",
            "reason": "product entitlement and interface not configured; no request sent",
            "row_count": 0, "raw_response_sha256": "",
        },
    ]
    synchronized = _synchronized_dates(comparison)
    finished_at = datetime.now(timezone.utc)
    report_dir = _write_reports(
        root=root, run_id=run_id, as_of_date=as_of_date, started_at=started_at,
        finished_at=finished_at, comparison=comparison, evidence=evidence,
        synchronized=synchronized, external_results=external_results, raw_files=raw_files,
        listing_evidence=listing_evidence,
    )
    return {
        **plan, "mode": "formal_validation", "run_id": run_id,
        "validation_status": "BLOCKED", "yahoo_raw_status": "PASS" if raw_pass else "FAIL",
        "qfq_status": "FAIL", "hfq_status": "FAIL", "report_dir": str(report_dir),
        "stage17_formal_status": "BLOCKED",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate external history for 09669.HK")
    parser.add_argument("--evidence-run-id", required=True)
    parser.add_argument("--tencent-run-id", required=True)
    parser.add_argument("--eastmoney-run-id", required=True)
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    parser.add_argument("--run-id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_external_validation(
        evidence_run_id=args.evidence_run_id, tencent_run_id=args.tencent_run_id,
        eastmoney_run_id=args.eastmoney_run_id, as_of_date=args.as_of_date,
        run_id=args.run_id, validate_only=args.validate_only, dry_run=args.dry_run,
        root=args.root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
