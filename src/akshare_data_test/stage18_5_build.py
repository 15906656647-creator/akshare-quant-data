"""Stage 18.5 point-in-time fundamental feature construction."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import numpy as np
import pandas as pd

from .stage18_4_load import _tree_fingerprint
from .stage18_5_config import FEATURE_NAMES, Stage185Config, load_stage18_5_config
from .stage18_audit import Stage18Blocked, _atomic_csv, _atomic_text, frozen_hashes
from .stage18_reaudit import _verify_records
from .storage.raw_store import file_record, file_sha256
from .storage.stage18_feature_store import Stage18FeatureStore


FEATURE_DEFINITIONS = (
    {"feature_name": "revenue", "formula": "latest PIT revenue normalized_value", "required_source_fields": '["revenue"]', "preferred_statement": "fact_income_statement", "period_semantics": "latest_available_report_period", "currency_requirement": "single_currency", "pit_requirement": "PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "not_applicable", "output_unit": "currency"},
    {"feature_name": "net_profit", "formula": "latest PIT net_profit normalized_value", "required_source_fields": '["net_profit"]', "preferred_statement": "fact_income_statement", "period_semantics": "latest_available_report_period", "currency_requirement": "single_currency", "pit_requirement": "PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "not_applicable", "output_unit": "currency"},
    {"feature_name": "total_assets", "formula": "latest PIT total_assets normalized_value", "required_source_fields": '["total_assets"]', "preferred_statement": "fact_balance_sheet", "period_semantics": "latest_available_report_period", "currency_requirement": "single_currency", "pit_requirement": "PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "not_applicable", "output_unit": "currency"},
    {"feature_name": "total_equity", "formula": "latest PIT net_assets normalized_value", "required_source_fields": '["net_assets"]', "preferred_statement": "fact_balance_sheet", "period_semantics": "latest_available_report_period", "currency_requirement": "single_currency", "pit_requirement": "PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "not_applicable", "output_unit": "currency"},
    {"feature_name": "operating_cash_flow", "formula": "latest PIT operating_cash_flow normalized_value", "required_source_fields": '["operating_cash_flow"]', "preferred_statement": "fact_cash_flow_statement", "period_semantics": "latest_available_report_period cumulative", "currency_requirement": "single_currency", "pit_requirement": "PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "not_applicable", "output_unit": "currency"},
    {"feature_name": "revenue_yoy", "formula": "revenue(t)/revenue(t-1 same fiscal_period)-1", "required_source_fields": '["revenue"]', "preferred_statement": "fact_income_statement", "period_semantics": "same_fiscal_period_prior_year", "currency_requirement": "same_currency", "pit_requirement": "both inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
    {"feature_name": "net_profit_yoy", "formula": "net_profit(t)/net_profit(t-1 same fiscal_period)-1", "required_source_fields": '["net_profit"]', "preferred_statement": "fact_income_statement", "period_semantics": "same_fiscal_period_prior_year", "currency_requirement": "same_currency", "pit_requirement": "both inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
    {"feature_name": "net_margin", "formula": "net_profit/revenue at same report period", "required_source_fields": '["net_profit","revenue"]', "preferred_statement": "fact_income_statement", "period_semantics": "same_report_period cumulative", "currency_requirement": "same_currency", "pit_requirement": "all inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
    {"feature_name": "roa", "formula": "annual net_profit/average(current FY total_assets,prior FY total_assets)", "required_source_fields": '["net_profit","total_assets"]', "preferred_statement": "fact_income_statement+fact_balance_sheet", "period_semantics": "latest FY with prior comparable FY balance", "currency_requirement": "same_currency", "pit_requirement": "all inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
    {"feature_name": "roe", "formula": "annual parent_net_profit/average(current FY parent_equity,prior FY parent_equity)", "required_source_fields": '["parent_net_profit","parent_equity"]', "preferred_statement": "fact_income_statement+fact_balance_sheet", "period_semantics": "latest FY with prior comparable FY balance", "currency_requirement": "same_currency", "pit_requirement": "all inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
    {"feature_name": "debt_to_asset", "formula": "total_liabilities/total_assets at same report period", "required_source_fields": '["total_liabilities","total_assets"]', "preferred_statement": "fact_balance_sheet", "period_semantics": "same_report_period stock values", "currency_requirement": "same_currency", "pit_requirement": "all inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
    {"feature_name": "ocf_to_net_profit", "formula": "operating_cash_flow/net_profit at same report period", "required_source_fields": '["operating_cash_flow","net_profit"]', "preferred_statement": "fact_cash_flow_statement+fact_income_statement", "period_semantics": "same_report_period cumulative", "currency_requirement": "same_currency", "pit_requirement": "all inputs PIT_ELIGIBLE and eligible=true", "null_policy": "UNAVAILABLE", "division_by_zero_policy": "UNAVAILABLE", "output_unit": "ratio"},
)

TABLES = ("fact_income_statement", "fact_balance_sheet", "fact_cash_flow_statement")


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Stage18Blocked(f"Missing or invalid Stage 18.5 upstream evidence: {path}") from exc
    if not isinstance(value, dict):
        raise Stage18Blocked(f"Expected JSON object: {path}")
    return value


def _upstream_fingerprint(root: Path, config: Stage185Config) -> dict[str, Any]:
    run_path = root / config.source_run_path
    manifest_path = root / config.source_manifest_path
    database_path = root / config.database_path
    run = _json_object(run_path)
    manifest = _json_object(manifest_path)
    if (
        run.get("run_id") != config.source_run_id or run.get("status") != "PASS"
        or run.get("stage18_5_authorized") is not True or run.get("stage18_5_started") is not False
        or run.get("database_path") != config.database_path.as_posix()
        or run.get("database_sha256") != config.database_sha256
        or manifest.get("run_id") != config.source_run_id or manifest.get("status") != "PASS"
        or manifest.get("manifest_closed_world") is not True
    ):
        raise Stage18Blocked("Stage 18.4 PASS/authorization/database evidence differs")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise Stage18Blocked("Stage 18.4 manifest file inventory is invalid")
    tree_hash = _verify_records(root, files, size_key="size")
    if not database_path.is_file() or file_sha256(database_path) != config.database_sha256:
        raise Stage18Blocked("Stage 18.4 database SHA-256 differs")
    return {"run_id": config.source_run_id, "run_sha256": file_sha256(run_path), "manifest_sha256": file_sha256(manifest_path), "manifest_tree_sha256": tree_hash, "database_sha256": config.database_sha256, "database_size_bytes": database_path.stat().st_size}


def _protected_state(root: Path, config: Stage185Config) -> dict[str, Any]:
    return {
        "stage17_raw": _tree_fingerprint([root / "data/raw/stage17"], root),
        "stage18_raw": _tree_fingerprint([root / "data/raw/stage18"], root),
        "stage18_clean": _tree_fingerprint([root / "data/clean/stage18"], root),
        "stage18_4_database": _tree_fingerprint([root / config.database_path.parent], root),
        "stage18_4_reports": _tree_fingerprint([root / config.source_run_path.parent], root),
    }


def _load_pit_inputs(database_path: Path, as_of_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = as_of_date.isoformat()
    with duckdb.connect(str(database_path), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        required = set(TABLES) | {"fact_valuation_snapshot"}
        if not required.issubset(tables):
            raise Stage18Blocked("Stage 18.5 required database tables are missing")
        union = " UNION ALL ".join(
            f"SELECT *, '{table}' AS source_table FROM {table}" for table in TABLES
        )
        core = connection.execute(
            f"SELECT * FROM ({union}) WHERE pit_status='PIT_ELIGIBLE' "
            "AND eligible_for_as_of_date_analysis IS TRUE "
            "AND announcement_date IS NOT NULL AND update_date IS NOT NULL "
            f"AND announcement_date <= DATE '{cutoff}' AND update_date <= DATE '{cutoff}' "
            "AND mapping_status='CORE_MAPPED'"
        ).fetchdf()
        securities = connection.execute(
            "SELECT DISTINCT symbol, market FROM fact_valuation_snapshot ORDER BY market, symbol"
        ).fetchdf()
        valuation = connection.execute(
            "SELECT count(*) AS rows, count(*) FILTER (WHERE eligible_for_as_of_date_analysis IS FALSE) AS ineligible_rows, count(*) FILTER (WHERE eligible_for_as_of_date_analysis IS TRUE) AS eligible_rows FROM fact_valuation_snapshot"
        ).fetchone()
    if tuple(int(value) for value in valuation) != (23, 23, 0):
        raise Stage18Blocked("Stage 18.5 valuation exclusion gate differs")
    if len(securities) != 23 or int((securities["market"] == "A").sum()) != 16 or int((securities["market"] == "HK").sum()) != 7:
        raise Stage18Blocked("Stage 18.5 security identity scope differs")
    return core, securities


def _row_index(core: pd.DataFrame) -> dict[tuple[str, str], list[pd.Series]]:
    result: dict[tuple[str, str], list[pd.Series]] = {}
    for _, row in core.iterrows():
        result.setdefault((str(row["symbol"]), str(row["canonical_name"])), []).append(row)
    for rows in result.values():
        rows.sort(key=lambda row: (pd.Timestamp(row["report_date"]), pd.Timestamp(row["update_date"])), reverse=True)
    return result


def _prior_comparable(rows: list[pd.Series], current: pd.Series) -> pd.Series | None:
    year = int(current["fiscal_year"]) - 1
    period = str(current["fiscal_period"])
    return next((row for row in rows if int(row["fiscal_year"]) == year and str(row["fiscal_period"]) == period), None)


def _same_date(left: list[pd.Series], right: list[pd.Series]) -> tuple[pd.Series, pd.Series] | None:
    right_by_date = {pd.Timestamp(row["report_date"]): row for row in right}
    for row in left:
        other = right_by_date.get(pd.Timestamp(row["report_date"]))
        if other is not None:
            return row, other
    return None


def _feature_row(
    *, run_id: str, symbol: str, market: str, as_of_date: date,
    feature_name: str, inputs: list[pd.Series] | None,
    value: float | None = None, reason: str = "",
) -> dict[str, Any]:
    definition = next(item for item in FEATURE_DEFINITIONS if item["feature_name"] == feature_name)
    rows = inputs or []
    currencies = sorted({str(row["currency"]) for row in rows})
    status = "PASS" if rows and value is not None and np.isfinite(value) else "UNAVAILABLE"
    if status == "UNAVAILABLE" and not reason:
        reason = "NO_PIT_ELIGIBLE_INPUT"
    def dates(column: str) -> list[str]:
        return sorted({pd.Timestamp(row[column]).isoformat() for row in rows if pd.notna(row[column])})
    lineage = [{
        "source_table": str(row["source_table"]), "canonical_name": str(row["canonical_name"]),
        "source_field": str(row["source_field"]), "canonical_key": str(row["canonical_key"]),
        "report_date": pd.Timestamp(row["report_date"]).isoformat(),
        "announcement_date": pd.Timestamp(row["announcement_date"]).isoformat(),
        "update_date": pd.Timestamp(row["update_date"]).isoformat(),
        "fiscal_period": str(row["fiscal_period"]), "currency": str(row["currency"]),
        "source_run_id": str(row["source_run_id"]), "clean_run_id": str(row["clean_run_id"]),
        "source_sha256": str(row["source_sha256"]), "pit_status": str(row["pit_status"]),
    } for row in rows]
    return {
        "run_id": run_id, "symbol": symbol, "market": market,
        "as_of_date": pd.Timestamp(as_of_date), "feature_name": feature_name,
        "feature_value": float(value) if status == "PASS" else np.nan,
        "feature_status": status, "unavailable_reason": "" if status == "PASS" else reason,
        "formula": definition["formula"], "output_unit": definition["output_unit"],
        "period_semantics": definition["period_semantics"],
        "source_report_date": max((pd.Timestamp(row["report_date"]) for row in rows), default=pd.NaT),
        "source_announcement_date": max((pd.Timestamp(row["announcement_date"]) for row in rows), default=pd.NaT),
        "source_update_date": max((pd.Timestamp(row["update_date"]) for row in rows), default=pd.NaT),
        "source_report_dates": json.dumps(dates("report_date"), ensure_ascii=False),
        "source_announcement_dates": json.dumps(dates("announcement_date"), ensure_ascii=False),
        "source_update_dates": json.dumps(dates("update_date"), ensure_ascii=False),
        "source_fields": json.dumps(sorted({str(row["source_field"]) for row in rows}), ensure_ascii=False),
        "source_tables": json.dumps(sorted({str(row["source_table"]) for row in rows}), ensure_ascii=False),
        "source_canonical_keys": json.dumps(sorted({str(row["canonical_key"]) for row in rows}), ensure_ascii=False),
        "source_run_ids": json.dumps(sorted({str(row["source_run_id"]) for row in rows}), ensure_ascii=False),
        "source_clean_run_ids": json.dumps(sorted({str(row["clean_run_id"]) for row in rows}), ensure_ascii=False),
        "source_sha256s": json.dumps(sorted({str(row["source_sha256"]) for row in rows}), ensure_ascii=False),
        "source_currencies": json.dumps(currencies, ensure_ascii=False),
        "source_periods": json.dumps(sorted({str(row["fiscal_period"]) for row in rows}), ensure_ascii=False),
        "lineage_json": json.dumps(lineage, ensure_ascii=False, sort_keys=True),
        "schema_version": "fundamental_feature_long_v1",
    }


def build_features(core: pd.DataFrame, securities: pd.DataFrame, *, run_id: str, as_of_date: date) -> pd.DataFrame:
    index = _row_index(core)
    output: list[dict[str, Any]] = []
    base = {"revenue": "revenue", "net_profit": "net_profit", "total_assets": "total_assets", "total_equity": "net_assets", "operating_cash_flow": "operating_cash_flow"}
    for security in securities.to_dict("records"):
        symbol, market = str(security["symbol"]), str(security["market"])
        for feature_name, canonical in base.items():
            rows = index.get((symbol, canonical), [])
            current = rows[0] if rows else None
            output.append(_feature_row(run_id=run_id, symbol=symbol, market=market, as_of_date=as_of_date, feature_name=feature_name, inputs=[current] if current is not None else None, value=float(current["normalized_value"]) if current is not None and pd.notna(current["normalized_value"]) else None))
        for feature_name, canonical in (("revenue_yoy", "revenue"), ("net_profit_yoy", "net_profit")):
            rows = index.get((symbol, canonical), [])
            current = rows[0] if rows else None
            prior = _prior_comparable(rows, current) if current is not None else None
            reason = "PRIOR_COMPARABLE_PERIOD_UNAVAILABLE" if current is not None and prior is None else "NO_PIT_ELIGIBLE_INPUT"
            value = None
            inputs = [row for row in (current, prior) if row is not None]
            if current is not None and prior is not None:
                if str(current["currency"]) != str(prior["currency"]): reason = "MIXED_CURRENCY"
                elif float(prior["normalized_value"]) == 0: reason = "DIVISION_BY_ZERO"
                else: value = float(current["normalized_value"]) / float(prior["normalized_value"]) - 1.0
            output.append(_feature_row(run_id=run_id, symbol=symbol, market=market, as_of_date=as_of_date, feature_name=feature_name, inputs=inputs, value=value, reason=reason))
        ratio_specs = (("net_margin", "net_profit", "revenue"), ("debt_to_asset", "total_liabilities", "total_assets"), ("ocf_to_net_profit", "operating_cash_flow", "net_profit"))
        for feature_name, numerator, denominator in ratio_specs:
            pair = _same_date(index.get((symbol, numerator), []), index.get((symbol, denominator), []))
            value = None; reason = "NO_COMMON_PIT_REPORT_PERIOD"; inputs = list(pair) if pair else []
            if pair:
                left, right = pair
                if str(left["currency"]) != str(right["currency"]): reason = "MIXED_CURRENCY"
                elif float(right["normalized_value"]) == 0: reason = "DIVISION_BY_ZERO"
                else: value = float(left["normalized_value"]) / float(right["normalized_value"])
            output.append(_feature_row(run_id=run_id, symbol=symbol, market=market, as_of_date=as_of_date, feature_name=feature_name, inputs=inputs, value=value, reason=reason))
        for feature_name, numerator, denominator in (("roa", "net_profit", "total_assets"), ("roe", "parent_net_profit", "parent_equity")):
            annual_num = [row for row in index.get((symbol, numerator), []) if str(row["fiscal_period"]) == "FY"]
            current = annual_num[0] if annual_num else None
            denom_rows = index.get((symbol, denominator), [])
            current_den = next((row for row in denom_rows if current is not None and pd.Timestamp(row["report_date"]) == pd.Timestamp(current["report_date"])), None)
            prior_den = _prior_comparable(denom_rows, current_den) if current_den is not None else None
            inputs = [row for row in (current, current_den, prior_den) if row is not None]
            value = None; reason = "ANNUAL_OR_PRIOR_BALANCE_UNAVAILABLE"
            if current is not None and current_den is not None and prior_den is not None:
                if len({str(row["currency"]) for row in inputs}) != 1: reason = "MIXED_CURRENCY"
                else:
                    average = (float(current_den["normalized_value"]) + float(prior_den["normalized_value"])) / 2.0
                    if average == 0: reason = "DIVISION_BY_ZERO"
                    else: value = float(current["normalized_value"]) / average
            output.append(_feature_row(run_id=run_id, symbol=symbol, market=market, as_of_date=as_of_date, feature_name=feature_name, inputs=inputs, value=value, reason=reason))
    frame = pd.DataFrame(output)
    return frame.sort_values(["market", "symbol", "feature_name"], kind="stable").reset_index(drop=True)


def _validation_reports(features: pd.DataFrame, definitions: pd.DataFrame, config: Stage185Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    failures: list[str] = []
    coverage = features.groupby(["feature_name", "market", "feature_status"], dropna=False).size().rename("row_count").reset_index()
    coverage["status"] = "PASS"
    pass_rows = features[features["feature_status"] == "PASS"]
    lineage = pass_rows["lineage_json"].map(json.loads)
    future_count = sum(any(pd.Timestamp(item["announcement_date"]).date() > config.as_of_date or pd.Timestamp(item["update_date"]).date() > config.as_of_date for item in items) for items in lineage)
    non_pit_count = sum(any(item["pit_status"] != "PIT_ELIGIBLE" for item in items) for items in lineage)
    valuation_leakage = int(pass_rows["source_tables"].str.contains("valuation", regex=False).sum())
    inferred_dates = int(pass_rows["source_announcement_dates"].eq("[]").sum())
    pit = pd.DataFrame([
        {"check_name": "future_data_usage", "expected": 0, "observed": future_count},
        {"check_name": "non_pit_input_usage", "expected": 0, "observed": non_pit_count},
        {"check_name": "announcement_date_inference", "expected": 0, "observed": inferred_dates},
        {"check_name": "current_valuation_leakage", "expected": 0, "observed": valuation_leakage},
    ])
    pit["status"] = np.where(pit["expected"] == pit["observed"], "PASS", "FAIL")
    period_rows = []
    for row in features[features["feature_name"].isin(["revenue_yoy", "net_profit_yoy", "roa", "roe"])].to_dict("records"):
        lineage_items = json.loads(row["lineage_json"])
        periods = sorted({(int(pd.Timestamp(item["report_date"]).year), item["fiscal_period"]) for item in lineage_items})
        valid = row["feature_status"] == "UNAVAILABLE" or (
            len({period for _, period in periods}) == 1
            and max(year for year, _ in periods) - min(year for year, _ in periods) == 1
        )
        period_rows.append({"symbol": row["symbol"], "market": row["market"], "feature_name": row["feature_name"], "feature_status": row["feature_status"], "source_periods": json.dumps(periods), "period_match_status": "PASS" if valid else "FAIL"})
    period = pd.DataFrame(period_rows)
    quality = features[["symbol", "market", "feature_name", "feature_status", "unavailable_reason"]].copy()
    quality["lineage_present"] = features["lineage_json"].ne("[]")
    quality["quality_status"] = np.where(
        ((quality["feature_status"] == "PASS") & quality["lineage_present"] & features["feature_value"].notna())
        | ((quality["feature_status"] == "UNAVAILABLE") & quality["unavailable_reason"].ne("")),
        "PASS", "FAIL",
    )
    checks = {
        "feature_definition_count": len(definitions) == len(FEATURE_NAMES),
        "feature_unit_count": len(features) == config.expected_security_count * len(FEATURE_NAMES),
        "security_coverage": features["symbol"].nunique() == 23,
        "feature_coverage": features["feature_name"].nunique() == len(FEATURE_NAMES),
        "terminal_status_only": set(features["feature_status"]) <= {"PASS", "UNAVAILABLE"},
        "computed_feature_exists": int((features["feature_status"] == "PASS").sum()) > 0,
        "pit_validation": not (pit["status"] == "FAIL").any(),
        "period_matching": not (period["period_match_status"] == "FAIL").any(),
        "feature_quality": not (quality["quality_status"] == "FAIL").any(),
    }
    failures.extend(name for name, ok in checks.items() if not ok)
    summary = pd.DataFrame([{"check_name": name, "status": "PASS" if ok else "FAIL"} for name, ok in checks.items()])
    quality = pd.concat([quality, pd.DataFrame([{"symbol": "__RUN__", "market": "ALL", "feature_name": row["check_name"], "feature_status": row["status"], "unavailable_reason": "", "lineage_present": True, "quality_status": row["status"]} for row in summary.to_dict("records")])], ignore_index=True)
    return coverage, pit, period, quality, failures


def run_stage18_5(
    *, root: str | Path | None = None, config_path: str | Path = "config/stage18_5.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], int]:
    project_root = Path(root or Path.cwd()).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute(): config_file = project_root / config_file
    config = load_stage18_5_config(config_file)
    if as_of_date != config.as_of_date:
        raise Stage18Blocked("Stage 18.5 as-of date differs from frozen configuration")
    if upstream_run_id is not None and upstream_run_id != config.source_run_id:
        raise Stage18Blocked("Stage 18.5 upstream run id differs from the sole formal Stage 18.4 run")
    stage0_before = frozen_hashes(project_root)
    upstream_before = _upstream_fingerprint(project_root, config)
    protected_before = _protected_state(project_root, config)
    core, securities = _load_pit_inputs(project_root / config.database_path, config.as_of_date)
    if validate_only or dry_run:
        return ({"stage": 18, "substage": "18.5", "status": "VALIDATED" if validate_only else "DRY_RUN", "upstream": upstream_before, "pit_input_rows": len(core), "feature_writes": 0}, 0)
    active_run = run_id or str(uuid.uuid4())
    try: uuid.UUID(active_run)
    except ValueError as exc: raise Stage18Blocked("Stage 18.5 run_id must be a UUID") from exc
    report_dir = project_root / config.reports_root / active_run
    feature_dir = project_root / config.feature_root / f"run_id={active_run}"
    if report_dir.exists() or feature_dir.exists():
        raise Stage18Blocked("Stage 18.5 run/report or feature path already exists; append-only policy blocks overwrite")
    report_dir.mkdir(parents=True, exist_ok=False)
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now().astimezone(timezone.utc).isoformat()
    features = build_features(core, securities, run_id=active_run, as_of_date=config.as_of_date)
    definitions = pd.DataFrame(FEATURE_DEFINITIONS)
    coverage, pit, period, quality, failures = _validation_reports(features, definitions, config)
    for name, frame in (("feature_definition.csv", definitions), ("feature_coverage.csv", coverage), ("pit_feature_validation.csv", pit), ("period_matching_validation.csv", period), ("feature_quality.csv", quality)):
        _atomic_csv(report_dir / name, frame, must_not_exist=True)
    stored = Stage18FeatureStore(project_root / config.feature_root).write(
        run_id=active_run, frame=features,
        metadata={"stage": 18, "substage": "18.5", "run_id": active_run, "status": "PASS" if not failures else "BLOCKED", "asset_role": "fundamental_feature", "analysis_as_of_date": config.as_of_date.isoformat(), "source_stage18_4_run_id": config.source_run_id, "source_database_sha256": config.database_sha256, "valuation_snapshot_used": False, "writes_database": False, "writes_stage19": False, "schema_version": "fundamental_feature_long_v1"},
    )
    stage0_after = frozen_hashes(project_root)
    upstream_after = _upstream_fingerprint(project_root, config)
    protected_after = _protected_state(project_root, config)
    if stage0_before != stage0_after: failures.append("stage0_frozen_hashes_changed")
    if upstream_before != upstream_after: failures.append("stage18_4_upstream_changed")
    if protected_before != protected_after: failures.append("protected_assets_changed")
    stage19_count = sum(1 for path in (project_root / "data/raw/stage19", project_root / "reports/stage19") if path.exists() for item in path.rglob("*") if item.is_file())
    if stage19_count: failures.append("stage19_assets_exist")
    residuals = [item for item in feature_dir.rglob("*") if item.name.endswith((".tmp", ".wal"))]
    if residuals: failures.append("temporary_residuals")
    status = "PASS" if not failures else "BLOCKED"
    pass_count = int((features["feature_status"] == "PASS").sum())
    unavailable_count = int((features["feature_status"] == "UNAVAILABLE").sum())
    run_report = {"stage": 18, "substage": "18.5", "run_id": active_run, "status": status, "stage18_5_status": status, "started_at": started_at, "finished_at": now().astimezone(timezone.utc).isoformat(), "analysis_as_of_date": config.as_of_date.isoformat(), "upstream_stage18_4_run_id": config.source_run_id, "source_database_path": config.database_path.as_posix(), "source_database_sha256": config.database_sha256, "pit_input_row_count": int(len(core)), "security_count": int(features["symbol"].nunique()), "feature_definition_count": len(definitions), "feature_unit_count": len(features), "feature_pass_count": pass_count, "feature_unavailable_count": unavailable_count, "feature_fail_count": 0, "feature_blocked_count": 0, "future_data_usage_count": int(pit.loc[pit["check_name"] == "future_data_usage", "observed"].iloc[0]), "announcement_date_inference_count": int(pit.loc[pit["check_name"] == "announcement_date_inference", "observed"].iloc[0]), "valuation_leakage_count": int(pit.loc[pit["check_name"] == "current_valuation_leakage", "observed"].iloc[0]), "period_mismatch_count": int((period["period_match_status"] == "FAIL").sum()), "feature_data_path": stored["data_path"].relative_to(project_root).as_posix(), "feature_data_sha256": stored["data_sha256"], "stage0_hashes_unchanged": stage0_before == stage0_after, "protected_assets_unchanged": protected_before == protected_after, "upstream_evidence_unchanged": upstream_before == upstream_after, "stage19_asset_count": stage19_count, "tmp_residual_count": len(residuals), "blockers": failures, "stage18_6_authorized": status == "PASS", "stage18_6_started": False, "known_test_debt": {"node_id": "tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset", "signature": "expected returncode 1, observed returncode 0"}}
    run_path = report_dir / "stage18_5_run.json"
    _atomic_text(run_path, json.dumps(run_report, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    artifacts = [stored["data_path"], stored["metadata_path"], config_file, run_path] + [report_dir / name for name in ("feature_definition.csv", "feature_coverage.csv", "pit_feature_validation.csv", "period_matching_validation.csv", "feature_quality.csv")]
    records = [file_record(path, project_root) for path in artifacts]
    manifest = {"stage": 18, "substage": "18.5", "run_id": active_run, "status": status, "upstream_stage18_4_run_id": config.source_run_id, "feature_asset": {"path": stored["data_path"].relative_to(project_root).as_posix(), "row_count": len(features), "sha256": stored["data_sha256"]}, "files": records, "manifest_closed_world": status == "PASS"}
    manifest_path = report_dir / "stage18_5_manifest.json"
    _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
    _verify_records(project_root, records, size_key="size")
    if file_sha256(project_root / config.database_path) != config.database_sha256:
        raise Stage18Blocked("Stage 18.4 database changed during Stage 18.5")
    return run_report, 0 if status == "PASS" else 1
