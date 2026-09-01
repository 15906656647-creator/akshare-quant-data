"""Offline Stage 19 build over frozen Stage 17 unadjusted A-share assets."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import json
import uuid

import duckdb
import pandas as pd
import yaml

from .stage8_manual import validate_manual_dataset, _internal_rules, _internal_statuses
from .stage19_engine import (
    blocked_statistics, build_candidates, coverage_matrix, eligible_official_events,
    formal_statistics, release_gate, rule_audit,
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_stage19_config(path: Path, as_of_date: date) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value.get("stage") != 19:
        raise ValueError("Stage 19 config must declare stage: 19")
    if str(value.get("analysis_as_of_date")) != as_of_date.isoformat():
        raise ValueError("CLI as-of date must equal the explicit Stage 19 analysis date")
    symbols = value.get("symbols") or []
    if len(symbols) != 16 or len(set(symbols)) != 16:
        raise ValueError("Stage 19 requires the frozen 16-symbol A-share universe")
    if any(len(str(s)) != 6 or not str(s).isdigit() for s in symbols):
        raise ValueError("Stage 19 symbols must be six-digit A-share codes")
    return value


def _load_daily(root: Path, manifest: dict, symbols: list[str]) -> tuple[pd.DataFrame, list[dict]]:
    expected = {f"daily:{symbol}:raw" for symbol in symbols}
    chosen = {}
    for item in manifest.get("datasets", []):
        dataset_id = item.get("dataset_id")
        if dataset_id in expected and item.get("kind") == "equity_daily" and item.get("market") == "A" and item.get("adjust") == "raw":
            if item.get("status") != "success" or item.get("quality_status") != "PASS":
                raise ValueError(f"Formal Stage 17 dataset is not PASS: {dataset_id}")
            chosen[dataset_id] = item
    missing = sorted(expected - set(chosen))
    if missing:
        raise ValueError("Missing formal Stage 17 raw datasets: " + ",".join(missing))
    frames, evidence = [], []
    for dataset_id in sorted(chosen):
        item = chosen[dataset_id]
        path = root / item["data_path"]
        actual_hash = _sha256(path)
        if actual_hash != item["data_sha256"]:
            raise ValueError(f"Stage 17 hash mismatch: {dataset_id}")
        frame = pd.read_parquet(path).rename(columns={"date": "trade_date", "volume": "volume_share"})
        frame["symbol"], frame["adjust_type"] = item["symbol"], "raw"
        frames.append(frame[["symbol", "trade_date", "open", "high", "low", "close", "volume_share", "adjust_type"]])
        evidence.append({"dataset_id": dataset_id, "path": item["data_path"], "sha256": actual_hash,
                         "row_count": len(frame), "adjust_type": "raw"})
    return pd.concat(frames, ignore_index=True), evidence


def _historical_pass(root: Path, config: dict) -> tuple[bool, bool, dict]:
    rebuild_path = root / config["formal_release"]["stage8_rebuild_evidence"]
    rebuild_pass = False
    if rebuild_path.exists():
        try:
            with duckdb.connect(str(rebuild_path), read_only=True) as connection:
                row = connection.execute("SELECT status, publication_status FROM audit.stage8_run ORDER BY created_at DESC LIMIT 1").fetchone()
                rebuild_pass = bool(row and row[0] == "PASS" and row[1] == "formal")
        except Exception:
            rebuild_pass = False
    s15_path = root / config["formal_release"]["s15_14_evidence"]
    s15_payload = _read_json(s15_path) if s15_path.exists() else {}
    stale_s15_pass = str(s15_payload.get("status") or s15_payload.get("verdict") or "").upper() == "PASS"
    # Later governance records invalidate an S15-14 PASS that is not backed by
    # a currently passing formal Stage 8 rebuild.
    s15_pass = stale_s15_pass and rebuild_pass
    evidence = {"stage8_evidence": str(rebuild_path),
        "s15_14_evidence": str(s15_path), "s15_14_payload": s15_payload}
    if stale_s15_pass and not rebuild_pass:
        evidence["stale_s15_14_pass_ignored"] = True
        evidence["current_interpretation"] = "BLOCKED: S15-14 requires a current formal Stage 8 rebuild"
    return rebuild_pass, s15_pass, evidence


def _persist(root: Path, run_id: str, created_at: pd.Timestamp, candidates: pd.DataFrame,
             statistics: pd.DataFrame, gate: dict, config: dict,
             rules: list, statuses: list) -> Path:
    db_path = root / config["database_root"] / f"run_id={run_id}" / "stage19.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    formal_status = gate["formal_event_release"]["status"]
    columns = ["run_id", "symbol", "trade_date", "event_type", "previous_close", "open", "high", "low", "close",
        "theoretical_limit_up_price", "theoretical_limit_down_price", "matched_limit_price", "calculation_method",
        "rule_version", "security_status_version", "evidence_status", "quality_status", "blocked_reason", "next_trade_date",
        "next_open_return_vs_event_close", "next_open_return_vs_pre_event_close", "next_high_return", "next_low_return",
        "next_close_return", "next_day_continued_limit", "next_day_gap_up", "forward_3d_return", "forward_5d_return",
        "forward_10d_return", "mfe_3d", "mfe_5d", "mfe_10d", "mae_3d", "mae_5d", "mae_10d",
        "forward_sample_status", "consecutive_limit_up_count", "consecutive_limit_down_count", "created_at"]
    insert = candidates.rename(columns={"detection_method": "calculation_method", "resolution_reason": "blocked_reason",
        "next_open_return": "next_open_return_vs_event_close", "is_continued_limit": "next_day_continued_limit"}).copy()
    insert = insert.loc[:, ~insert.columns.duplicated(keep="last")]
    for column in columns:
        if column not in insert:
            insert[column] = None
    insert = insert[columns]
    # Recompute eligibility at the persistence boundary; callers cannot inject
    # unresolved or otherwise ineligible rows into the official table.
    official = eligible_official_events(candidates, gate)
    official_columns = ["run_id", "symbol", "trade_date", "event_type", "rule_version",
        "security_status_version", "calculation_method", "evidence_status", "release_status", "created_at"]
    official_insert = official.rename(columns={"detection_method": "calculation_method"}).copy()
    for column in official_columns:
        if column not in official_insert:
            official_insert[column] = "PASS" if column == "release_status" else None
    official_insert["release_status"] = "PASS"
    official_insert = official_insert[official_columns]
    checks = gate["formal_event_release"]["checks"]
    gate_frame = pd.DataFrame([{"run_id": run_id, "gate_id": key, "status": value["status"],
        "reason": value["reason"], "checked_at": created_at} for key, value in checks.items()])
    quality = gate_frame.rename(columns={"gate_id": "check_id"}).copy()
    quality["observed_value"], quality["expected_value"], quality["message"] = quality["status"], "PASS", quality["reason"]
    quality = quality[["run_id", "check_id", "status", "observed_value", "expected_value", "message", "checked_at"]]
    rule_frame = pd.DataFrame([{
        "exchange": item.exchange, "board": item.board,
        "special_treatment": "ST" if item.is_st else "NON_ST",
        "effective_start": item.effective_start, "effective_end": item.effective_end,
        "limit_up_ratio": item.limit_up_ratio, "limit_down_ratio": item.limit_down_ratio,
        "no_limit_flag": item.no_limit_flag, "tick_size": item.tick_size,
        "price_precision": item.price_precision, "rounding_rule": item.rounding_rule,
        "rule_version": item.rule_version, "source_name": item.source_name,
        "source_reference": item.source_reference,
        "verification_status": item.evidence_status,
        "manual_review_status": item.review_status,
    } for item in rules])
    status_frame = pd.DataFrame([{
        "symbol": item.symbol, "exchange": item.exchange, "board": item.board,
        "effective_start": item.effective_start, "effective_end": item.effective_end,
        "is_st": item.is_st, "special_treatment_type": item.special_treatment_type,
        "listing_status": item.listing_status, "source_name": item.source_name,
        "source_reference": item.source_reference, "source_date": item.source_published_at,
        "fetched_at": item.retrieved_at, "evidence_level": item.evidence_status,
        "verification_status": item.evidence_status,
        "manual_review_status": item.review_status, "notes": item.notes,
        "status_version": f"{item.status_version}:{item.status_type or 'COMBINED'}",
    } for item in statuses])
    with duckdb.connect(str(db_path)) as connection:
        connection.execute("BEGIN")
        try:
            connection.execute((root / "sql/stage19_schema.sql").read_text(encoding="utf-8"))
            connection.execute("DELETE FROM reference.limit_rule_history")
            if not rule_frame.empty:
                connection.register("rule_insert", rule_frame)
                connection.execute("INSERT INTO reference.limit_rule_history SELECT * FROM rule_insert")
            connection.execute("DELETE FROM reference.security_status_history")
            if not status_frame.empty:
                connection.register("status_insert", status_frame)
                connection.execute("INSERT INTO reference.security_status_history SELECT * FROM status_insert")
            for table in ("analysis.limit_event_candidate", "analysis.limit_event", "analysis.limit_event_statistics",
                          "quality.stage19_quality_result", "governance.stage19_release_gate"):
                connection.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
            connection.register("candidate_insert", insert)
            connection.execute("INSERT INTO analysis.limit_event_candidate SELECT * FROM candidate_insert")
            if formal_status == "PASS" and not official_insert.empty:
                connection.register("official_insert", official_insert)
                connection.execute("INSERT INTO analysis.limit_event SELECT * FROM official_insert")
            connection.register("statistics_insert", statistics)
            connection.execute("INSERT INTO analysis.limit_event_statistics SELECT * FROM statistics_insert")
            connection.register("quality_insert", quality)
            connection.execute("INSERT INTO quality.stage19_quality_result SELECT * FROM quality_insert")
            connection.register("gate_insert", gate_frame)
            connection.execute("INSERT INTO governance.stage19_release_gate SELECT * FROM gate_insert")
            connection.execute("DELETE FROM audit.stage19_run WHERE run_id = ?", [run_id])
            blockers = json.dumps(gate["formal_event_release"]["blocked_reasons"], ensure_ascii=False)
            connection.execute("INSERT INTO audit.stage19_run VALUES (?, ?, ?, ?, 'PASS', ?, ?, ?, ?, ?, ?)", [run_id,
                date.fromisoformat(config["analysis_as_of_date"]), date.fromisoformat(config["period_start"]),
                date.fromisoformat(config["period_end"]), "PASS" if formal_status == "PASS" else "BLOCKED", formal_status,
                len(insert), len(official_insert) if formal_status == "PASS" else 0, blockers, created_at])
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return db_path


def build_stage19(*, root: Path, config_path: Path, as_of_date: date,
                  run_id: str | None = None, validate_only: bool = False) -> dict:
    root = root.resolve()
    config = load_stage19_config(root / config_path, as_of_date)
    contract = _read_json(root / config["stage18_contract"])
    if contract.get("status") != "PASS" or contract.get("stage19_authorized") is not True:
        raise ValueError("Stage 18 does not provide a formal Stage 19 entry")
    manifest = _read_json(root / config["stage17_manifest"])
    if manifest.get("status") != "PASS" or manifest.get("run_id") != config["stage17_run_id"]:
        raise ValueError("Configured Stage 17 formal manifest is not PASS")
    run_id = run_id or str(uuid.uuid4())
    start, end = date.fromisoformat(config["period_start"]), date.fromisoformat(config["period_end"])
    rule_result = validate_manual_dataset(kind="rules", dataset_dir=root / config["rules_dataset_dir"],
        as_of_date=as_of_date, coverage_start=start, coverage_end=end, run_id=run_id)
    status_result = validate_manual_dataset(kind="status", dataset_dir=root / config["status_dataset_dir"],
        as_of_date=as_of_date, coverage_start=start, coverage_end=end, run_id=run_id)
    rules = _internal_rules(rule_result["records"], rule_result["manifest"]) if rule_result.get("status") == "READY" else []
    statuses = _internal_statuses(status_result["records"], status_result["manifest"]) if status_result.get("status") == "READY" else []
    coverage = coverage_matrix(statuses, config["symbols"], start, end)
    rebuild_pass, s15_pass, historical = _historical_pass(root, config)
    gate = release_gate(coverage=coverage, rule_result=rule_result, status_result=status_result,
        stage8_rebuild_pass=rebuild_pass, s15_14_pass=s15_pass)
    daily, raw_evidence = _load_daily(root, manifest, config["symbols"])
    daily_dates = pd.to_datetime(daily["trade_date"])
    buffer_start = pd.Timestamp(start) - pd.Timedelta(days=45)
    buffer_end = pd.Timestamp(end) + pd.Timedelta(days=45)
    daily = daily.loc[daily_dates.between(buffer_start, buffer_end)].copy()
    created_at = pd.Timestamp(datetime.now(timezone.utc))
    candidates = build_candidates(daily, rules, statuses, run_id=run_id, created_at=created_at)
    dates = pd.to_datetime(candidates["trade_date"]).dt.date
    candidates = candidates.loc[(dates >= start) & (dates <= end)].copy()
    formal_status = gate["formal_event_release"]["status"]
    official = eligible_official_events(candidates, gate)
    statistics = (
        formal_statistics(official, config["symbols"], start, end, run_id)
        if formal_status == "PASS"
        else blocked_statistics(config["symbols"], start, end, run_id,
                                gate["formal_event_release"]["blocked_reasons"])
    )
    report_dir = root / config["output_root"] / run_id
    report = {"stage": 19, "run_id": run_id, "as_of_date": as_of_date.isoformat(), "entry_status": "PASS",
        "target_symbols": config["symbols"], "analysis_range": [start.isoformat(), end.isoformat()],
        "price_route": "Stage 17 formal A-share adjust=raw only", "candidate_count": len(candidates),
        "official_event_count": int(len(official)),
        "rule_dataset": {k: rule_result.get(k) for k in ("status", "record_count", "review_status", "errors")},
        "status_dataset": {k: status_result.get(k) for k in ("status", "record_count", "review_status", "errors")},
        "rule_audit": rule_audit(rules, start, end), "historical_revalidation": historical,
        "stage8_rebuild_status": "PASS" if rebuild_pass else "BLOCKED", "s15_14_status": "PASS" if s15_pass else "BLOCKED",
        "release_gate": gate, "official_event_availability": "AVAILABLE" if gate["formal_event_release"]["status"] == "PASS" else "BLOCKED",
        "stage20_authorized": gate["formal_event_release"]["status"] == "PASS", "raw_inputs": raw_evidence,
        "validate_only": validate_only}
    if not validate_only:
        report_dir.mkdir(parents=True, exist_ok=True)
        coverage.to_csv(report_dir / "security_status_coverage.csv", index=False, encoding="utf-8")
        statistics.to_csv(report_dir / "formal_statistics.csv", index=False, encoding="utf-8")
        _write_json(report_dir / "stage19_gate.json", gate)
        db_path = _persist(root, run_id, created_at, candidates, statistics, gate, config, rules, statuses)
        report["database_path"] = str(db_path.relative_to(root)).replace("\\", "/")
        report["database_sha256"] = _sha256(db_path)
        _write_json(report_dir / "stage19_manifest.json", report)
    return report
