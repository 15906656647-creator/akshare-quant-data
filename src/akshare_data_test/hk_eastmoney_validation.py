"""Stage 17.6.2 isolated Eastmoney Hong Kong history validation."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .adapters.hk_market import HkMarketAdapter
from .paths import project_root
from .stage17_collect import _resolve_columns
from .stage17_hk_audit import ADJUSTMENTS, HK_SYMBOLS
from .stage17_hk_tencent_validation import (
    _quality,
    _relative,
    _sha256,
    _verify_listing_evidence,
)
from .storage.stage17_raw_store import Stage17RawStore


REPORT_COLUMNS = (
    "symbol", "adjust", "provider", "interface", "status", "call_status",
    "quality_status", "row_count", "source_row_count", "first_date", "last_date",
    "listing_date", "coverage_status", "future_date_count", "duplicate_date_count",
    "quality_errors", "attempt_count", "request_start_date", "request_end_date",
    "request_adjust", "data_path", "data_sha256", "source_response_path",
    "source_response_sha256", "error_type", "error_message",
)


def normalize_eastmoney_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename required columns without changing, sorting, dropping, or filling rows."""
    resolved, missing = _resolve_columns(frame)
    if missing:
        raise ValueError(f"stock_hk_hist missing required columns: {','.join(missing)}")
    return frame[[resolved[field] for field in ("date", "open", "high", "low", "close", "volume")]].rename(
        columns={resolved[field]: field for field in ("date", "open", "high", "low", "close", "volume")}
    ).copy()


def build_validation_plan(*, evidence_run_id: str, as_of_date: date) -> dict[str, Any]:
    return {
        "stage": 17, "task": "stage17_6_2_hk_eastmoney_validation",
        "evidence_run_id": evidence_run_id, "as_of_date": as_of_date.isoformat(),
        "symbols": list(HK_SYMBOLS), "adjustments": list(ADJUSTMENTS),
        "expected_dataset_count": 21, "provider": "eastmoney",
        "interface": "stock_hk_hist", "network_required_for_formal_mode": True,
        "stage17_formal_rerun": False, "provider_registry_built": False,
        "stage18_authorized": False,
    }


def _metadata(
    *, run_id: str, symbol: str, adjust: str, listing_date: date,
    as_of_date: date, frame_role: str, call: Any,
    quality: dict[str, Any] | None, fetched_at: datetime,
) -> dict[str, Any]:
    return {
        "stage": 17, "task": "stage17_6_2_hk_eastmoney_validation",
        "run_id": run_id, "provider": "eastmoney", "interface": "stock_hk_hist",
        "source_role": "validation_candidate", "frame_role": frame_role,
        "symbol": symbol, "source_symbol": symbol[:-3], "market": "HK",
        "exchange": "HKEX", "currency": "HKD", "timezone": "Asia/Hong_Kong",
        "adjust": adjust, "request_adjust": "" if adjust == "raw" else adjust,
        "request_start_date": listing_date.strftime("%Y%m%d"),
        "request_end_date": as_of_date.strftime("%Y%m%d"),
        "listing_date": listing_date.isoformat(), "as_of_date": as_of_date.isoformat(),
        "attempt_count": call.attempt_count, "call_status": call.status,
        "error_type": call.error_type, "error_message": call.error_message,
        "quality": quality, "fetched_at": fetched_at.isoformat(),
        "stage17_formal_dataset": False, "provider_registry_built": False,
        "stage18_authorized": False,
    }


def _register(
    *, result: dict[str, Any], dataset_id: str, root: Path,
    raw_files: list[dict[str, Any]],
) -> None:
    for role, key in (("data", "data_path"), ("metadata", "metadata_path")):
        path = Path(result[key])
        raw_files.append({
            "dataset_id": dataset_id, "role": role, "path": _relative(path, root),
            "size_bytes": path.stat().st_size, "sha256": _sha256(path),
        })


def _write_reports(
    *, root: Path, run_id: str, evidence_run_id: str, as_of_date: date,
    started_at: datetime, finished_at: datetime, records: list[dict[str, Any]],
    raw_files: list[dict[str, Any]], verified_evidence: list[dict[str, Any]],
) -> Path:
    reports_root = root / "reports" / "stage17_hk_eastmoney_validation"
    reports_root.mkdir(parents=True, exist_ok=True)
    target = reports_root / run_id
    if target.exists():
        raise FileExistsError(f"Eastmoney validation report already exists: {target}")
    temp = Path(tempfile.mkdtemp(prefix=f".stage17-hk-eastmoney-{run_id}-", dir=reports_root))
    try:
        csv_path = temp / "hk_eastmoney_validation.csv"
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        pass_count = sum(row["status"] == "PASS" for row in records)
        validation_status = "PASS" if pass_count == 21 else "BLOCKED"
        table_rows = "\n".join(
            f"| {row['symbol']} | {row['adjust']} | {row['status']} | {row['row_count']} | "
            f"{row['first_date'] or '-'} | {row['coverage_status'] or '-'} | "
            f"{row['quality_errors'] or row['error_type'] or '-'} |"
            for row in records
        )
        report = f"""# Stage 17.6.2 东方财富港股接口重新验证

验证批次：`{run_id}`
业务基准日：`{as_of_date.isoformat()}`
Provider：`eastmoney`
Interface：`stock_hk_hist`

## 结论

- Provider验证状态：`{validation_status}`（{pass_count}/21 PASS）。
- Stage 17正式状态仍为：`BLOCKED`。
- Stage 18授权：`false`。
- 本批只验证东方财富候选，不建设Provider Registry、不重跑正式Stage 17。

| symbol | adjust | status | rows | first_date | coverage | issue |
| --- | --- | --- | ---: | --- | --- | --- |
{table_rows}

## 判定规则

每项必须同时满足非空、OHLC包络合法、成交量非负、日期递增且唯一、无未来日期，以及
`complete_to_verified_listing_date`。连接失败、空结果、Schema错误和质量错误分别记录；
下载成功不等于质量通过。

原始AKShare DataFrame和只改列名的规范候选分别追加保存。验证过程不修改OHLC、不插值、
不删除异常日期，也不使用raw替代qfq/hfq。

## 下一门禁

即使东方财富21/21通过，也只具备进入后续Provider Registry任务的资格。本批不是69项
A/H日线与6项ETH的正式重跑，不能把Stage 17改为PASS，也不能授权Stage 18。
"""
        report_path = temp / "stage17_hk_eastmoney_validation.md"
        report_path.write_text(report, encoding="utf-8")
        manifest = {
            "stage": 17, "task": "stage17_6_2_hk_eastmoney_validation",
            "run_id": run_id, "evidence_run_id": evidence_run_id,
            "as_of_date": as_of_date.isoformat(), "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "provider": "eastmoney",
            "interface": "stock_hk_hist", "expected_dataset_count": 21,
            "quality_pass_count": pass_count, "validation_status": validation_status,
            "stage17_formal_status_before": "BLOCKED",
            "stage17_formal_status_after": "BLOCKED", "stage17_formal_rerun": False,
            "provider_registry_built": False, "stage18_authorized": False,
            "raw_manifest_closed_world": True, "raw_files": raw_files,
            "datasets": records, "verified_listing_evidence": verified_evidence,
            "outputs": [
                {
                    "path": (target / path.name).relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size, "sha256": _sha256(path),
                }
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


def run_eastmoney_validation(
    *, evidence_run_id: str, as_of_date: date, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False, root: Path | None = None,
    adapter: HkMarketAdapter | None = None,
) -> dict[str, Any]:
    if validate_only and dry_run:
        raise ValueError("validate_only and dry_run are mutually exclusive")
    root = (root or project_root()).resolve()
    uuid.UUID(evidence_run_id)
    listing_dates, evidence, _, _ = _verify_listing_evidence(
        root=root, evidence_run_id=evidence_run_id, as_of_date=as_of_date,
    )
    plan = build_validation_plan(evidence_run_id=evidence_run_id, as_of_date=as_of_date)
    if validate_only:
        return {**plan, "mode": "validate_only", "network_calls": 0, "outputs_written": False}
    if dry_run:
        return {**plan, "mode": "dry_run", "network_calls": 0, "outputs_written": False}
    if run_id is None:
        raise ValueError("Formal Eastmoney validation requires an explicit run_id")
    uuid.UUID(run_id)
    raw_root = root / "data" / "raw" / "stage17"
    target_report = root / "reports" / "stage17_hk_eastmoney_validation" / run_id
    if target_report.exists() or any(raw_root.rglob(f"run_id={run_id}")):
        raise FileExistsError(f"Eastmoney validation run_id already exists: {run_id}")
    adapter = adapter or HkMarketAdapter()
    store = Stage17RawStore(raw_root)
    started_at = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    raw_files: list[dict[str, Any]] = []
    for symbol in HK_SYMBOLS:
        for adjust in ADJUSTMENTS:
            listing = listing_dates[symbol]
            start = listing.strftime("%Y%m%d")
            end = as_of_date.strftime("%Y%m%d")
            fetched_at = datetime.now(timezone.utc)
            call = adapter.fetch_history(
                symbol=symbol, start_date=start, end_date=end,
                adjust="" if adjust == "raw" else adjust,
            )
            source_result: dict[str, Any] | None = None
            candidate_result: dict[str, Any] | None = None
            candidate: pd.DataFrame | None = None
            quality: dict[str, Any] | None = None
            normalization_error = ""
            if call.dataframe is not None and not call.dataframe.empty:
                source_dir = store.dataset_dir(
                    dataset="hk_eastmoney_source_response", run_id=run_id, market="HK",
                    symbol=symbol, adjust=adjust, source="eastmoney",
                )
                source_result = store.write_dataset(
                    call.dataframe, source_dir,
                    _metadata(
                        run_id=run_id, symbol=symbol, adjust=adjust, listing_date=listing,
                        as_of_date=as_of_date, frame_role="source_response", call=call,
                        quality=None, fetched_at=fetched_at,
                    ),
                )
                _register(
                    result=source_result, dataset_id=f"eastmoney:{symbol}:{adjust}:source",
                    root=root, raw_files=raw_files,
                )
                try:
                    candidate = normalize_eastmoney_history(call.dataframe)
                except ValueError as exc:
                    normalization_error = str(exc)
            if call.status == "success" and candidate is not None:
                quality = _quality(candidate, listing_date=listing, as_of_date=as_of_date)
                candidate_dir = store.dataset_dir(
                    dataset="hk_eastmoney_candidate", run_id=run_id, market="HK",
                    symbol=symbol, adjust=adjust, source="eastmoney",
                )
                candidate_result = store.write_dataset(
                    candidate, candidate_dir,
                    _metadata(
                        run_id=run_id, symbol=symbol, adjust=adjust, listing_date=listing,
                        as_of_date=as_of_date, frame_role="normalized_candidate", call=call,
                        quality=quality, fetched_at=fetched_at,
                    ),
                )
                _register(
                    result=candidate_result,
                    dataset_id=f"eastmoney:{symbol}:{adjust}:candidate",
                    root=root, raw_files=raw_files,
                )
            passed = call.status == "success" and quality is not None and quality["status"] == "PASS"
            records.append({
                "symbol": symbol, "adjust": adjust, "provider": "eastmoney",
                "interface": "stock_hk_hist", "status": "PASS" if passed else "FAIL",
                "call_status": call.status,
                "quality_status": quality["status"] if quality else "NOT_RUN",
                "row_count": len(candidate) if candidate is not None else 0,
                "source_row_count": len(call.dataframe) if call.dataframe is not None else 0,
                "first_date": quality.get("min_date") if quality else None,
                "last_date": quality.get("max_date") if quality else None,
                "listing_date": listing.isoformat(),
                "coverage_status": quality.get("coverage_status") if quality else "history_unavailable",
                "future_date_count": quality.get("future_date_count") if quality else None,
                "duplicate_date_count": quality.get("duplicate_date_count") if quality else None,
                "quality_errors": "|".join(quality.get("errors", [])) if quality else "",
                "attempt_count": call.attempt_count, "request_start_date": start,
                "request_end_date": end, "request_adjust": "" if adjust == "raw" else adjust,
                "data_path": _relative(Path(candidate_result["data_path"]), root) if candidate_result else "",
                "data_sha256": candidate_result.get("data_sha256", "") if candidate_result else "",
                "source_response_path": _relative(Path(source_result["data_path"]), root) if source_result else "",
                "source_response_sha256": source_result.get("data_sha256", "") if source_result else "",
                "error_type": "unexpected_schema" if normalization_error else call.error_type,
                "error_message": normalization_error or call.error_message,
            })
            time.sleep(0.15)
    finished_at = datetime.now(timezone.utc)
    report_dir = _write_reports(
        root=root, run_id=run_id, evidence_run_id=evidence_run_id,
        as_of_date=as_of_date, started_at=started_at, finished_at=finished_at,
        records=records, raw_files=raw_files, verified_evidence=evidence,
    )
    pass_count = sum(row["status"] == "PASS" for row in records)
    return {
        "mode": "formal_validation", "run_id": run_id,
        "validation_status": "PASS" if pass_count == 21 else "BLOCKED",
        "quality_pass_count": pass_count, "expected_dataset_count": 21,
        "report_dir": str(report_dir), "stage17_formal_status": "BLOCKED",
        "stage17_formal_rerun": False, "provider_registry_built": False,
        "stage18_authorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Revalidate Eastmoney HK daily history")
    parser.add_argument("--evidence-run-id", required=True)
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    parser.add_argument("--run-id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_eastmoney_validation(
        evidence_run_id=args.evidence_run_id, as_of_date=args.as_of_date,
        run_id=args.run_id, validate_only=args.validate_only, dry_run=args.dry_run,
        root=args.root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
