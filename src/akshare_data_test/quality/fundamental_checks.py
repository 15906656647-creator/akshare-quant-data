"""Fail-closed Stage 10 financial and valuation quality checks."""
from __future__ import annotations

import json
import math
from numbers import Number
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from ..storage.fundamental_repository import QUALITY_COLUMNS


FLOAT_TOLERANCE = 1e-12
SUMMARY_COMPARE_COLUMNS = [
    "run_id", "symbol", "as_of_date", "revenue_growth", "profit_growth",
    "profitability_score", "financial_health_score", "valuation_status",
    "summary_explanation", "model_version", "config_version", "publication_status",
]
INDICATOR_VALUE_COLUMNS = [
    "revenue", "net_profit", "roe", "gross_margin", "net_margin",
    "asset_liability_ratio", "cashflow_profit_ratio",
]
INDICATOR_COMPARE_COLUMNS = [
    "run_id", "symbol", "report_period", *INDICATOR_VALUE_COLUMNS,
]
VALUATION_COMPARE_COLUMNS = [
    "run_id", "symbol", "snapshot_time", "pe", "pb", "market_cap",
    "valuation_status",
]
QUALITY_COMPARE_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "message",
]


def indicator_report_projection(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the stable wide indicator projection used by reports and QA."""
    if frame.empty:
        return pd.DataFrame(columns=INDICATOR_COMPARE_COLUMNS)
    projected = frame.loc[
        frame["indicator_code"].isin(INDICATOR_VALUE_COLUMNS),
        ["run_id", "symbol", "report_period", "indicator_code", "indicator_value"],
    ]
    wide = projected.pivot(
        index=["run_id", "symbol", "report_period"],
        columns="indicator_code", values="indicator_value",
    ).reset_index()
    wide.columns.name = None
    for column in INDICATOR_VALUE_COLUMNS:
        if column not in wide:
            wide[column] = np.nan
    return wide[INDICATOR_COMPARE_COLUMNS].sort_values(
        ["run_id", "symbol", "report_period"], kind="mergesort"
    ).reset_index(drop=True)


def _normal_scalar(value: object) -> object:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, Number) and not isinstance(value, bool):
        number = float(value)
        if math.isnan(number):
            return None
        if not math.isfinite(number):
            return ("non_finite", str(number))
        return number
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _values_equal(left: object, right: object) -> bool:
    left_value, right_value = _normal_scalar(left), _normal_scalar(right)
    if left_value is None or right_value is None:
        return left_value is None and right_value is None
    if isinstance(left_value, Number) and isinstance(right_value, Number):
        return math.isclose(
            float(left_value), float(right_value), rel_tol=0,
            abs_tol=FLOAT_TOLERANCE,
        )
    return left_value == right_value


def _compare_frames(
    database: pd.DataFrame, artifact: pd.DataFrame, *, columns: list[str],
    sort_by: list[str], date_columns: tuple[str, ...] = (),
    timestamp_columns: tuple[str, ...] = (),
) -> tuple[bool, str]:
    missing_database = sorted(set(columns).difference(database.columns))
    missing_artifact = sorted(set(columns).difference(artifact.columns))
    if missing_database or missing_artifact:
        return False, f"missing_db={missing_database};missing_artifact={missing_artifact}"
    left, right = database[columns].copy(), artifact[columns].copy()
    for frame in (left, right):
        for column in date_columns:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            frame[column] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), None)
        for column in timestamp_columns:
            parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
            frame[column] = parsed.dt.strftime("%Y-%m-%dT%H:%M:%S.%f%z").where(parsed.notna(), None)
        if "symbol" in frame:
            frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    left = left.sort_values(sort_by, kind="mergesort", na_position="first").reset_index(drop=True)
    right = right.sort_values(sort_by, kind="mergesort", na_position="first").reset_index(drop=True)
    if len(left) != len(right):
        return False, f"row_count={len(left)}/{len(right)}"
    for index in range(len(left)):
        for column in columns:
            if not _values_equal(left.at[index, column], right.at[index, column]):
                return False, f"mismatch_row={index};column={column}"
    return True, f"rows={len(left)}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(
    run_id: str, name: str, passed: bool, observed: Any, expected: Any,
    checked_at: pd.Timestamp, *, severity: str = "ERROR", numerator: int | None = None,
    denominator: int | None = None, message: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id, "check_name": name, "severity": severity,
        "status": "PASS" if passed else "FAIL", "observed_value": str(observed),
        "expected_value": str(expected), "numerator": numerator,
        "denominator": denominator, "message": message, "checked_at": checked_at,
    }


def run_stage10_quality_checks(
    raw: pd.DataFrame, facts: pd.DataFrame, indicators: pd.DataFrame,
    summaries: pd.DataFrame, valuations: pd.DataFrame, *, run_id: str,
    as_of_date: pd.Timestamp, expected_symbols: list[str], config: dict[str, Any],
    checked_at: pd.Timestamp,
) -> pd.DataFrame:
    """Run measured checks; every failed ERROR is a publication blocker."""
    rows: list[dict[str, Any]] = []
    add = lambda name, passed, observed, expected, **kw: rows.append(
        _row(run_id, name, passed, observed, expected, checked_at, **kw)
    )
    required_raw = {
        "symbol", "report_period", "announcement_date", "update_time", "source_name",
        "source_reference", "source_unit", "cumulative_flag", "version", "run_id",
    }
    missing_schema = sorted(required_raw.difference(raw.columns))
    add("input_schema_complete", not missing_schema, missing_schema, [])
    actual_items = set(facts["item_code"].dropna().astype(str))
    missing_items = sorted(set(config["required_items"]).difference(actual_items))
    add("required_financial_fields_present", not missing_items, missing_items, [])
    missing_by_symbol = {
        symbol: sorted(
            set(config["required_items"]).difference(
                set(facts.loc[facts.symbol.eq(symbol), "item_code"].dropna().astype(str))
            )
        )
        for symbol in expected_symbols
    }
    missing_by_symbol = {
        symbol: missing for symbol, missing in missing_by_symbol.items() if missing
    }
    add("required_financial_fields_present_per_symbol", not missing_by_symbol, missing_by_symbol, {})
    units_by_item = facts.groupby("item_code")["unit"].nunique(dropna=False) if not facts.empty else pd.Series(dtype=int)
    mixed_units = sorted(units_by_item[units_by_item.gt(1)].index.astype(str))
    add("financial_units_consistent", not mixed_units, mixed_units, [])
    alias_conflicts = int(facts["conflict_flag"].fillna(False).sum())
    alias_mismatches = int(facts["conflict_value_mismatch"].fillna(False).sum())
    add(
        "financial_alias_conflicts_tracked", True, alias_conflicts,
        "priority-selected facts with raw candidates retained", severity="WARNING",
    )
    add(
        "financial_alias_values_consistent", alias_mismatches == 0,
        alias_mismatches, 0, severity="WARNING", numerator=alias_mismatches,
        denominator=max(alias_conflicts, 1),
        message="Differing alias values are recorded; selection remains deterministic",
    )
    duplicate_key = ["symbol", "statement_type", "report_period", "item_code", "version_key"]
    duplicates = int(facts.duplicated(duplicate_key).sum()) if set(duplicate_key).issubset(facts.columns) else -1
    add("report_versions_unique", duplicates == 0, duplicates, 0)
    announcement = pd.to_datetime(facts["announcement_date"], errors="coerce")
    periods = pd.to_datetime(facts["report_period"], errors="coerce")
    unreasonable = int(((announcement.notna()) & ((announcement < periods) | (announcement > pd.Timestamp(as_of_date)))).sum())
    add("announcement_dates_reasonable", unreasonable == 0, unreasonable, 0)
    numeric = pd.to_numeric(facts["item_value"], errors="coerce")
    nonfinite = int(np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).sum())
    add("financial_amounts_finite", nonfinite == 0, nonfinite, 0)
    conversion_failures = int(
        (facts["cumulative_flag"] & facts["conversion_status"].eq("pending")).sum()
    )
    add("single_quarter_conversion_complete", conversion_failures == 0, conversion_failures, 0)
    missing_prior = int(facts["conversion_status"].eq("missing_prior_cumulative").sum())
    add(
        "single_quarter_missing_prior_explicit", True, missing_prior,
        "preserved as null with explicit status", severity="WARNING",
    )
    indicator_duplicates = int(indicators.duplicated(["symbol", "report_period", "indicator_code"]).sum())
    add("indicator_keys_unique", indicator_duplicates == 0, indicator_duplicates, 0)
    latest_facts = facts.copy()
    latest_facts["_announcement"] = pd.to_datetime(latest_facts["announcement_date"], errors="coerce")
    latest_facts = latest_facts.sort_values(
        ["symbol", "item_code", "report_period", "_announcement", "version"],
        kind="mergesort", na_position="first",
    ).drop_duplicates(["symbol", "item_code", "report_period"], keep="last")

    def fact_value(symbol: str, period: pd.Timestamp, code: str) -> float | None:
        match = latest_facts.loc[
            latest_facts.symbol.eq(symbol)
            & latest_facts.report_period.eq(pd.Timestamp(period))
            & latest_facts.item_code.eq(code),
            "single_quarter_value",
        ]
        if match.empty or pd.isna(match.iloc[-1]):
            return None
        return float(match.iloc[-1])

    ttm_mismatches = 0
    ttm_sources = {
        "revenue_ttm": ("revenue",),
        "net_profit_ttm": ("parent_net_profit", "net_profit"),
        "operating_cashflow_ttm": ("operating_cashflow",),
    }
    for row in indicators.loc[
        indicators.indicator_code.isin(ttm_sources) & indicators.calculation_status.eq("calculated")
    ].itertuples():
        periods_for_ttm = list(pd.date_range(end=pd.Timestamp(row.report_period), periods=4, freq="QE"))
        expected_ttm = None
        for source_code in ttm_sources[row.indicator_code]:
            observed = [fact_value(row.symbol, period, source_code) for period in periods_for_ttm]
            if all(value is not None for value in observed):
                expected_ttm = float(sum(observed))
                break
        if expected_ttm is None or pd.isna(row.indicator_value) or not np.isclose(
            float(row.indicator_value), expected_ttm, rtol=0, atol=1e-12
        ):
            ttm_mismatches += 1
    add("ttm_calculation_consistent", ttm_mismatches == 0, ttm_mismatches, 0)

    yoy_mismatches = 0
    yoy_sources = {"revenue_yoy": "revenue", "net_profit_yoy": "parent_net_profit"}
    for row in indicators.loc[
        indicators.indicator_code.isin(yoy_sources) & indicators.calculation_status.eq("calculated")
    ].itertuples():
        current_period = pd.Timestamp(row.report_period)
        prior_period = current_period - pd.DateOffset(years=1)
        current_value = fact_value(row.symbol, current_period, yoy_sources[row.indicator_code])
        prior_value = fact_value(row.symbol, prior_period, yoy_sources[row.indicator_code])
        expected_yoy = (
            (current_value - prior_value) / abs(prior_value)
            if current_value is not None and prior_value not in (None, 0) else None
        )
        if expected_yoy is None or pd.isna(row.indicator_value) or not np.isclose(
            float(row.indicator_value), expected_yoy, rtol=0, atol=1e-12
        ):
            yoy_mismatches += 1
    add("yoy_calculation_consistent", yoy_mismatches == 0, yoy_mismatches, 0)
    for code, bounds in config.get("ratio_ranges", {}).items():
        values = pd.to_numeric(
            indicators.loc[indicators.indicator_code.eq(code), "indicator_value"], errors="coerce"
        ).dropna()
        invalid = int((~values.between(float(bounds[0]), float(bounds[1]))).sum())
        add(f"{code}_range_valid", invalid == 0, invalid, 0)
    run_ids: set[str] = set()
    for frame in (raw, facts, indicators, summaries, valuations):
        if not frame.empty:
            run_ids.update(frame["run_id"].astype(str))
    add("run_id_consistent", run_ids == {run_id}, sorted(run_ids), [run_id])
    actual_symbols = set(summaries["symbol"].astype(str).str.zfill(6))
    expected = set(expected_symbols)
    add(
        "symbol_coverage_complete", actual_symbols == expected,
        sorted(actual_symbols), sorted(expected), numerator=len(actual_symbols & expected),
        denominator=len(expected),
    )
    invalid_types = sorted(set(valuations["valuation_type"].astype(str)).difference({"snapshot"}))
    add("valuation_snapshot_historical_separated", not invalid_types, invalid_types, [])
    negative_pe_unmarked = int((valuations["pe"].le(0) & valuations["pe_status"].ne("loss-making")).sum())
    add("negative_pe_marked_loss_making", negative_pe_unmarked == 0, negative_pe_unmarked, 0)
    missing_pe_filled = int((valuations["pe_status"].eq("unavailable") & valuations["pe"].notna()).sum())
    add("missing_pe_not_filled", missing_pe_filled == 0, missing_pe_filled, 0)
    missing_pb_filled = int((valuations["pb_status"].eq("unavailable") & valuations["pb"].notna()).sum())
    add("missing_pb_not_filled", missing_pb_filled == 0, missing_pb_filled, 0)
    zero_pb = int(valuations["pb"].eq(0).sum())
    add("zero_pb_not_treated_as_available", int((valuations["pb"].eq(0) & valuations["pb_status"].eq("available")).sum()) == 0, zero_pb, "zero is invalid or absent")
    prohibited = int(summaries["summary_explanation"].str.contains("买入|卖出|必涨|低估|主力正在", regex=True).sum())
    add("no_investment_advice", prohibited == 0, prohibited, 0)
    sensitive = int(
        raw["source_reference"].astype(str).str.contains(
            r"(?i)(?:api[_-]?key|password|passwd|cookie|authorization|proxy://)", regex=True
        ).sum()
    )
    add("sensitive_information_absent", sensitive == 0, sensitive, 0)
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def verify_stage10_persistence(
    database_path: Path, reports_dir: Path, *, run_id: str,
    expected_counts: dict[str, int], checked_at: pd.Timestamp,
) -> pd.DataFrame:
    """Cross-check every published field across DuckDB and report artifacts."""
    passed = False
    detail = "not checked"
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            counts = {
                "raw": connection.execute("SELECT count(*) FROM raw.financial_statement WHERE run_id=?", [run_id]).fetchone()[0],
                "facts": connection.execute("SELECT count(*) FROM clean.financial_fact WHERE run_id=?", [run_id]).fetchone()[0],
                "indicators": connection.execute("SELECT count(*) FROM feature.fundamental_indicator WHERE run_id=?", [run_id]).fetchone()[0],
                "summaries": connection.execute("SELECT count(*) FROM analysis.fundamental_summary WHERE run_id=?", [run_id]).fetchone()[0],
                "valuations": connection.execute("SELECT count(*) FROM analysis.valuation_snapshot WHERE run_id=?", [run_id]).fetchone()[0],
            }
            database_runs = {
                row[0] for row in connection.execute(
                    "SELECT DISTINCT run_id FROM analysis.fundamental_summary"
                ).fetchall()
            }
            db_summaries = connection.execute(
                "SELECT * FROM analysis.fundamental_summary WHERE run_id=?", [run_id]
            ).fetchdf()
            db_indicators = connection.execute(
                "SELECT * FROM feature.fundamental_indicator WHERE run_id=?", [run_id]
            ).fetchdf()
            db_valuations = connection.execute(
                "SELECT * FROM analysis.valuation_snapshot WHERE run_id=?", [run_id]
            ).fetchdf()
            db_quality = connection.execute(
                "SELECT * FROM quality.stage10_quality_result WHERE run_id=?", [run_id]
            ).fetchdf()
            audit_frame = connection.execute(
                "SELECT * FROM audit.stage10_run WHERE run_id=?", [run_id]
            ).fetchdf()
        summary_csv = pd.read_csv(
            reports_dir / "stage10_fundamental_summary.csv",
            dtype={"run_id": str, "symbol": str},
        )
        indicator_csv = pd.read_csv(
            reports_dir / "stage10_fundamental_indicator.csv",
            dtype={"run_id": str, "symbol": str},
        )
        valuation_csv = pd.read_csv(
            reports_dir / "stage10_valuation_snapshot.csv",
            dtype={"run_id": str, "symbol": str},
        )
        quality_csv = pd.read_csv(
            reports_dir / "stage10_data_quality.csv", dtype={"run_id": str},
            keep_default_na=False,
        )
        run_payload = json.loads(
            (reports_dir / "stage10_run.json").read_text(encoding="utf-8")
        )
        markdown = (reports_dir / "stage10_validation.md").read_text(encoding="utf-8")
        summary_match, summary_detail = _compare_frames(
            db_summaries, summary_csv, columns=SUMMARY_COMPARE_COLUMNS,
            sort_by=["run_id", "symbol", "as_of_date"], date_columns=("as_of_date",),
        )
        indicator_match, indicator_detail = _compare_frames(
            indicator_report_projection(db_indicators), indicator_csv,
            columns=INDICATOR_COMPARE_COLUMNS,
            sort_by=["run_id", "symbol", "report_period"],
            date_columns=("report_period",),
        )
        valuation_match, valuation_detail = _compare_frames(
            db_valuations, valuation_csv, columns=VALUATION_COMPARE_COLUMNS,
            sort_by=["run_id", "symbol", "snapshot_time"],
            timestamp_columns=("snapshot_time",),
        )
        quality_match, quality_detail = _compare_frames(
            db_quality, quality_csv, columns=QUALITY_COMPARE_COLUMNS,
            sort_by=["run_id", "check_name"],
        )
        if len(audit_frame) != 1:
            raise ValueError(f"audit_row_count={len(audit_frame)}")
        audit = audit_frame.iloc[0]
        stored_manifest = json.loads(audit["manifest_json"])
        stored_blockers = json.loads(audit["blocking_reasons_json"])
        manifest_match = (
            _canonical_json(run_payload) == _canonical_json(stored_manifest)
            and run_payload.get("run_id") == run_id == audit["run_id"]
            and run_payload.get("run_status") == audit["run_status"]
            and run_payload.get("publication_status") == audit["publication_status"]
            and run_payload.get("summary_count") == counts["summaries"] == audit["summary_row_count"]
            and run_payload.get("indicator_count") == counts["indicators"] == audit["indicator_row_count"]
            and run_payload.get("quality_passed") == audit["quality_passed"]
            and run_payload.get("quality_failed") == audit["quality_failed"]
            and run_payload.get("blocking_reasons") == stored_blockers
            and run_payload.get("config_hash") == audit["config_hash"]
        )
        from ..stage10_build import render_stage10_validation
        markdown_match = (
            markdown.replace("\r\n", "\n")
            == render_stage10_validation(run_payload).replace("\r\n", "\n")
        )
        passed = (
            counts == expected_counts
            and run_id in database_runs
            and summary_match and indicator_match and valuation_match
            and quality_match and manifest_match and markdown_match
        )
        detail = (
            f"counts={counts};summary={summary_match}:{summary_detail};"
            f"indicator={indicator_match}:{indicator_detail};"
            f"valuation={valuation_match}:{valuation_detail};"
            f"quality={quality_match}:{quality_detail};"
            f"manifest={manifest_match};markdown={markdown_match}"
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError, duckdb.Error) as exc:
        detail = f"{type(exc).__name__}: {exc}"
    forbidden = [
        path.name for path in reports_dir.rglob("*") if path.is_file()
        and path.suffix.lower() in {".duckdb", ".db", ".sqlite", ".wal", ".log", ".parquet"}
    ]
    return pd.DataFrame([
        _row(run_id, "database_report_consistent", passed, detail, expected_counts, checked_at),
        _row(run_id, "forbidden_file_check", not forbidden, forbidden, [], checked_at),
    ], columns=QUALITY_COLUMNS)
