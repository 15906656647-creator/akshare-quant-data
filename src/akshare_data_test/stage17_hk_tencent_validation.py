"""Stage 17.6.1 isolated Tencent Hong Kong provider validation."""
from __future__ import annotations

import argparse
import csv
import hashlib
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

from .adapters.hk_tencent_adapter import HkTencentAdapter
from .paths import project_root
from .stage17_collect import listing_coverage_status, validate_equity_daily
from .stage17_hk_audit import ADJUSTMENTS, HK_SYMBOLS
from .storage.stage17_raw_store import Stage17RawStore


REPORT_COLUMNS = (
    "symbol", "adjust", "provider", "interface", "status", "call_status",
    "quality_status", "row_count", "source_row_count", "first_date", "last_date",
    "listing_date", "coverage_status", "future_date_count", "duplicate_date_count",
    "quality_errors", "attempt_count", "requested_blocks", "duplicate_rows_removed",
    "data_path", "data_sha256", "source_response_path", "source_response_sha256",
    "error_type", "error_message",
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


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _verify_listing_evidence(
    *, root: Path, evidence_run_id: str, as_of_date: date,
) -> tuple[dict[str, date], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    report_dir = root / "reports" / "stage17" / evidence_run_id
    manifest_path = report_dir / "stage17_manifest.json"
    run_path = report_dir / "stage17_run.json"
    manifest = _load_json(manifest_path)
    run = _load_json(run_path)
    if manifest.get("stage") != 17 or manifest.get("run_id") != evidence_run_id:
        raise ValueError("Stage 17 evidence manifest identity mismatch")
    if manifest.get("as_of_date") != as_of_date.isoformat():
        raise ValueError("Explicit as_of_date does not match Stage 17 evidence")
    if run.get("status") != "BLOCKED" or run.get("stage18_authorized") is not False:
        raise ValueError("Tencent validation requires BLOCKED Stage 17 evidence")
    raw_index = {
        (row.get("path"), row.get("role")): row
        for row in manifest.get("raw_files", [])
    }
    profiles = {
        row.get("symbol"): row for row in manifest.get("datasets", [])
        if row.get("market") == "HK" and row.get("kind") == "equity_profile"
    }
    if set(profiles) != set(HK_SYMBOLS):
        raise ValueError("Stage 17 evidence must contain all seven HK profiles")
    listing_dates: dict[str, date] = {}
    verified: list[dict[str, Any]] = []
    for symbol in HK_SYMBOLS:
        row = profiles[symbol]
        if row.get("quality_status") != "PASS" or not row.get("listing_date"):
            raise ValueError(f"Missing verified listing evidence for {symbol}")
        listing_dates[symbol] = date.fromisoformat(row["listing_date"])
        for role, path_key, hash_key in (
            ("data", "data_path", "data_sha256"),
            ("metadata", "metadata_path", "metadata_sha256"),
        ):
            relative = row.get(path_key)
            expected = row.get(hash_key)
            registered = raw_index.get((relative, role))
            path = root / str(relative)
            if not relative or not expected or registered is None:
                raise ValueError(f"Incomplete listing evidence for {symbol}:{role}")
            actual = _sha256(path)
            if actual != expected or registered.get("sha256") != expected:
                raise ValueError(f"Listing evidence hash mismatch: {relative}")
            verified.append({
                "symbol": symbol, "role": role, "path": relative,
                "size_bytes": path.stat().st_size, "sha256": actual,
            })
    return listing_dates, verified, manifest, run


def build_validation_plan(*, evidence_run_id: str, as_of_date: date) -> dict[str, Any]:
    return {
        "stage": 17, "task": "stage17_6_1_hk_tencent_validation",
        "evidence_run_id": evidence_run_id, "as_of_date": as_of_date.isoformat(),
        "symbols": list(HK_SYMBOLS), "adjustments": list(ADJUSTMENTS),
        "expected_dataset_count": len(HK_SYMBOLS) * len(ADJUSTMENTS),
        "provider": "tencent", "interface": "stock_zh_ah_daily",
        "network_required_for_formal_mode": True,
        "stage17_formal_rerun": False, "stage18_authorized": False,
    }


def _metadata(
    *, run_id: str, symbol: str, adjust: str, listing_date: date,
    as_of_date: date, frame_role: str, call: Any, quality: dict[str, Any] | None,
    fetched_at: datetime,
) -> dict[str, Any]:
    return {
        "stage": 17, "task": "stage17_6_1_hk_tencent_validation",
        "run_id": run_id, "provider": "tencent", "interface": "stock_zh_ah_daily",
        "source_role": "validation_candidate", "frame_role": frame_role,
        "symbol": symbol, "source_symbol": symbol[:-3], "market": "HK",
        "exchange": "HKEX", "currency": "HKD", "timezone": "Asia/Hong_Kong",
        "adjust": adjust, "request_adjust": "" if adjust == "raw" else adjust,
        "listing_date": listing_date.isoformat(), "as_of_date": as_of_date.isoformat(),
        "requested_year_blocks": list(call.requested_blocks),
        "attempt_count": call.attempt_count,
        "duplicate_rows_removed_from_candidate": call.duplicate_rows_removed,
        "call_status": call.status, "quality": quality,
        "fetched_at": fetched_at.isoformat(),
        "stage17_formal_dataset": False, "stage18_authorized": False,
    }


def _add_raw_files(
    *, result: dict[str, Any], dataset_id: str, root: Path,
    raw_files: list[dict[str, Any]],
) -> None:
    for role, key in (("data", "data_path"), ("metadata", "metadata_path")):
        path = Path(result[key])
        raw_files.append({
            "dataset_id": dataset_id, "role": role, "path": _relative(path, root),
            "size_bytes": path.stat().st_size, "sha256": _sha256(path),
        })


def _quality(
    frame: pd.DataFrame, *, listing_date: date, as_of_date: date,
) -> dict[str, Any]:
    result = validate_equity_daily(frame)
    errors = list(result.get("errors", []))
    dates = pd.to_datetime(frame["date"], errors="coerce")
    future_count = int((dates > pd.Timestamp(as_of_date)).sum())
    if future_count:
        errors.append("future_trade_date")
    coverage = listing_coverage_status(listing_date, result.get("min_date"))
    if coverage != "complete_to_verified_listing_date":
        errors.append(coverage)
    return {
        **result, "status": "PASS" if not errors else "FAIL", "errors": errors,
        "future_date_count": future_count, "coverage_status": coverage,
        "duplicate_date_count": int(dates.duplicated().sum()),
    }


def _write_reports(
    *, root: Path, run_id: str, evidence_run_id: str, as_of_date: date,
    started_at: datetime, finished_at: datetime, records: list[dict[str, Any]],
    raw_files: list[dict[str, Any]], verified_evidence: list[dict[str, Any]],
    evidence_manifest: dict[str, Any], evidence_run: dict[str, Any],
) -> Path:
    reports_root = root / "reports" / "stage17_hk_tencent_validation"
    reports_root.mkdir(parents=True, exist_ok=True)
    target = reports_root / run_id
    if target.exists():
        raise FileExistsError(f"Tencent validation report already exists: {target}")
    temp = Path(tempfile.mkdtemp(prefix=f".stage17-hk-tencent-{run_id}-", dir=reports_root))
    try:
        csv_path = temp / "hk_tencent_validation.csv"
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        pass_count = sum(row["status"] == "PASS" for row in records)
        validation_status = "PASS" if pass_count == len(records) else "BLOCKED"
        table_rows = "\n".join(
            f"| {row['symbol']} | {row['adjust']} | {row['status']} | "
            f"{row['row_count']} | {row['first_date'] or '-'} | "
            f"{row['coverage_status'] or '-'} | {row['quality_errors'] or row['error_type'] or '-'} |"
            for row in records
        )
        report = f"""# Stage 17.6.1 腾讯港股接口验证

> 验证批次：`{run_id}`
> 业务基准日：`{as_of_date.isoformat()}`
> Provider：`tencent`
> Interface：`stock_zh_ah_daily`

## 结论

- Provider验证状态：`{validation_status}`（{pass_count}/{len(records)} PASS）。
- Stage 17正式状态仍为：`BLOCKED`。
- Stage 18授权：`false`。
- 本批只验证腾讯候选，不拼接旧Raw、不替换正式69项、不重跑Stage 17。

| symbol | adjust | status | rows | first_date | coverage | issue |
| --- | --- | --- | ---: | --- | --- | --- |
{table_rows}

## 判定规则

每项必须同时满足：非空、日期递增且唯一、无未来日期、OHLC包络合法、成交量非负，以及
最早记录覆盖到已有上市日期证据对应的首个交易区间。下载成功不等于质量通过。

AKShare接口按相邻年份产生重叠响应时，仅允许删除所有字段完全相同的重复日期，并同时
保存未去重`source_response`和去重数量；同日值冲突时直接失败。任何价格值均不修改、
不插值、不截断异常行。

## 下一门禁

即使腾讯21/21通过，也只能说明该候选具备进入正式Stage 17完整新批次的资格。必须另行
使用全新run_id完整重跑69项A/H日线、6项ETH及清单覆盖门禁，正式Stage 17达到`PASS`
后才能授权Stage 18。本任务不执行该重跑。
"""
        report_path = temp / "stage17_hk_tencent_validation.md"
        report_path.write_text(report, encoding="utf-8")
        manifest = {
            "stage": 17, "task": "stage17_6_1_hk_tencent_validation",
            "run_id": run_id, "evidence_run_id": evidence_run_id,
            "as_of_date": as_of_date.isoformat(), "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "provider": "tencent",
            "interface": "stock_zh_ah_daily", "expected_dataset_count": 21,
            "quality_pass_count": pass_count, "validation_status": validation_status,
            "stage17_formal_status_before": "BLOCKED",
            "stage17_formal_status_after": "BLOCKED", "stage17_formal_rerun": False,
            "stage18_authorized": False, "raw_manifest_closed_world": True,
            "raw_files": raw_files, "datasets": records,
            "verified_listing_evidence": verified_evidence,
            "evidence_manifest_sha256": hashlib.sha256(
                json.dumps(evidence_manifest, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "evidence_run_status": evidence_run.get("status"),
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return target


def run_tencent_validation(
    *, evidence_run_id: str, as_of_date: date, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False, root: Path | None = None,
    adapter: HkTencentAdapter | None = None,
) -> dict[str, Any]:
    if validate_only and dry_run:
        raise ValueError("validate_only and dry_run are mutually exclusive")
    root = (root or project_root()).resolve()
    uuid.UUID(evidence_run_id)
    listing_dates, evidence, evidence_manifest, evidence_run = _verify_listing_evidence(
        root=root, evidence_run_id=evidence_run_id, as_of_date=as_of_date,
    )
    plan = build_validation_plan(evidence_run_id=evidence_run_id, as_of_date=as_of_date)
    if validate_only:
        return {**plan, "mode": "validate_only", "network_calls": 0, "outputs_written": False}
    if dry_run:
        return {**plan, "mode": "dry_run", "network_calls": 0, "outputs_written": False}
    if run_id is None:
        raise ValueError("Formal Tencent validation requires an explicit run_id")
    uuid.UUID(run_id)
    raw_run_root = root / "data" / "raw" / "stage17"
    report_target = root / "reports" / "stage17_hk_tencent_validation" / run_id
    if report_target.exists() or any(raw_run_root.rglob(f"run_id={run_id}")):
        raise FileExistsError(f"Tencent validation run_id already exists: {run_id}")
    adapter = adapter or HkTencentAdapter()
    store = Stage17RawStore(raw_run_root)
    started_at = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    raw_files: list[dict[str, Any]] = []
    for symbol in HK_SYMBOLS:
        for adjust in ADJUSTMENTS:
            fetched_at = datetime.now(timezone.utc)
            call = adapter.fetch_history(
                symbol=symbol, listing_date=listing_dates[symbol],
                as_of_date=as_of_date, adjust=adjust,
            )
            source_result: dict[str, Any] | None = None
            candidate_result: dict[str, Any] | None = None
            quality: dict[str, Any] | None = None
            if call.source_frame is not None and not call.source_frame.empty:
                source_dir = store.dataset_dir(
                    dataset="hk_tencent_source_response", run_id=run_id, market="HK",
                    symbol=symbol, adjust=adjust, source="tencent",
                )
                source_result = store.write_dataset(
                    call.source_frame, source_dir,
                    _metadata(
                        run_id=run_id, symbol=symbol, adjust=adjust,
                        listing_date=listing_dates[symbol], as_of_date=as_of_date,
                        frame_role="source_response", call=call, quality=None,
                        fetched_at=fetched_at,
                    ),
                )
                _add_raw_files(
                    result=source_result, dataset_id=f"tencent:{symbol}:{adjust}:source",
                    root=root, raw_files=raw_files,
                )
            if call.status == "success" and call.dataframe is not None:
                quality = _quality(
                    call.dataframe, listing_date=listing_dates[symbol],
                    as_of_date=as_of_date,
                )
                candidate_dir = store.dataset_dir(
                    dataset="hk_tencent_candidate", run_id=run_id, market="HK",
                    symbol=symbol, adjust=adjust, source="tencent",
                )
                candidate_result = store.write_dataset(
                    call.dataframe, candidate_dir,
                    _metadata(
                        run_id=run_id, symbol=symbol, adjust=adjust,
                        listing_date=listing_dates[symbol], as_of_date=as_of_date,
                        frame_role="normalized_candidate", call=call, quality=quality,
                        fetched_at=fetched_at,
                    ),
                )
                _add_raw_files(
                    result=candidate_result,
                    dataset_id=f"tencent:{symbol}:{adjust}:candidate",
                    root=root, raw_files=raw_files,
                )
            passed = call.status == "success" and quality is not None and quality["status"] == "PASS"
            records.append({
                "symbol": symbol, "adjust": adjust, "provider": "tencent",
                "interface": "stock_zh_ah_daily", "status": "PASS" if passed else "FAIL",
                "call_status": call.status,
                "quality_status": quality["status"] if quality else "NOT_RUN",
                "row_count": len(call.dataframe) if call.dataframe is not None else 0,
                "source_row_count": len(call.source_frame) if call.source_frame is not None else 0,
                "first_date": quality.get("min_date") if quality else None,
                "last_date": quality.get("max_date") if quality else None,
                "listing_date": listing_dates[symbol].isoformat(),
                "coverage_status": quality.get("coverage_status") if quality else "history_unavailable",
                "future_date_count": quality.get("future_date_count") if quality else None,
                "duplicate_date_count": quality.get("duplicate_date_count") if quality else None,
                "quality_errors": "|".join(quality.get("errors", [])) if quality else "",
                "attempt_count": call.attempt_count,
                "requested_blocks": "|".join(map(str, call.requested_blocks)),
                "duplicate_rows_removed": call.duplicate_rows_removed,
                "data_path": _relative(Path(candidate_result["data_path"]), root) if candidate_result else "",
                "data_sha256": candidate_result.get("data_sha256", "") if candidate_result else "",
                "source_response_path": _relative(Path(source_result["data_path"]), root) if source_result else "",
                "source_response_sha256": source_result.get("data_sha256", "") if source_result else "",
                "error_type": call.error_type, "error_message": call.error_message,
            })
            time.sleep(0.15)
    finished_at = datetime.now(timezone.utc)
    report_dir = _write_reports(
        root=root, run_id=run_id, evidence_run_id=evidence_run_id,
        as_of_date=as_of_date, started_at=started_at, finished_at=finished_at,
        records=records, raw_files=raw_files, verified_evidence=evidence,
        evidence_manifest=evidence_manifest, evidence_run=evidence_run,
    )
    pass_count = sum(row["status"] == "PASS" for row in records)
    return {
        "mode": "formal_validation", "run_id": run_id,
        "validation_status": "PASS" if pass_count == 21 else "BLOCKED",
        "quality_pass_count": pass_count, "expected_dataset_count": 21,
        "report_dir": str(report_dir), "stage17_formal_status": "BLOCKED",
        "stage17_formal_rerun": False, "stage18_authorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Tencent HK daily history")
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
    result = run_tencent_validation(
        evidence_run_id=args.evidence_run_id, as_of_date=args.as_of_date,
        run_id=args.run_id, validate_only=args.validate_only, dry_run=args.dry_run,
        root=args.root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
