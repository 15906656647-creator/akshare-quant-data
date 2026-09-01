"""Stage 17.6.5 manual/external validation for 09669.HK raw/qfq/hfq."""
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

from .adapters.hk_manual_provider import ADJUSTMENTS, HkManualProvider, ManualDailyCall
from .paths import project_root
from .stage17_hk_tencent_validation import _quality, _relative, _verify_listing_evidence
from .storage.stage17_raw_store import Stage17RawStore


SYMBOL = "09669.HK"
REPORT_COLUMNS = (
    "symbol", "adjust", "provider", "status", "call_status", "quality_status",
    "row_count", "first_date", "last_date", "listing_date", "coverage_status",
    "source", "provider_adjust_semantics", "source_file", "source_sha256",
    "candidate_path", "candidate_sha256", "error_type", "error_message",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"Manual Raw target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"Manual Raw temporary file already exists: {temporary}")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _register(path: Path, *, root: Path, role: str, adjust: str) -> dict[str, Any]:
    return {
        "dataset_id": f"manual:{SYMBOL}:{adjust}", "role": role,
        "path": _relative(path, root), "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _save_source_evidence(
    *, call: ManualDailyCall, root: Path, run_id: str, adjust: str,
) -> list[dict[str, Any]]:
    if call.source_path is None or call.metadata_path is None:
        return []
    directory = (
        root / "data/raw/stage17/hk_manual_source_response" / f"run_id={run_id}"
        / "market=HK" / f"symbol={SYMBOL}" / f"adjust={adjust}"
        / "source=manual_external"
    )
    source_target = directory / f"source{call.source_path.suffix.casefold()}"
    metadata_target = directory / "source_metadata.json"
    _atomic_copy(call.source_path, source_target)
    _atomic_copy(call.metadata_path, metadata_target)
    if _sha256(source_target) != call.source_sha256:
        raise ValueError(f"Copied source hash mismatch for {adjust}")
    return [
        _register(source_target, root=root, role="source_response", adjust=adjust),
        _register(metadata_target, root=root, role="source_metadata", adjust=adjust),
    ]


def _write_reports(
    *, root: Path, run_id: str, evidence_run_id: str, input_dir: Path,
    as_of_date: date, started_at: datetime, finished_at: datetime,
    records: list[dict[str, Any]], raw_files: list[dict[str, Any]],
    listing_evidence: list[dict[str, Any]],
) -> Path:
    reports_root = root / "reports/stage17_hk_manual_validation"
    reports_root.mkdir(parents=True, exist_ok=True)
    target = reports_root / run_id
    if target.exists():
        raise FileExistsError(f"Manual validation report already exists: {target}")
    temporary = Path(tempfile.mkdtemp(prefix=f".stage17-hk-manual-{run_id}-", dir=reports_root))
    try:
        csv_path = temporary / "09669_validation.csv"
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        pass_count = sum(row["status"] == "PASS" for row in records)
        validation_status = "PASS" if pass_count == 3 else "BLOCKED"
        table_rows = "\n".join(
            f"| {row['adjust']} | {row['status']} | {row['row_count']} | "
            f"{row['first_date'] or '-'} | {row['last_date'] or '-'} | "
            f"{row['coverage_status']} | {row['source'] or '-'} | "
            f"{row['error_type'] or row['error_message'] or '-'} |"
            for row in records
        )
        report = f"""# Stage 17.6.5：09669.HK人工/外部数据验证

验证批次：`{run_id}`
业务基准日：`{as_of_date.isoformat()}`
Provider：`manual_external`

## 结论

- 专项验证状态：`{validation_status}`（{pass_count}/3 PASS）。
- Stage 17正式状态仍为：`BLOCKED`。
- Stage 18授权：`false`。
- 本批未建设Provider Registry，未重跑完整Stage 17，未创建Stage 18或Stage 19产物。

| adjust | status | rows | first_date | last_date | coverage | source | issue |
| --- | --- | ---: | --- | --- | --- | --- | --- |
{table_rows}

## 数据来源与语义门禁

输入目录：`{_relative(input_dir, root) if input_dir.is_relative_to(root) else str(input_dir)}`

每个口径必须同时提供CSV/Parquet和独立metadata。metadata必须记录来源、获取时间、源文件
SHA-256、字段定义、Provider复权定义及调整依据。`raw`不得冒充`qfq/hfq`，Yahoo
`Adj Close`不得冒充完整复权OHLC；计算型复权必须引用Raw、公司行动和因子三类哈希证据。

## 质量规则

质量检查直接复用Stage 17现有逻辑：非空、日期递增且唯一、无未来日期、OHLC包络、
成交量非负以及`complete_to_verified_listing_date`。本任务没有修改或放宽规则。

## 阶段边界

即使本专项3/3通过，也只代表具备进入后续独立Provider Registry任务的候选条件。本批不是
69项A/H日线与6项ETH的完整正式重跑，不能直接把Stage 17改为PASS或授权Stage 18。
"""
        report_path = temporary / "09669_validation.md"
        report_path.write_text(report, encoding="utf-8")
        manifest = {
            "stage": 17, "task": "stage17_6_5_09669_manual_validation",
            "run_id": run_id, "evidence_run_id": evidence_run_id,
            "symbol": SYMBOL, "provider": "manual_external",
            "input_dir": str(input_dir), "as_of_date": as_of_date.isoformat(),
            "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
            "expected_dataset_count": 3, "quality_pass_count": pass_count,
            "validation_status": validation_status,
            "stage17_formal_status_before": "BLOCKED",
            "stage17_formal_status_after": "BLOCKED", "stage17_formal_rerun": False,
            "provider_registry_built": False, "stage18_authorized": False,
            "stage19_artifacts_created": False, "raw_manifest_closed_world": True,
            "datasets": records, "raw_files": raw_files,
            "verified_listing_evidence": listing_evidence,
            "outputs": [
                {"path": (target / path.name).relative_to(root).as_posix(),
                 "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
                for path in (csv_path, report_path)
            ],
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def run_manual_validation(
    *, evidence_run_id: str, input_dir: Path, as_of_date: date,
    run_id: str | None = None, validate_only: bool = False, dry_run: bool = False,
    root: Path | None = None, provider: HkManualProvider | None = None,
) -> dict[str, Any]:
    if validate_only and dry_run:
        raise ValueError("validate_only and dry_run are mutually exclusive")
    root = (root or project_root()).resolve()
    input_dir = input_dir.resolve()
    uuid.UUID(evidence_run_id)
    listing_dates, listing_evidence, _, _ = _verify_listing_evidence(
        root=root, evidence_run_id=evidence_run_id, as_of_date=as_of_date,
    )
    provider = provider or HkManualProvider(input_dir)
    calls = {adjust: provider.fetch_daily(SYMBOL, adjust) for adjust in ADJUSTMENTS}
    plan = {
        "stage": 17, "task": "stage17_6_5_09669_manual_validation",
        "symbol": SYMBOL, "adjustments": list(ADJUSTMENTS),
        "as_of_date": as_of_date.isoformat(), "input_dir": str(input_dir),
        "input_status": {adjust: call.status for adjust, call in calls.items()},
        "network_calls": 0, "stage17_formal_rerun": False,
        "provider_registry_built": False, "stage18_authorized": False,
    }
    if validate_only:
        return {**plan, "mode": "validate_only", "outputs_written": False}
    if dry_run:
        return {**plan, "mode": "dry_run", "outputs_written": False}
    if run_id is None:
        raise ValueError("Formal manual validation requires an explicit run_id")
    uuid.UUID(run_id)
    raw_root = root / "data/raw/stage17"
    report_target = root / "reports/stage17_hk_manual_validation" / run_id
    if report_target.exists() or any(raw_root.rglob(f"run_id={run_id}")):
        raise FileExistsError(f"Manual validation run_id already exists: {run_id}")
    listing_date = listing_dates[SYMBOL]
    started_at = datetime.now(timezone.utc)
    store = Stage17RawStore(raw_root)
    raw_files: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for adjust in ADJUSTMENTS:
        call = calls[adjust]
        quality: dict[str, Any] | None = None
        candidate_result: dict[str, Any] | None = None
        if call.status == "success" and call.dataframe is not None:
            quality = _quality(
                call.dataframe[["date", "open", "high", "low", "close", "volume"]],
                listing_date=listing_date, as_of_date=as_of_date,
            )
            raw_files.extend(_save_source_evidence(
                call=call, root=root, run_id=run_id, adjust=adjust,
            ))
            directory = store.dataset_dir(
                dataset="hk_manual_candidate", run_id=run_id, market="HK",
                symbol=SYMBOL, adjust=adjust, source="manual_external",
            )
            generated_metadata = {
                "stage": 17, "task": "stage17_6_5_09669_manual_validation",
                "run_id": run_id, "symbol": SYMBOL, "market": "HK",
                "provider": "manual_external", "adjust": adjust,
                "listing_date": listing_date.isoformat(),
                "as_of_date": as_of_date.isoformat(), "quality": quality,
                "source_sha256": call.source_sha256,
                "source_metadata": call.metadata,
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "stage17_formal_dataset": False, "provider_registry_built": False,
                "stage18_authorized": False,
            }
            candidate_result = store.write_dataset(
                call.dataframe, directory, generated_metadata,
            )
            for role, key in (("candidate_data", "data_path"),
                              ("candidate_metadata", "metadata_path")):
                path = Path(candidate_result[key])
                raw_files.append(_register(
                    path, root=root, role=role, adjust=adjust,
                ))
        passed = call.status == "success" and quality is not None and quality["status"] == "PASS"
        metadata = call.metadata or {}
        records.append({
            "symbol": SYMBOL, "adjust": adjust, "provider": "manual_external",
            "status": "PASS" if passed else "FAIL", "call_status": call.status,
            "quality_status": quality["status"] if quality else "NOT_RUN",
            "row_count": len(call.dataframe) if call.dataframe is not None else 0,
            "first_date": quality.get("min_date") if quality else "",
            "last_date": quality.get("max_date") if quality else "",
            "listing_date": listing_date.isoformat(),
            "coverage_status": quality.get("coverage_status") if quality else "history_unavailable",
            "source": metadata.get("source", ""),
            "provider_adjust_semantics": metadata.get("provider_adjust_semantics", ""),
            "source_file": _relative(call.source_path, root) if call.source_path else "",
            "source_sha256": call.source_sha256,
            "candidate_path": _relative(Path(candidate_result["data_path"]), root)
            if candidate_result else "",
            "candidate_sha256": candidate_result.get("data_sha256", "")
            if candidate_result else "",
            "error_type": call.error_type,
            "error_message": call.error_message or (
                "|".join(quality.get("errors", [])) if quality else ""
            ),
        })
    finished_at = datetime.now(timezone.utc)
    report_dir = _write_reports(
        root=root, run_id=run_id, evidence_run_id=evidence_run_id,
        input_dir=input_dir, as_of_date=as_of_date, started_at=started_at,
        finished_at=finished_at, records=records, raw_files=raw_files,
        listing_evidence=listing_evidence,
    )
    pass_count = sum(record["status"] == "PASS" for record in records)
    return {
        **plan, "mode": "formal_validation", "run_id": run_id,
        "validation_status": "PASS" if pass_count == 3 else "BLOCKED",
        "quality_pass_count": pass_count, "expected_dataset_count": 3,
        "report_dir": str(report_dir), "stage17_formal_status": "BLOCKED",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate manual 09669.HK daily data")
    parser.add_argument("--evidence-run-id", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    parser.add_argument("--run-id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_manual_validation(
        evidence_run_id=args.evidence_run_id, input_dir=args.input_dir,
        as_of_date=args.as_of_date, run_id=args.run_id,
        validate_only=args.validate_only, dry_run=args.dry_run, root=args.root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
