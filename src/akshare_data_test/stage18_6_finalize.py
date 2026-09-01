"""Stage 18.6 final quality acceptance, exit freeze, and Stage 19 authorization."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from .stage18_4_load import _tree_fingerprint
from .stage18_6_config import STAGE_KEYS, Stage186Config, load_stage18_6_config
from .stage18_audit import Stage18Blocked, _atomic_csv, _atomic_text, frozen_hashes
from .stage18_reaudit import _verify_records
from .storage.raw_store import file_record, file_sha256


STAGE_FILES = {
    "stage18_1": ("stage18_1_run.json", "stage18_1_manifest.json", "stage18_2_authorized", "stage18_2_started"),
    "stage18_2": ("stage18_2_run.json", "stage18_2_manifest.json", "stage18_3_authorized", "stage18_3_started"),
    "stage18_3": ("stage18_3_run.json", "stage18_3_manifest.json", "stage18_4_authorized", "stage18_4_started"),
    "stage18_4": ("stage18_4_run.json", "stage18_4_manifest.json", "stage18_5_authorized", "stage18_5_started"),
    "stage18_5": ("stage18_5_run.json", "stage18_5_manifest.json", "stage18_6_authorized", "stage18_6_started"),
}


def _json_object(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Stage18Blocked(f"Missing or invalid Stage 18.6 evidence: {path}") from exc
    if not isinstance(value, dict): raise Stage18Blocked(f"Expected JSON object: {path}")
    return value


def _verify_stage_chain(root: Path, config: Stage186Config) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for stage in STAGE_KEYS:
        run_id = config.run_ids[stage]
        run_name, manifest_name, authorized_key, started_key = STAGE_FILES[stage]
        directory = root / config.reports_root / run_id
        run_path, manifest_path = directory / run_name, directory / manifest_name
        run, manifest = _json_object(run_path), _json_object(manifest_path)
        if (
            run.get("run_id") != run_id or run.get("status") != "PASS"
            or manifest.get("run_id") != run_id or manifest.get("status") != "PASS"
            or run.get(authorized_key) is not True or run.get(started_key) is not False
        ):
            raise Stage18Blocked(f"{stage} PASS/authorization evidence differs")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise Stage18Blocked(f"{stage} manifest file inventory is invalid")
        tree_hash = _verify_records(root, files, size_key="size")
        evidence[stage] = {
            "run_id": run_id, "run_sha256": file_sha256(run_path),
            "manifest_sha256": file_sha256(manifest_path),
            "manifest_file_count": len(files), "manifest_tree_sha256": tree_hash,
            "manifest_closed_world": manifest.get("manifest_closed_world", "legacy_verified_records"),
        }
    database, feature = root / config.database_path, root / config.feature_path
    if not database.is_file() or file_sha256(database) != config.database_sha256:
        raise Stage18Blocked("Stage 18.4 formal database SHA-256 differs")
    if not feature.is_file() or file_sha256(feature) != config.feature_sha256:
        raise Stage18Blocked("Stage 18.5 formal feature SHA-256 differs")
    return evidence


def _protected_state(root: Path, config: Stage186Config) -> dict[str, Any]:
    result = {
        "stage17_raw": _tree_fingerprint([root / "data/raw/stage17"], root),
        "stage18_raw": _tree_fingerprint([root / "data/raw/stage18"], root),
        "stage18_clean": _tree_fingerprint([root / "data/clean/stage18"], root),
        "formal_database": _tree_fingerprint([root / config.database_path.parent], root),
        "formal_features": _tree_fingerprint([root / config.feature_path.parent], root),
    }
    for stage, run_id in config.run_ids.items():
        result[f"{stage}_reports"] = _tree_fingerprint([root / config.reports_root / run_id], root)
    return result


def _stage19_file_count(root: Path) -> int:
    return sum(
        1 for target in (root / "data/raw/stage19", root / "reports/stage19")
        if target.exists() for item in target.rglob("*") if item.is_file()
    )


def _load_and_validate_features(root: Path, config: Stage186Config) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    frame = pd.read_parquet(root / config.feature_path)
    failures: list[str] = []
    expected_columns = {"symbol", "market", "as_of_date", "feature_name", "feature_value", "feature_status", "unavailable_reason", "lineage_json", "source_tables"}
    if not expected_columns.issubset(frame.columns):
        raise Stage18Blocked("Stage 18.5 feature schema lacks final-contract columns")
    counts = frame["feature_status"].value_counts().to_dict()
    checks = {
        "feature_units": len(frame) == config.expected_feature_units,
        "security_count": frame["symbol"].nunique() == config.expected_security_count,
        "feature_count": frame["feature_name"].nunique() == config.expected_feature_count,
        "pass_count": int(counts.get("PASS", 0)) == config.expected_pass,
        "unavailable_count": int(counts.get("UNAVAILABLE", 0)) == config.expected_unavailable,
        "fail_count": int(counts.get("FAIL", 0)) == 0,
        "blocked_count": int(counts.get("BLOCKED", 0)) == 0,
        "terminal_statuses": set(counts) <= {"PASS", "UNAVAILABLE"},
        "pass_value_and_lineage": bool(((frame.loc[frame["feature_status"] == "PASS", "feature_value"].notna()) & (frame.loc[frame["feature_status"] == "PASS", "lineage_json"] != "[]")).all()),
        "unavailable_null_value": bool(frame.loc[frame["feature_status"] == "UNAVAILABLE", "feature_value"].isna().all()),
    }
    unavailable = frame[frame["feature_status"] == "UNAVAILABLE"]
    reasons = unavailable["unavailable_reason"].value_counts().to_dict()
    checks["known_unavailable_reasons"] = reasons == config.allowed_reasons
    unknown = sorted(set(reasons) - set(config.allowed_reasons))
    a = frame[frame["market"] == "A"]
    hk = frame[frame["market"] == "HK"]
    ordinary = set(frame["feature_name"]) - {"roa", "roe"}
    checks["a_ten_features_16_pass"] = all(int(((a["feature_name"] == name) & (a["feature_status"] == "PASS")).sum()) == 16 for name in ordinary)
    checks["a_roa_roe_5_11"] = all(int(((a["feature_name"] == name) & (a["feature_status"] == "PASS")).sum()) == 5 and int(((a["feature_name"] == name) & (a["feature_status"] == "UNAVAILABLE")).sum()) == 11 for name in ("roa", "roe"))
    checks["hk_84_unavailable"] = len(hk) == 84 and hk["feature_status"].eq("UNAVAILABLE").all()
    checks["valuation_source_excluded"] = not frame["source_tables"].str.contains("valuation", regex=False).any()
    checks["as_of_date_frozen"] = pd.to_datetime(frame["as_of_date"]).dt.date.eq(config.as_of_date).all()
    failures.extend(name for name, ok in checks.items() if not ok)
    return frame, {"checks": checks, "reason_counts": reasons, "unknown_reasons": unknown}, failures


def _gate_rows(
    *, root: Path, config: Stage186Config, frame: pd.DataFrame,
    feature_audit: dict[str, Any], chain: dict[str, Any], stage0_same: bool,
    protected_same: bool, stage19_count: int, residual_count: int,
) -> tuple[pd.DataFrame, list[str]]:
    stage185 = _json_object(root / config.reports_root / config.run_ids["stage18_5"] / "stage18_5_run.json")
    with duckdb.connect(str(root / config.database_path), read_only=True) as connection:
        valuation = connection.execute("SELECT count(*), count(*) FILTER (WHERE eligible_for_as_of_date_analysis IS FALSE), count(*) FILTER (WHERE eligible_for_as_of_date_analysis IS TRUE) FROM fact_valuation_snapshot").fetchone()
    observed = {
        "stage18_1_to_5_pass": int(all(item["run_id"] for item in chain.values())),
        "feature_units": len(frame), "feature_pass": int((frame["feature_status"] == "PASS").sum()),
        "feature_unavailable": int((frame["feature_status"] == "UNAVAILABLE").sum()),
        "feature_fail": int((frame["feature_status"] == "FAIL").sum()),
        "feature_blocked": int((frame["feature_status"] == "BLOCKED").sum()),
        "unknown_unavailable_reasons": len(feature_audit["unknown_reasons"]),
        "future_data_usage": int(stage185["future_data_usage_count"]),
        "announcement_inference": int(stage185["announcement_date_inference_count"]),
        "valuation_leakage": int(stage185["valuation_leakage_count"]),
        "period_mismatch": int(stage185["period_mismatch_count"]),
        "valuation_rows": int(valuation[0]), "valuation_ineligible_rows": int(valuation[1]), "valuation_eligible_rows": int(valuation[2]),
        "database_hash_match": int(file_sha256(root / config.database_path) == config.database_sha256),
        "feature_hash_match": int(file_sha256(root / config.feature_path) == config.feature_sha256),
        "stage0_unchanged": int(stage0_same), "formal_assets_unchanged": int(protected_same),
        "stage19_assets": stage19_count, "temporary_residuals": residual_count,
    }
    expected = {
        "stage18_1_to_5_pass": 1, "feature_units": 276, "feature_pass": 170,
        "feature_unavailable": 106, "feature_fail": 0, "feature_blocked": 0,
        "unknown_unavailable_reasons": 0, "future_data_usage": 0,
        "announcement_inference": 0, "valuation_leakage": 0, "period_mismatch": 0,
        "valuation_rows": 23, "valuation_ineligible_rows": 23, "valuation_eligible_rows": 0,
        "database_hash_match": 1, "feature_hash_match": 1, "stage0_unchanged": 1,
        "formal_assets_unchanged": 1, "stage19_assets": 0, "temporary_residuals": 0,
    }
    rows = [{"check_name": name, "expected": expected[name], "observed": observed[name], "status": "PASS" if expected[name] == observed[name] else "FAIL"} for name in expected]
    for name, ok in feature_audit["checks"].items():
        rows.append({"check_name": f"feature_contract:{name}", "expected": 1, "observed": int(ok), "status": "PASS" if ok else "FAIL"})
    quality = pd.DataFrame(rows)
    failures = quality.loc[quality["status"] == "FAIL", "check_name"].tolist()
    return quality, failures


def run_stage18_6(
    *, root: str | Path | None = None, config_path: str | Path = "config/stage18_6.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], int]:
    project_root = Path(root or Path.cwd()).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute(): config_file = project_root / config_file
    config = load_stage18_6_config(config_file)
    if as_of_date != config.as_of_date: raise Stage18Blocked("Stage 18.6 as-of date differs from frozen configuration")
    if upstream_run_id is not None and upstream_run_id != config.run_ids["stage18_5"]:
        raise Stage18Blocked("Stage 18.6 upstream run id differs from the sole formal Stage 18.5 run")
    stage0_before = frozen_hashes(project_root)
    chain_before = _verify_stage_chain(project_root, config)
    protected_before = _protected_state(project_root, config)
    frame, feature_audit, feature_failures = _load_and_validate_features(project_root, config)
    if validate_only or dry_run:
        return ({"stage": 18, "substage": "18.6", "status": "VALIDATED" if validate_only else "DRY_RUN", "stage_chain": chain_before, "feature_units": len(frame), "writes": 0}, 0)
    active_run = run_id or str(uuid.uuid4())
    try: uuid.UUID(active_run)
    except ValueError as exc: raise Stage18Blocked("Stage 18.6 run_id must be a UUID") from exc
    report_dir = project_root / config.reports_root / active_run
    if report_dir.exists(): raise Stage18Blocked("Stage 18.6 report path already exists; append-only policy blocks overwrite")
    report_dir.mkdir(parents=True, exist_ok=False)
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now().astimezone(timezone.utc).isoformat()
    coverage = frame.copy()
    coverage["downstream_policy"] = coverage["feature_status"].map({"PASS": "AVAILABLE", "UNAVAILABLE": "PRESERVE_NULL_UNAVAILABLE"})
    unavailable = coverage[coverage["feature_status"] == "UNAVAILABLE"].copy()
    stage0_after = frozen_hashes(project_root)
    chain_after = _verify_stage_chain(project_root, config)
    protected_after = _protected_state(project_root, config)
    stage19_count = _stage19_file_count(project_root)
    residual_count = sum(1 for target in [project_root / config.database_path.parent, project_root / config.feature_path.parent] for item in target.rglob("*") if item.name.endswith((".tmp", ".wal")))
    quality, gate_failures = _gate_rows(root=project_root, config=config, frame=frame, feature_audit=feature_audit, chain=chain_after, stage0_same=stage0_before == stage0_after, protected_same=protected_before == protected_after, stage19_count=stage19_count, residual_count=residual_count)
    blockers = feature_failures + gate_failures
    status = "PASS" if not blockers else "BLOCKED"
    contract = {
        "contract_version": "stage18_to_stage19_v1", "status": status,
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "fundamental_database_run_id": config.run_ids["stage18_4"],
        "fundamental_database_path": config.database_path.as_posix(),
        "fundamental_database_sha256": config.database_sha256,
        "fundamental_feature_run_id": config.run_ids["stage18_5"],
        "fundamental_feature_path": config.feature_path.as_posix(),
        "fundamental_feature_sha256": config.feature_sha256,
        "feature_policy": {"PASS": "downstream_eligible", "UNAVAILABLE": "preserve_null_and_unavailable_no_fill", "FAIL": "prohibited", "BLOCKED": "prohibited"},
        "current_valuation_snapshot": {"eligible_for_as_of_date_analysis": False, "historical_pe_pb_backfill_allowed": False},
        "upstream_access_policy": {"formal_inputs_only": ["fundamental_database", "fundamental_feature"], "stage18_audit_raw_reinterpretation_allowed": False},
        "stage19_authorized": status == "PASS", "stage19_started": False,
        "stage19_event_publication_gate_required": True,
    }
    for name, value in (("final_feature_coverage.csv", coverage), ("unavailable_items.csv", unavailable), ("final_quality_summary.csv", quality)):
        _atomic_csv(report_dir / name, value, must_not_exist=True)
    contract_path = report_dir / "downstream_contract.json"
    _atomic_text(contract_path, json.dumps(contract, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    run_report = {
        "stage": 18, "substage": "18.6", "run_id": active_run,
        "status": status, "stage18_status": status,
        "started_at": started_at, "finished_at": now().astimezone(timezone.utc).isoformat(),
        "analysis_as_of_date": config.as_of_date.isoformat(),
        "upstream_stage18_5_run_id": config.run_ids["stage18_5"],
        "stage_chain": {stage: {"run_id": item["run_id"], "status": "PASS"} for stage, item in chain_after.items()},
        "formal_database_path": config.database_path.as_posix(), "formal_database_sha256": config.database_sha256,
        "formal_feature_path": config.feature_path.as_posix(), "formal_feature_sha256": config.feature_sha256,
        "feature_unit_count": len(frame), "feature_pass_count": int((frame["feature_status"] == "PASS").sum()),
        "feature_unavailable_count": int((frame["feature_status"] == "UNAVAILABLE").sum()),
        "feature_fail_count": int((frame["feature_status"] == "FAIL").sum()), "feature_blocked_count": int((frame["feature_status"] == "BLOCKED").sum()),
        "unknown_unavailable_reason_count": len(feature_audit["unknown_reasons"]),
        "unavailable_reason_counts": feature_audit["reason_counts"],
        "quality_check_count": len(quality), "quality_fail_count": int((quality["status"] == "FAIL").sum()),
        "stage0_hashes_unchanged": stage0_before == stage0_after,
        "formal_assets_unchanged": protected_before == protected_after,
        "stage_chain_unchanged": chain_before == chain_after,
        "stage19_asset_count": stage19_count, "tmp_wal_residual_count": residual_count,
        "blockers": blockers, "stage19_authorized": status == "PASS", "stage19_started": False,
        "known_test_debt": {"node_id": "tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset", "signature": "expected returncode 1, observed returncode 0"},
    }
    run_path = report_dir / "stage18_6_run.json"
    _atomic_text(run_path, json.dumps(run_report, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    artifacts = [config_file, run_path, contract_path, report_dir / "final_feature_coverage.csv", report_dir / "unavailable_items.csv", report_dir / "final_quality_summary.csv"]
    records = [file_record(path, project_root) for path in artifacts]
    manifest = {"stage": 18, "substage": "18.6", "run_id": active_run, "status": status, "stage18_status": status, "formal_exit_assets": [{"role": "fundamental_database", "path": config.database_path.as_posix(), "sha256": config.database_sha256}, {"role": "fundamental_feature", "path": config.feature_path.as_posix(), "sha256": config.feature_sha256}], "files": records, "manifest_closed_world": status == "PASS", "stage19_authorized": status == "PASS", "stage19_started": False}
    manifest_path = report_dir / "stage18_6_manifest.json"
    _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    _verify_records(project_root, records, size_key="size")
    if file_sha256(project_root / config.database_path) != config.database_sha256 or file_sha256(project_root / config.feature_path) != config.feature_sha256:
        raise Stage18Blocked("Stage 18 formal exit asset changed during finalization")
    return run_report, 0 if status == "PASS" else 1
