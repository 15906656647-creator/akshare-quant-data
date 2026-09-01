"""Stage 17.6.6 isolated Tencent recovery for 09669.HK."""
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

from .adapters.hk_tencent_direct import HkTencentDirectAdapter
from .paths import project_root
from .stage17_hk_tencent_validation import _quality, _relative, _sha256, _verify_listing_evidence
from .storage.stage17_raw_store import Stage17RawStore


SYMBOL = "09669.HK"
LISTING_DATE = date(2023, 4, 13)
AS_OF_DATE = date(2026, 8, 24)
ADJUSTMENTS = ("raw", "qfq", "hfq")
REPORT_COLUMNS = (
    "symbol", "adjust", "status", "call_status", "quality_status", "row_count",
    "source_row_count", "first_date", "last_date", "coverage_status",
    "requested_blocks", "used_response_keys", "field_fallback",
    "duplicate_rows_removed", "qfq_hfq_identical", "quality_errors",
    "attempt_count", "data_path", "data_sha256", "metadata_path",
    "metadata_sha256", "error_type", "error_message",
)


def build_recovery_plan(*, evidence_run_id: str, as_of_date: date) -> dict[str, Any]:
    if as_of_date != AS_OF_DATE:
        raise ValueError("Stage 17.6.6 requires as_of_date 2026-08-24")
    return {
        "stage": 17, "task": "stage17_6_6_09669_tencent_recovery",
        "evidence_run_id": evidence_run_id, "symbol": SYMBOL,
        "listing_date": LISTING_DATE.isoformat(), "as_of_date": as_of_date.isoformat(),
        "adjustments": list(ADJUSTMENTS), "request_blocks": [2023, 2025],
        "provider": "tencent", "interface": "direct_https",
        "network_required_for_formal_mode": True, "stage17_formal_rerun": False,
        "stage17_formal_status": "BLOCKED", "stage18_authorized": False,
        "provider_registry_built": False,
    }


def _atomic_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"Immutable response already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the sibling temporary name short for Windows MAX_PATH test roots.
    temporary = path.with_name(".tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary response already exists: {temporary}")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    _atomic_bytes(path, encoded)


def _register(path: Path, *, root: Path, dataset_id: str, role: str) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id, "role": role, "path": _relative(path, root),
        "size_bytes": path.stat().st_size, "sha256": _sha256(path),
    }


def _strict_quality(frame: pd.DataFrame) -> dict[str, Any]:
    quality = _quality(frame, listing_date=LISTING_DATE, as_of_date=AS_OF_DATE)
    errors = list(quality["errors"])
    if len(frame) != 829:
        errors.append("unexpected_row_count")
    if quality.get("min_date") != LISTING_DATE.isoformat():
        errors.append("unexpected_first_date")
    if quality.get("max_date") != AS_OF_DATE.isoformat():
        errors.append("unexpected_last_date")
    return {**quality, "status": "PASS" if not errors else "FAIL", "errors": errors}


def _candidate_metadata(
    *, run_id: str, adjust: str, call: Any, quality: dict[str, Any],
    qfq_hfq_identical: bool,
) -> dict[str, Any]:
    return {
        "stage": 17, "task": "stage17_6_6_09669_tencent_recovery",
        "run_id": run_id, "provider": "tencent", "interface": "direct_https",
        "source_role": "validation_candidate", "stage17_formal_dataset": False,
        "symbol": SYMBOL, "source_symbol": "09669", "market": "HK",
        "exchange": "HKEX", "currency": "HKD", "timezone": "Asia/Hong_Kong",
        "adjust": adjust, "provider_adjust_semantics": (
            "Tencent raw daily request" if adjust == "raw"
            else f"Tencent endpoint explicitly requested {adjust}"
        ),
        "listing_date": LISTING_DATE.isoformat(), "as_of_date": AS_OF_DATE.isoformat(),
        "requested_year_blocks": [block.year for block in call.blocks],
        "requested_response_keys": [block.requested_key for block in call.blocks],
        "used_response_keys": [block.used_key for block in call.blocks],
        "response_field_fallback": any(block.field_fallback for block in call.blocks),
        "response_field_fallback_reason": (
            "AKShare 1.18.80 expects qfqday/hfqday; Tencent returned day"
            if any(block.field_fallback for block in call.blocks) else ""
        ),
        "source_row_count": len(call.source_frame),
        "duplicate_rows_removed": call.duplicate_rows_removed,
        "filtered_candidate_row_count": len(call.dataframe),
        "qfq_hfq_identical": qfq_hfq_identical,
        "qfq_hfq_identical_is_failure": False,
        "quality": quality, "call_status": call.status,
        "stage17_formal_status": "BLOCKED", "stage18_authorized": False,
        "provider_registry_built": False,
    }


def _write_reports(
    *, root: Path, run_id: str, evidence_run_id: str, records: list[dict[str, Any]],
    raw_files: list[dict[str, Any]], verified_evidence: list[dict[str, Any]],
    started_at: str, finished_at: str, qfq_hfq_identical: bool,
) -> Path:
    base = root / "reports" / "stage17_hk_09669_tencent_recovery"
    base.mkdir(parents=True, exist_ok=True)
    target = base / run_id
    if target.exists():
        raise FileExistsError(f"Recovery report already exists: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=f".stage17-09669-{run_id}-", dir=base))
    try:
        csv_path = temporary / "09669_tencent_recovery.csv"
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        pass_count = sum(record["status"] == "PASS" for record in records)
        status = "PASS" if pass_count == 3 else "BLOCKED"
        rows = "\n".join(
            f"| {row['adjust']} | {row['status']} | {row['row_count']} | "
            f"{row['first_date'] or '-'} | {row['last_date'] or '-'} | "
            f"{row['used_response_keys'] or '-'} | {row['duplicate_rows_removed']} |"
            for row in records
        )
        report = f"""# Stage 17.6.6：09669.HK 腾讯复权兼容采集验证

> 专项批次：`{run_id}`
> 业务基准日：`{AS_OF_DATE.isoformat()}`
> Provider：`tencent`（HTTPS直连）

## 结论

- 专项候选状态：`{status}`（{pass_count}/3 PASS）。
- 若为3/3 PASS，港股专项候选覆盖达到`21/21`；这不是Stage 17正式验收。
- Stage 17正式状态保持：`BLOCKED`；Stage 18授权：`false`。
- Provider Registry：未建设；未拼接或修改任何既有正式批次。

| adjust | status | rows | first_date | last_date | response keys | exact duplicates removed |
| --- | --- | ---: | --- | --- | --- | ---: |
{rows}

## 兼容与复权语义披露

调整端点分别显式请求`qfq`和`hfq`。响应未提供AKShare 1.18.80预期的
`qfqday/hfqday`字段时，本专项兼容读取Provider实际返回的`day`字段，并在每个请求块及
候选metadata中记录回退。qfq与hfq规范候选当前完全相同：
`{str(qfq_hfq_identical).lower()}`。依照本专项已批准口径，该事实必须披露但不自动判失败。

候选层只过滤已核验上市日到业务基准日区间；只删除跨请求块所有字段完全相同的重复日。
冲突重复、OHLC异常、身份错配、缺字段或覆盖不足均直接失败，未修改任何价格。

## 后续门禁

本专项成功后仍需另行建设Stage 17.7 Provider Registry并以全新run_id完整重跑Stage 17。
只有正式69/69 A/H日线、6/6 ETH及全部审计门禁通过，Stage 17才可变更为PASS并授权Stage 18。
"""
        md_path = temporary / "09669_validation.md"
        md_path.write_text(report, encoding="utf-8")
        manifest = {
            "stage": 17, "task": "stage17_6_6_09669_tencent_recovery",
            "run_id": run_id, "evidence_run_id": evidence_run_id,
            "symbol": SYMBOL, "listing_date": LISTING_DATE.isoformat(),
            "as_of_date": AS_OF_DATE.isoformat(), "started_at": started_at,
            "finished_at": finished_at, "provider": "tencent",
            "interface": "direct_https", "expected_dataset_count": 3,
            "quality_pass_count": pass_count, "validation_status": status,
            "qfq_hfq_identical": qfq_hfq_identical,
            "qfq_hfq_identical_is_failure": False,
            "candidate_hk_coverage_after_success": "21/21" if pass_count == 3 else "below_21/21",
            "stage17_formal_status_before": "BLOCKED",
            "stage17_formal_status_after": "BLOCKED", "stage17_formal_rerun": False,
            "stage18_authorized": False, "provider_registry_built": False,
            "raw_manifest_closed_world": True,
            "raw_files": raw_files, "datasets": records,
            "verified_listing_evidence": verified_evidence,
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def run_tencent_recovery(
    *, evidence_run_id: str, as_of_date: date, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False, root: Path | None = None,
    adapter: HkTencentDirectAdapter | None = None,
) -> dict[str, Any]:
    if validate_only and dry_run:
        raise ValueError("validate_only and dry_run are mutually exclusive")
    root = (root or project_root()).resolve()
    uuid.UUID(evidence_run_id)
    listing_dates, evidence, _, _ = _verify_listing_evidence(
        root=root, evidence_run_id=evidence_run_id, as_of_date=as_of_date,
    )
    if listing_dates.get(SYMBOL) != LISTING_DATE:
        raise ValueError("Verified 09669.HK listing date must be 2023-04-13")
    plan = build_recovery_plan(evidence_run_id=evidence_run_id, as_of_date=as_of_date)
    if validate_only:
        return {**plan, "mode": "validate_only", "network_calls": 0, "outputs_written": False}
    if dry_run:
        return {**plan, "mode": "dry_run", "network_calls": 0, "outputs_written": False}
    if run_id is None:
        raise ValueError("Formal recovery requires an explicit run_id")
    uuid.UUID(run_id)
    raw_root = root / "data" / "raw" / "stage17"
    report_target = root / "reports" / "stage17_hk_09669_tencent_recovery" / run_id
    if report_target.exists() or any(raw_root.rglob(f"run_id={run_id}")):
        raise FileExistsError(f"Recovery run_id already exists: {run_id}")
    adapter = adapter or HkTencentDirectAdapter()
    started_at = datetime.now(timezone.utc).isoformat()
    calls = {
        adjust: adapter.fetch_history(
            symbol=SYMBOL, listing_date=LISTING_DATE, as_of_date=as_of_date, adjust=adjust,
        )
        for adjust in ADJUSTMENTS
    }
    qfq = calls["qfq"].dataframe
    hfq = calls["hfq"].dataframe
    identical = bool(qfq is not None and hfq is not None and qfq.equals(hfq))
    store = Stage17RawStore(raw_root)
    raw_files: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for adjust, call in calls.items():
        for block in call.blocks:
            if block.raw_response is None:
                continue
            directory = (
                raw_root / "hk_tencent_recovery_source_response" / f"run_id={run_id}"
                / "market=HK" / f"symbol={SYMBOL}" / f"adjust={adjust}"
                / f"block={block.year}" / "source=tencent"
            )
            response_path = directory / "response.txt"
            metadata_path = directory / "metadata.json"
            _atomic_bytes(response_path, block.raw_response)
            response_hash = _sha256(response_path)
            _atomic_json(metadata_path, {
                "stage": 17, "task": "stage17_6_6_09669_tencent_recovery",
                "run_id": run_id, "provider": "tencent", "interface": "direct_https",
                "symbol": SYMBOL, "adjust": adjust, "block": block.year,
                "request_url": block.request_url, "request_params": block.request_params,
                "requested_at": block.requested_at, "completed_at": block.completed_at,
                "attempt_count": block.attempt_count, "http_status": block.http_status,
                "requested_response_key": block.requested_key,
                "used_response_key": block.used_key,
                "response_field_fallback": block.field_fallback,
                "source_row_count": len(block.source_frame) if block.source_frame is not None else 0,
                "raw_response_sha256": response_hash,
                "stage17_formal_dataset": False, "stage18_authorized": False,
            })
            dataset_id = f"tencent-recovery:{SYMBOL}:{adjust}:block:{block.year}"
            raw_files.extend((
                _register(response_path, root=root, dataset_id=dataset_id, role="source_response"),
                _register(metadata_path, root=root, dataset_id=dataset_id, role="source_metadata"),
            ))
        quality = _strict_quality(call.dataframe) if call.dataframe is not None else None
        candidate_result: dict[str, Any] | None = None
        if call.status == "success" and call.dataframe is not None:
            directory = store.dataset_dir(
                dataset="hk_tencent_recovery_candidate", run_id=run_id, market="HK",
                symbol=SYMBOL, adjust=adjust, source="tencent",
            )
            candidate_result = store.write_dataset(
                call.dataframe, directory,
                _candidate_metadata(
                    run_id=run_id, adjust=adjust, call=call, quality=quality,
                    qfq_hfq_identical=identical,
                ),
            )
            dataset_id = f"tencent-recovery:{SYMBOL}:{adjust}:candidate"
            for role, key in (("candidate", "data_path"), ("candidate_metadata", "metadata_path")):
                raw_files.append(_register(
                    Path(candidate_result[key]), root=root, dataset_id=dataset_id, role=role,
                ))
        passed = call.status == "success" and quality is not None and quality["status"] == "PASS"
        records.append({
            "symbol": SYMBOL, "adjust": adjust, "status": "PASS" if passed else "FAIL",
            "call_status": call.status,
            "quality_status": quality["status"] if quality else "NOT_RUN",
            "row_count": len(call.dataframe) if call.dataframe is not None else 0,
            "source_row_count": len(call.source_frame) if call.source_frame is not None else 0,
            "first_date": quality.get("min_date") if quality else "",
            "last_date": quality.get("max_date") if quality else "",
            "coverage_status": quality.get("coverage_status") if quality else "history_unavailable",
            "requested_blocks": "|".join(str(block.year) for block in call.blocks),
            "used_response_keys": "|".join(block.used_key for block in call.blocks),
            "field_fallback": any(block.field_fallback for block in call.blocks),
            "duplicate_rows_removed": call.duplicate_rows_removed,
            "qfq_hfq_identical": identical,
            "quality_errors": "|".join(quality.get("errors", [])) if quality else "",
            "attempt_count": call.attempt_count,
            "data_path": _relative(Path(candidate_result["data_path"]), root) if candidate_result else "",
            "data_sha256": candidate_result.get("data_sha256", "") if candidate_result else "",
            "metadata_path": _relative(Path(candidate_result["metadata_path"]), root) if candidate_result else "",
            "metadata_sha256": _sha256(Path(candidate_result["metadata_path"])) if candidate_result else "",
            "error_type": call.error_type, "error_message": call.error_message,
        })
    finished_at = datetime.now(timezone.utc).isoformat()
    report_dir = _write_reports(
        root=root, run_id=run_id, evidence_run_id=evidence_run_id, records=records,
        raw_files=raw_files, verified_evidence=evidence, started_at=started_at,
        finished_at=finished_at, qfq_hfq_identical=identical,
    )
    pass_count = sum(record["status"] == "PASS" for record in records)
    return {
        "mode": "formal_recovery", "run_id": run_id,
        "validation_status": "PASS" if pass_count == 3 else "BLOCKED",
        "quality_pass_count": pass_count, "expected_dataset_count": 3,
        "qfq_hfq_identical": identical, "report_dir": str(report_dir),
        "stage17_formal_status": "BLOCKED", "stage18_authorized": False,
        "provider_registry_built": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover 09669.HK Tencent adjusted candidates")
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
    result = run_tencent_recovery(
        evidence_run_id=args.evidence_run_id, as_of_date=args.as_of_date,
        run_id=args.run_id, validate_only=args.validate_only, dry_run=args.dry_run,
        root=args.root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
