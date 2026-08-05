"""Offline Stage 9 orchestration, reporting, and fail-closed quality gating."""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from .quality.style_checks import (
    render_stage9_validation,
    run_stage9_post_write_checks,
    run_stage9_quality_checks,
)
from .storage.style_repository import (
    inspect_stage9_source,
    read_stage8_auxiliary,
    read_stage9_daily,
    upsert_stage9_results,
    validate_style_output_target,
)
from .style_classification import build_style_profiles
from .style_features import compute_style_features, load_stage9_config


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_version(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def validate_stage9_inputs(
    *, config_path: Path, input_database: Path, output_database: Path,
    as_of_date: pd.Timestamp, symbols: list[str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    blockers: list[str] = []
    try:
        config = load_stage9_config(config_path)
    except Exception as exc:
        config = None
        errors.append(f"stage9_config_invalid:{exc}")
    source = inspect_stage9_source(input_database, as_of_date=as_of_date, symbols=symbols)
    errors.extend(source.get("errors", []))
    blockers.extend(source.get("blockers", []))
    errors.extend(validate_style_output_target(input_database, output_database))
    status = "FAILED" if errors else ("BLOCKED" if blockers else "READY")
    return {
        "status": status, "as_of_date": pd.Timestamp(as_of_date).date(),
        "input_database": str(input_database), "output_database": str(output_database),
        "input_table": source.get("input_table"),
        "input_price_routes": source.get("input_price_routes", []),
        "qfq_row_count": source.get("qfq_row_count", 0),
        "symbols": symbols, "windows": list(config.windows) if config else None,
        "errors": sorted(set(errors)), "blockers": sorted(set(blockers)),
    }


def _decision(quality: pd.DataFrame, base_blockers: list[str]) -> tuple[str, str, int, list[str]]:
    failed = quality.loc[(quality["severity"] == "ERROR") & (quality["status"] == "FAIL"), "check_name"].astype(str).tolist()
    blockers = sorted(set(base_blockers + ["quality_error:" + name for name in failed]))
    return ("BLOCKED", "blocked", 2, blockers) if blockers else ("PASS", "research_only", 0, [])


def _quality_counts(quality: pd.DataFrame) -> tuple[int, int]:
    return int(quality["status"].eq("PASS").sum()), int(quality["status"].eq("FAIL").sum())


def _write_reports(root: Path, features: pd.DataFrame, profiles: pd.DataFrame, quality: pd.DataFrame, report: dict[str, Any]) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    features.to_csv(reports / "stage9_style_feature_sample.csv", index=False, encoding="utf-8-sig")
    profiles.to_csv(reports / "stage9_style_profile.csv", index=False, encoding="utf-8-sig")
    distribution = profiles.groupby("style_label", dropna=False).agg(count=("symbol", "size"), average_confidence=("confidence", "mean")).reset_index()
    distribution["run_id"] = report["run_id"]
    distribution.to_csv(reports / "stage9_style_distribution.csv", index=False, encoding="utf-8-sig")
    quality.to_csv(reports / "stage9_data_quality.csv", index=False, encoding="utf-8-sig")
    (reports / "stage9_run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
    (reports / "stage9_validation.md").write_text(
        render_stage9_validation(report), encoding="utf-8"
    )


def analyze_stage9(
    *, root: Path, config_path: Path, input_database: Path,
    output_database: Path, as_of_date: pd.Timestamp,
    start_date: pd.Timestamp | None = None, symbols: list[str] | None = None,
    windows: list[int] | None = None, stage8_database: Path | None = None,
    run_id: str | None = None, dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    started = pd.Timestamp.now(tz="UTC")
    as_of = pd.Timestamp(as_of_date).normalize()
    validation = validate_stage9_inputs(
        config_path=config_path, input_database=input_database,
        output_database=output_database, as_of_date=as_of, symbols=symbols,
    )
    if validation["status"] == "FAILED":
        raise ValueError("; ".join(validation["errors"]))
    config = load_stage9_config(config_path)
    requested_windows = windows or list(config.windows)
    if config.primary_window not in requested_windows:
        raise ValueError(
            f"Requested windows must include primary_window={config.primary_window}"
        )
    daily = read_stage9_daily(
        input_database, table=validation["input_table"], as_of_date=as_of,
        start_date=start_date, symbols=symbols,
    )
    selected_symbols = sorted(set(symbols or daily["symbol"].astype(str).str.zfill(6)))
    auxiliary, stage8_status = read_stage8_auxiliary(stage8_database)
    features = compute_style_features(
        daily, config, as_of_date=as_of, symbols=selected_symbols,
        windows=requested_windows, stage8_auxiliary=auxiliary,
    )
    profiles = build_style_profiles(features, config)
    effective_run_id = run_id or str(uuid.uuid4())
    created_at = started
    features["run_id"] = effective_run_id
    features["created_at"] = created_at
    profiles["run_id"] = effective_run_id
    profiles["created_at"] = created_at
    config_hash = _hash(config_path)
    quality = run_stage9_quality_checks(
        daily, features, profiles, run_id=effective_run_id, as_of_date=as_of,
        expected_symbols=selected_symbols, expected_windows=requested_windows,
        config_hash=config_hash, expected_config_hash=config_hash, checked_at=created_at,
    )
    run_status, publication_status, exit_code, blockers = _decision(quality, validation["blockers"])
    profiles["publication_status"] = publication_status
    passed, failed = _quality_counts(quality)
    output_type = "fixture" if root.resolve() != Path(__file__).resolve().parents[2] else "implementation_validation"
    report: dict[str, Any] = {
        "run_id": effective_run_id, "run_status": run_status,
        "publication_status": publication_status, "output_type": output_type,
        "started_at": started, "completed_at": pd.Timestamp.now(tz="UTC"),
        "created_at": created_at, "input_database": str(input_database),
        "input_table": validation["input_table"], "output_database": str(output_database),
        "as_of_date": as_of.date(), "window_start": daily["trade_date"].min().date() if not daily.empty else None,
        "window_end": daily["trade_date"].max().date() if not daily.empty else None,
        "windows": requested_windows, "primary_window": config.primary_window,
        "symbol_count": len(selected_symbols), "feature_row_count": len(features),
        "profile_row_count": len(profiles), "quality_passed": passed,
        "quality_failed": failed, "blocking_reasons": blockers,
        "config_hash": config_hash, "code_version": _code_version(root),
        "model_version": config.raw["model_version"],
        "config_version": config.raw["schema_version"],
        "stage8_publication_status": stage8_status,
        "stage8_formal_events_used": stage8_status == "formal",
        "style_distribution": profiles["style_label"].value_counts().sort_index().to_dict(),
        "insufficient_history_count": int(profiles["style_label"].eq("数据不足").sum()),
        "unclassified_count": int(profiles["style_label"].eq("未分类或混合型").sum()),
        "dry_run": dry_run,
    }
    if dry_run:
        return report, exit_code

    def audit_payload() -> dict[str, object]:
        return {
            "run_id": effective_run_id, "run_status": report["run_status"],
            "publication_status": report["publication_status"], "started_at": started,
            "completed_at": report["completed_at"], "input_database": str(input_database),
            "input_table": validation["input_table"], "output_database": str(output_database),
            "as_of_date": as_of.date(), "window_start": report["window_start"],
            "window_end": report["window_end"], "symbol_count": len(selected_symbols),
            "feature_row_count": len(features), "profile_row_count": len(profiles),
            "quality_passed": report["quality_passed"], "quality_failed": report["quality_failed"],
            "blocking_reasons": report["blocking_reasons"], "config_hash": config_hash,
            "code_version": report["code_version"], "output_type": output_type,
            "stage8_publication_status": stage8_status, "manifest": report,
            "created_at": created_at,
        }

    upsert_stage9_results(output_database, root / "sql/stage9_schema.sql", features=features, profiles=profiles, quality=quality, run=audit_payload())
    _write_reports(root, features, profiles, quality, report)
    post = run_stage9_post_write_checks(
        output_database, root / "reports", run_id=effective_run_id,
        expected_feature_rows=len(features), expected_profile_rows=len(profiles),
        expected_config_hash=config_hash, checked_at=created_at,
    )
    quality = pd.concat([quality, post], ignore_index=True)
    run_status, publication_status, exit_code, blockers = _decision(quality, validation["blockers"])
    profiles["publication_status"] = publication_status
    passed, failed = _quality_counts(quality)
    report.update(
        run_status=run_status, publication_status=publication_status,
        quality_passed=passed, quality_failed=failed, blocking_reasons=blockers,
        completed_at=pd.Timestamp.now(tz="UTC"),
    )
    upsert_stage9_results(output_database, root / "sql/stage9_schema.sql", features=features, profiles=profiles, quality=quality, run=audit_payload())
    _write_reports(root, features, profiles, quality, report)
    return report, exit_code
