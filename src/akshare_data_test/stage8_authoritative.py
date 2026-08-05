"""Authoritative Stage 8 rule/status dataset builders and S15-14 reverify.

The builders validate the curated authoritative datasets through the existing
Stage 8 configuration loader, then publish deterministic manifests.  The
S15-14 reverify reads Stage 8 formal events and Stage 15 cross-validation
snapshots and produces the manual-verification evidence table.  No network
access and no AKShare calls happen in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from .stage8_manual import (
    build_component_payload,
    provenance_report,
    validate_manual_dataset,
)
from .stage8_build import load_stage8_config


UNIVERSE = [
    "002067", "002600", "002230", "600763", "603259", "603799",
    "601012", "600438", "002361", "601500", "600231", "300274",
    "601636", "002129", "000100", "300433",
]

BASE_CONFIG_KEYS = {
    "schema_version": "1.0.0",
    "price_adjust_type": "raw",
    "rounding_rules": {"supported": ["half_up", "half_even"]},
    "formal_evidence_status": "verified",
    "formal_quality_status": "pass",
    "unresolved_policy": "block_formal_annual_statistics",
    "rule_records": [],
    "security_status_records": [],
    "source_notes": {
        "limit_pool_usage": "cross_validation_only",
        "gap_proxy_usage": "candidate_feature_only_not_formal_event",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _atomic_publish(payloads: list[tuple[Path, str]]) -> None:
    """Write all artifacts through a staging directory with rollback."""
    staging = Path(tempfile.mkdtemp(prefix="stage8_publish_"))
    try:
        staged: list[tuple[Path, Path]] = []
        for index, (target, text) in enumerate(payloads):
            encoding = "utf-8-sig" if target.suffix == ".csv" else "utf-8"
            staged_path = staging / f"{index}_{target.name}"
            staged_path.write_text(text, encoding=encoding, newline="\n")
            staged.append((target, staged_path))
        for target, staged_path in staged:
            if staged_path.suffix == ".json":
                json.loads(staged_path.read_text(encoding="utf-8"))
        replaced: list[Path] = []
        try:
            for target, staged_path in staged:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, target)
                replaced.append(target)
        except Exception:
            for path in reversed(replaced):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _load_component(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Authoritative dataset must be a mapping: {path}")
    return payload


def _merged_manifest(
    *,
    base: dict[str, Any] | None,
    current: dict[str, Any] | None,
    run_id: str,
) -> dict[str, Any] | None:
    base_manifest = (base or {}).get("dataset_manifest")
    current_manifest = (current or {}).get("dataset_manifest")
    if current_manifest is None:
        return base_manifest
    if base_manifest is None:
        return current_manifest
    return {
        "dataset_version": (
            f"{base_manifest['dataset_version']}+"
            f"{current_manifest['dataset_version']}"
        ),
        "generated_at": max(
            base_manifest["generated_at"], current_manifest["generated_at"]
        ),
        "as_of_date": current_manifest["as_of_date"],
        "source_files": sorted(
            set(base_manifest["source_files"]).union(
                current_manifest["source_files"]
            )
        ),
        "source_hashes": {
            **base_manifest["source_hashes"],
            **current_manifest["source_hashes"],
        },
        "record_counts": {
            **base_manifest["record_counts"],
            **current_manifest["record_counts"],
        },
        "date_coverage": {
            "start": min(
                base_manifest["date_coverage"]["start"],
                current_manifest["date_coverage"]["start"],
            ),
            "end": max(
                base_manifest["date_coverage"]["end"],
                current_manifest["date_coverage"]["end"],
            ),
        },
        "review_status": (
            "approved"
            if base_manifest["review_status"] == "approved"
            and current_manifest["review_status"] == "approved"
            else "rejected"
        ),
        "run_id": run_id,
    }


def _merged_config(
    *,
    base_path: Path | None,
    rules_payload: dict[str, Any] | None,
    statuses_payload: dict[str, Any] | None,
    run_id: str,
) -> dict[str, Any]:
    if base_path is not None and base_path.is_file():
        config = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    else:
        config = dict(BASE_CONFIG_KEYS)
    if rules_payload is not None:
        config["rule_records"] = list(rules_payload.get("rule_records", []))
    if statuses_payload is not None:
        config["security_status_records"] = list(
            statuses_payload.get("security_status_records", [])
        )
    config["dataset_manifest"] = _merged_manifest(
        base=config,
        current=statuses_payload if statuses_payload is not None else rules_payload,
        run_id=run_id,
    )
    return config


def _validate_config(config: dict[str, Any], output_dir: Path) -> tuple[Any, Any]:
    """Validate through the existing Stage 8 loader using a temporary file."""
    with tempfile.TemporaryDirectory(prefix="stage8_validate_") as temporary:
        temp = Path(temporary) / "config.yml"
        temp.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        raw, rules, statuses = load_stage8_config(temp)
    return rules, statuses


def build_rules_manifest(
    *,
    rules_path: Path | None = None,
    dataset_dir: Path | None = None,
    output_dir: Path,
    as_of_date: date,
    run_id: str | None = None,
    output_config: Path | None = None,
    base_config: Path | None = None,
    validate_only: bool = False,
    coverage_start: date | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate and publish the authoritative price-limit rule dataset."""
    effective_run_id = run_id or str(uuid.uuid4())
    dataset_result = None
    if dataset_dir is not None:
        dataset_result = validate_manual_dataset(
            kind="rules",
            dataset_dir=dataset_dir,
            as_of_date=as_of_date,
            coverage_start=coverage_start,
            coverage_end=as_of_date,
            run_id=effective_run_id,
        )
        if not dataset_result["valid"]:
            return {
                "stage": 8,
                "command": "stage8-rules-build",
                "status": dataset_result["status"],
                "run_id": effective_run_id,
                "as_of_date": as_of_date.isoformat(),
                "dataset_validation": dataset_result,
                "blocking_reasons": ["dataset_validation_failed"],
                "errors": dataset_result["errors"],
                "outputs_written": False,
            }, 2 if dataset_result["status"] == "BLOCKED" else 1
        payload = build_component_payload(
            kind="rules", validated=dataset_result
        )
    else:
        if rules_path is None:
            raise ValueError("rules_path or dataset_dir is required")
        payload = _load_component(rules_path)
    config = _merged_config(
        base_path=(
            base_config
            if base_config is not None
            else (output_config if output_config is not None and output_config.is_file() else None)
        ),
        rules_payload=payload,
        statuses_payload=None,
        run_id=effective_run_id,
    )
    rules, _ = _validate_config(config, output_dir)
    verified = [item for item in rules if item.evidence_status == "verified"]
    if not verified:
        return {
            "stage": 8,
            "command": "stage8-rules-build",
            "status": "BLOCKED",
            "run_id": effective_run_id,
            "rule_count": len(rules),
            "verified_rule_count": 0,
            "blocking_reasons": ["no_authoritative_limit_rules"],
            "outputs_written": False,
        }, 2
    if validate_only:
        return {
            "stage": 8,
            "command": "stage8-rules-build",
            "status": "READY",
            "run_id": effective_run_id,
            "as_of_date": as_of_date.isoformat(),
            "rule_count": len(rules),
            "verified_rule_count": len(verified),
            "dataset_validation": dataset_result,
            "outputs_written": False,
        }, 0
    records = [
        {
            "exchange": item.exchange,
            "board": item.board,
            "is_st": item.is_st,
            "symbol": item.symbol or "",
            "security_type": item.security_type or "",
            "effective_start": item.effective_start.isoformat(),
            "effective_end": item.effective_end.isoformat()
            if item.effective_end is not None
            else "",
            "record_id": item.record_id or "",
            "raw_file": item.raw_file or "",
            "source_document_id": item.source_document_id or "",
            "reviewer": item.reviewer or "",
            "notes": item.notes or "",
            "retrieved_at": item.retrieved_at or "",
            "review_status": item.review_status or "",
            "limit_up_ratio": str(item.limit_up_ratio),
            "limit_down_ratio": str(item.limit_down_ratio),
            "no_limit_flag": item.no_limit_flag,
            "tick_size": str(item.tick_size),
            "price_precision": item.price_precision,
            "rounding_rule": item.rounding_rule,
            "rule_version": item.rule_version,
            "source_reference": item.source_reference,
            "source_name": item.source_name,
            "source_published_at": item.source_published_at.isoformat()
            if item.source_published_at is not None
            else "",
            "source_hash": item.source_hash or "",
            "data_version": item.data_version or "",
            "verified_at": item.verified_at.isoformat()
            if item.verified_at is not None
            else "",
            "evidence_status": item.evidence_status,
        }
        for item in rules
    ]
    frame = pd.DataFrame(records)
    csv_path = output_dir / "rules_manifest.csv"
    report = {
        "stage": 8,
        "command": "stage8-rules-build",
        "status": "PASS",
        "run_id": effective_run_id,
        "as_of_date": as_of_date.isoformat(),
        "rule_count": len(rules),
        "verified_rule_count": len(verified),
        "exchanges": sorted({item.exchange for item in rules}),
        "boards": sorted({item.board for item in rules}),
        "source_versions": sorted({item.rule_version for item in rules}),
        "record_ids": sorted(
            {
                str(item.record_id)
                for item in rules
                if item.record_id is not None and str(item.record_id).strip()
            }
        ),
        "dataset_manifest": config.get("dataset_manifest"),
        "dataset_validation": dataset_result,
        "provenance": (
            provenance_report(dataset_result)
            if dataset_result is not None
            else None
        ),
        "outputs": {
            "rules_manifest_csv": str(csv_path),
            "rules_manifest_json": str(output_dir / "rules_manifest.json"),
            "output_config": str(output_config) if output_config else None,
            "dataset_validation_json": (
                str(output_dir / "rules_dataset_validation.json")
                if dataset_result is not None
                else None
            ),
            "dataset_provenance_json": (
                str(output_dir / "rules_dataset_provenance.json")
                if dataset_result is not None
                else None
            ),
        },
    }
    payloads: list[tuple[Path, str]] = [
        (csv_path, frame.to_csv(index=False)),
        (output_dir / "rules_manifest.json",
         json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"),
    ]
    if output_config is not None:
        payloads.append(
            (
                output_config,
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            )
        )
    if dataset_result is not None:
        payloads.append(
            (
                output_dir / "rules_dataset_validation.json",
                json.dumps(
                    dataset_result, ensure_ascii=False, indent=2, default=str
                )
                + "\n",
            )
        )
        payloads.append(
            (
                output_dir / "rules_dataset_provenance.json",
                json.dumps(
                    provenance_report(dataset_result),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
        )
    _atomic_publish(payloads)
    report["outputs"]["csv_sha256"] = _sha256(csv_path)
    return report, 0


def build_status_manifest(
    *,
    statuses_path: Path | None = None,
    dataset_dir: Path | None = None,
    output_dir: Path,
    as_of_date: date,
    run_id: str | None = None,
    output_config: Path | None = None,
    base_config: Path | None = None,
    validate_only: bool = False,
    coverage_start: date | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate and publish the authoritative security-status history dataset."""
    effective_run_id = run_id or str(uuid.uuid4())
    dataset_result = None
    if dataset_dir is not None:
        dataset_result = validate_manual_dataset(
            kind="status",
            dataset_dir=dataset_dir,
            as_of_date=as_of_date,
            coverage_start=coverage_start,
            coverage_end=as_of_date,
            run_id=effective_run_id,
        )
        if not dataset_result["valid"]:
            return {
                "stage": 8,
                "command": "stage8-status-build",
                "status": dataset_result["status"],
                "run_id": effective_run_id,
                "as_of_date": as_of_date.isoformat(),
                "dataset_validation": dataset_result,
                "blocking_reasons": ["dataset_validation_failed"],
                "errors": dataset_result["errors"],
                "outputs_written": False,
            }, 2 if dataset_result["status"] == "BLOCKED" else 1
        payload = build_component_payload(
            kind="status", validated=dataset_result
        )
    else:
        if statuses_path is None:
            raise ValueError("statuses_path or dataset_dir is required")
        payload = _load_component(statuses_path)
    config = _merged_config(
        base_path=(
            base_config
            if base_config is not None
            else (output_config if output_config is not None and output_config.is_file() else None)
        ),
        rules_payload=None,
        statuses_payload=payload,
        run_id=effective_run_id,
    )
    _, statuses = _validate_config(config, output_dir)
    verified = [item for item in statuses if item.evidence_status == "verified"]
    if not verified:
        return {
            "stage": 8,
            "command": "stage8-status-build",
            "status": "BLOCKED",
            "run_id": effective_run_id,
            "security_status_count": len(statuses),
            "verified_security_status_count": 0,
            "blocking_reasons": ["no_authoritative_security_status_history"],
            "outputs_written": False,
        }, 2
    if validate_only:
        return {
            "stage": 8,
            "command": "stage8-status-build",
            "status": "READY",
            "run_id": effective_run_id,
            "as_of_date": as_of_date.isoformat(),
            "security_status_count": len(statuses),
            "verified_security_status_count": len(verified),
            "covered_symbol_count": len({item.symbol for item in statuses}),
            "dataset_validation": dataset_result,
            "outputs_written": False,
        }, 0
    covered_symbols = sorted({item.symbol for item in statuses})
    records = [
        {
            "symbol": item.symbol,
            "exchange": item.exchange,
            "board": item.board,
            "listing_date": item.listing_date.isoformat()
            if item.listing_date is not None
            else "",
            "delisting_date": item.delisting_date.isoformat()
            if item.delisting_date is not None
            else "",
            "is_st": "" if item.is_st is None else item.is_st,
            "special_treatment_type": item.special_treatment_type or "",
            "listing_status": item.listing_status,
            "effective_start": item.effective_start.isoformat(),
            "effective_end": item.effective_end.isoformat()
            if item.effective_end is not None
            else "",
            "record_id": item.record_id or "",
            "status_type": item.status_type or "",
            "status_value": item.status_value or "",
            "announcement_date": item.announcement_date.isoformat()
            if item.announcement_date is not None
            else "",
            "raw_file": item.raw_file or "",
            "source_document_id": item.source_document_id or "",
            "reviewer": item.reviewer or "",
            "notes": item.notes or "",
            "retrieved_at": item.retrieved_at or "",
            "review_status": item.review_status or "",
            "no_limit_reason": item.no_limit_reason or "",
            "source_reference": item.source_reference,
            "source_name": item.source_name or "",
            "status_version": item.status_version,
            "source_published_at": item.source_published_at.isoformat()
            if item.source_published_at is not None
            else "",
            "source_hash": item.source_hash or "",
            "data_version": item.data_version or "",
            "evidence_status": item.evidence_status,
        }
        for item in statuses
    ]
    frame = pd.DataFrame(records)
    csv_path = output_dir / "status_manifest.csv"
    report = {
        "stage": 8,
        "command": "stage8-status-build",
        "status": "PASS",
        "run_id": effective_run_id,
        "as_of_date": as_of_date.isoformat(),
        "security_status_count": len(statuses),
        "verified_security_status_count": len(verified),
        "covered_symbol_count": len(covered_symbols),
        "expected_symbol_count": len(UNIVERSE),
        "missing_symbols": sorted(set(UNIVERSE).difference(covered_symbols)),
        "st_status_records": (
            sum(1 for record in records if str(record["is_st"]) == "True")
            if records
            else 0
        ),
        "record_ids": sorted(
            {
                str(item.record_id)
                for item in statuses
                if item.record_id is not None and str(item.record_id).strip()
            }
        ),
        "dataset_manifest": config.get("dataset_manifest"),
        "dataset_validation": dataset_result,
        "provenance": (
            provenance_report(dataset_result)
            if dataset_result is not None
            else None
        ),
        "outputs": {
            "status_manifest_csv": str(csv_path),
            "status_manifest_json": str(output_dir / "status_manifest.json"),
            "output_config": str(output_config) if output_config else None,
            "dataset_validation_json": (
                str(output_dir / "status_dataset_validation.json")
                if dataset_result is not None
                else None
            ),
            "dataset_provenance_json": (
                str(output_dir / "status_dataset_provenance.json")
                if dataset_result is not None
                else None
            ),
        },
    }
    payloads: list[tuple[Path, str]] = [
        (csv_path, frame.to_csv(index=False)),
        (output_dir / "status_manifest.json",
         json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"),
    ]
    if output_config is not None:
        payloads.append(
            (
                output_config,
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            )
        )
    if dataset_result is not None:
        payloads.append(
            (
                output_dir / "status_dataset_validation.json",
                json.dumps(
                    dataset_result, ensure_ascii=False, indent=2, default=str
                )
                + "\n",
            )
        )
        payloads.append(
            (
                output_dir / "status_dataset_provenance.json",
                json.dumps(
                    provenance_report(dataset_result),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
        )
    _atomic_publish(payloads)
    report["outputs"]["csv_sha256"] = _sha256(csv_path)
    return report, 0


def build_authoritative_config(
    *,
    rules_path: Path,
    statuses_path: Path,
    output_config: Path,
    base_config: Path | None = None,
    run_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Merge rules and status datasets into one runnable Stage 8 config."""
    rules_payload = _load_component(rules_path)
    statuses_payload = _load_component(statuses_path)
    config = _merged_config(
        base_path=base_config,
        rules_payload=rules_payload,
        statuses_payload=statuses_payload,
        run_id=run_id or str(uuid.uuid4()),
    )
    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_config.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    report = {
        "command": "stage8-authoritative-config",
        "status": "PASS",
        "output_config": str(output_config),
        "rule_records": len(config["rule_records"]),
        "security_status_records": len(config["security_status_records"]),
        "config_sha256": _sha256(output_config),
    }
    return report, 0


def _read_latest_events(database: Path) -> pd.DataFrame:
    with duckdb.connect(str(database), read_only=True) as connection:
        names = {
            f"{str(row[0])}.{str(row[1])}"
            for row in connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        if "analysis.v_latest_limit_event" not in names:
            raise ValueError(
                "stage8 database is missing analysis.v_latest_limit_event"
            )
        return connection.execute(
            "SELECT * FROM analysis.v_latest_limit_event ORDER BY symbol, trade_date"
        ).fetchdf()


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(pd.Timestamp(value).date())


def _num_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return repr(number)


def verify_s14(
    *,
    stage8_database: Path,
    stage15_reports_dir: Path,
    output_dir: Path,
    as_of_date: date,
    run_id: str | None = None,
    validate_only: bool = False,
) -> tuple[dict[str, Any], int]:
    """Produce the S15-14 manual-verification evidence from real Stage 8/15 data."""
    effective_run_id = run_id or str(uuid.uuid4())
    events = _read_latest_events(stage8_database)
    cross_path = stage15_reports_dir / "cross_validation.csv"
    if not cross_path.is_file():
        raise ValueError(f"stage15 cross_validation.csv not found: {cross_path}")
    if validate_only:
        return {
            "stage": 15,
            "command": "stage15-s14-reverify",
            "status": "READY",
            "run_id": effective_run_id,
            "as_of_date": as_of_date.isoformat(),
            "stage8_database": str(stage8_database),
            "stage15_reports_dir": str(stage15_reports_dir),
            "formal_event_count": int(
                events["event_type"].isin(["limit_up", "limit_down"]).sum()
            ),
            "outputs_written": False,
        }, 0
    cross = pd.read_csv(cross_path, dtype={"symbol": str})
    cross["symbol"] = cross["symbol"].astype(str).str.zfill(6)
    relevant = cross.loc[
        cross["check_item"].isin(
            ["recent_limit_up_day", "next_day_open_after_limit_up"]
        )
    ].copy()
    symbols = sorted(relevant["symbol"].unique())
    columns = [
        "symbol",
        "recent_formal_limit_up_day",
        "previous_valid_trade_day",
        "previous_close",
        "limit_ratio",
        "theoretical_limit_up_price",
        "actual_close",
        "security_status_version",
        "rule_version",
        "next_valid_trade_day",
        "next_day_open",
        "stage8_event_id",
        "manual_check_result",
        "note",
    ]
    rows: list[dict[str, Any]] = []
    unavailable_count = 0
    for symbol in symbols:
        symbol_cross = relevant.loc[relevant["symbol"].eq(symbol)]
        limit_up_day = symbol_cross.loc[
            symbol_cross["check_item"].eq("recent_limit_up_day")
        ]
        next_open_item = symbol_cross.loc[
            symbol_cross["check_item"].eq("next_day_open_after_limit_up")
        ]
        if (
            limit_up_day.empty
            or next_open_item.empty
            or str(limit_up_day.iloc[0]["verification_status"]) == "UNAVAILABLE"
            or str(next_open_item.iloc[0]["verification_status"]) == "UNAVAILABLE"
        ):
            unavailable_count += 1
            rows.append(
                {
                    "symbol": symbol,
                    "recent_formal_limit_up_day": "",
                    "previous_valid_trade_day": "",
                    "previous_close": "",
                    "limit_ratio": "",
                    "theoretical_limit_up_price": "",
                    "actual_close": "",
                    "security_status_version": "",
                    "rule_version": "",
                    "next_valid_trade_day": "",
                    "next_day_open": "",
                    "stage8_event_id": "",
                    "manual_check_result": "UNAVAILABLE",
                    "note": "no formal Stage 8 limit-up event",
                }
            )
            continue
        symbol_events = events.loc[events["symbol"].astype(str).eq(symbol)].copy()
        symbol_events = symbol_events.sort_values("trade_date", kind="mergesort")
        symbol_events = symbol_events.reset_index(drop=True)
        up = symbol_events.loc[symbol_events["event_type"].eq("limit_up")]
        latest = up.iloc[-1] if not up.empty else None
        if latest is None:
            unavailable_count += 1
            rows.append(
                {
                    "symbol": symbol,
                    "recent_formal_limit_up_day": "",
                    "previous_valid_trade_day": "",
                    "previous_close": "",
                    "limit_ratio": "",
                    "theoretical_limit_up_price": "",
                    "actual_close": "",
                    "security_status_version": "",
                    "rule_version": "",
                    "next_valid_trade_day": "",
                    "next_day_open": "",
                    "stage8_event_id": "",
                    "manual_check_result": "UNAVAILABLE",
                    "note": "no formal limit-up event for symbol",
                }
            )
            continue
        position = int(symbol_events.index[symbol_events["event_type"].eq("limit_up")][-1])
        previous_date = ""
        for prior in symbol_events.index[:position][::-1]:
            if bool(symbol_events.at[prior, "is_valid_trade_row"]):
                previous_date = _date_text(symbol_events.at[prior, "trade_date"])
                break
        observed_day = _date_text(limit_up_day.iloc[0]["observed_value"])
        observed_open = str(next_open_item.iloc[0]["observed_value"])
        event_day = _date_text(latest["trade_date"])
        event_open = _num_text(latest.get("next_open"))
        match = (
            observed_day == event_day
            and observed_open == event_open
        )
        rows.append(
            {
                "symbol": symbol,
                "recent_formal_limit_up_day": event_day,
                "previous_valid_trade_day": previous_date,
                "previous_close": _num_text(latest.get("previous_close")),
                "limit_ratio": _num_text(latest.get("limit_ratio")),
                "theoretical_limit_up_price": _num_text(
                    latest.get("theoretical_limit_up_price")
                    if latest.get("theoretical_limit_up_price") is not None
                    else latest.get("matched_limit_price")
                ),
                "actual_close": _num_text(latest.get("close")),
                "security_status_version": str(
                    latest.get("security_status_version") or ""
                ),
                "rule_version": str(latest.get("rule_version") or ""),
                "next_valid_trade_day": _date_text(latest.get("next_trade_date")),
                "next_day_open": event_open,
                "stage8_event_id": (
                    f"{latest.get('run_id')}:{symbol}:{event_day}"
                ),
                "manual_check_result": "REVIEW" if match else "MISMATCH",
                "note": (
                    "manual reviewer should confirm order of magnitude and field "
                    "interpretation against an external quote source"
                    if match
                    else "Stage 15 snapshot does not match Stage 8 formal event"
                ),
            }
        )
    frame = pd.DataFrame(rows, columns=columns)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "s14_verification.csv"
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    sample_count = int(frame["manual_check_result"].eq("REVIEW").sum())
    mismatch_count = int(frame["manual_check_result"].eq("MISMATCH").sum())
    status = (
        "PASS"
        if sample_count >= 2 and unavailable_count == 0 and mismatch_count == 0
        else "BLOCKED"
    )
    report = {
        "stage": 15,
        "command": "stage15-s14-reverify",
        "status": status,
        "run_id": effective_run_id,
        "as_of_date": as_of_date.isoformat(),
        "stage8_database": str(stage8_database),
        "stage15_reports_dir": str(stage15_reports_dir),
        "symbol_count": len(symbols),
        "valid_sample_count": sample_count,
        "unavailable_count": unavailable_count,
        "mismatch_count": mismatch_count,
        "blocking_reasons": (
            []
            if status == "PASS"
            else [
                reason
                for reason, condition in (
                    ("valid_sample_count_lt_2", sample_count < 2),
                    ("unavailable_items_present", unavailable_count > 0),
                    ("stage15_stage8_mismatch", mismatch_count > 0),
                )
                if condition
            ]
        ),
        "outputs": {
            "verification_csv": str(csv_path),
            "verification_json": str(output_dir / "s14_verification.json"),
            "verification_markdown": str(output_dir / "s14_verification.md"),
            "csv_sha256": _sha256(csv_path),
        },
    }
    _write_json(output_dir / "s14_verification.json", report)
    lines = [
        "# S15-14 最近涨停日及次日开盘价人工交叉验证补验",
        "",
        f"- run_id: `{effective_run_id}`",
        f"- as_of_date: {as_of_date.isoformat()}",
        f"- Stage8 数据库: `{stage8_database}`",
        f"- 有效样本数: {sample_count}",
        f"- UNAVAILABLE 数: {unavailable_count}",
        f"- 状态: **{status}**",
        "",
        "| symbol | 最近正式涨停日 | 前一有效交易日 | 前收盘价 | 涨停比例 | "
        "理论涨停价 | 实际收盘价 | 当日证券状态版本 | rule_id | "
        "次一有效交易日 | 次日开盘价 | Stage8事件ID | 人工核对结果 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | "
        "--- | ---: | --- | --- |",
    ]
    for row in frame.itertuples(index=False):
        lines.append(
            f"| {row.symbol} | {row.recent_formal_limit_up_day} | "
            f"{row.previous_valid_trade_day} | {row.previous_close} | "
            f"{row.limit_ratio} | {row.theoretical_limit_up_price} | "
            f"{row.actual_close} | {row.security_status_version} | "
            f"{row.rule_version} | {row.next_valid_trade_day} | "
            f"{row.next_day_open} | {row.stage8_event_id} | "
            f"{row.manual_check_result} |"
        )
    lines.extend(
        [
            "",
            "说明：`REVIEW` 表示已生成真实可核对数据，需人工对照行情源确认数量级与字段解释；"
            "本项目不构成投资建议。",
        ]
    )
    (output_dir / "s14_verification.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return report, 0 if status == "PASS" else 2
