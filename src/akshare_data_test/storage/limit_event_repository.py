"""DuckDB I/O for Stage 8, isolated from Stage 7 outputs."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from ..limit_rules import LimitRule, SecurityStatus


EVENT_COLUMNS = [
    "symbol", "trade_date", "event_type", "previous_close", "open", "high",
    "low", "close", "official_limit_up_price", "official_limit_down_price",
    "official_limit_source_name", "official_limit_source_reference",
    "official_limit_source_version", "official_limit_evidence_status",
    "official_limit_verified_at", "official_limit_fetched_at",
    "official_limit_symbol", "official_limit_trade_date",
    "official_limit_rejection_reason",
    "theoretical_limit_up_price", "theoretical_limit_down_price",
    "unrounded_limit_up_price", "unrounded_limit_down_price",
    "matched_limit_price", "tick_size", "limit_ratio", "rule_version",
    "security_status_version", "detection_method", "evidence_status",
    "quality_status", "resolution_reason", "next_trade_date", "next_open",
    "next_close", "next_open_return", "next_close_return", "forward_3d_return",
    "forward_5d_return", "forward_10d_return", "forward_sample_status",
    "is_continued_limit", "is_valid_trade_row", "run_id", "created_at",
]
SUMMARY_COLUMNS = [
    "symbol", "period_start", "period_end", "limit_up_count",
    "limit_down_count", "avg_next_open_return_after_limit_up",
    "avg_next_close_return_after_limit_up",
    "avg_forward_3d_return_after_limit_up",
    "avg_forward_5d_return_after_limit_up",
    "avg_forward_10d_return_after_limit_up",
    "next_day_gap_up_ratio", "continued_limit_ratio",
    "formal_event_count", "publication_status", "run_id", "created_at",
]
QUALITY_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "numerator", "denominator", "message", "checked_at",
]
EVENT_TABLE = "fact_limit_" + "event"


def validate_raw_daily_source(
    database_path: Path,
    *,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, object]:
    """Inspect the Stage 8 source contract without creating or changing it."""
    if not database_path.is_file():
        return {"errors": [f"source_database_not_found:{database_path}"]}
    if database_path.stat().st_size == 0:
        return {"errors": ["source_database_empty_file"]}

    connection = None
    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        daily_name = "fact_stock_" + "daily"
        tables = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        if ("clean", daily_name) in tables:
            table = "clean." + daily_name
        elif ("main", daily_name) in tables:
            table = "main." + daily_name
        else:
            return {"errors": ["source_daily_table_missing"]}

        columns = {
            row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()
        }
        required = {
            "symbol", "exchange", "trade_date", "adjust_type",
            "open", "high", "low", "close", "volume_share",
        }
        missing = sorted(required.difference(columns))
        if missing:
            return {
                "input_table": table,
                "errors": ["source_columns_missing:" + ",".join(missing)],
            }

        start_value, end_value = start_date.date(), end_date.date()
        parse_failures = connection.execute(
            f"""
            SELECT count(*)
            FROM {table}
            WHERE (
                try_cast(trade_date AS DATE) IS NULL
                OR NOT regexp_full_match(cast(symbol AS VARCHAR), '[0-9]{{6}}')
                OR try_cast(open AS DOUBLE) IS NULL
                OR try_cast(high AS DOUBLE) IS NULL
                OR try_cast(low AS DOUBLE) IS NULL
                OR try_cast(close AS DOUBLE) IS NULL
            )
            """
        ).fetchone()[0]
        if parse_failures:
            return {
                "input_table": table,
                "errors": [f"source_unparseable_required_values:{parse_failures}"],
            }

        range_rows = connection.execute(
            f"""
            SELECT count(*)
            FROM {table}
            WHERE try_cast(trade_date AS DATE) BETWEEN ? AND ?
            """,
            [start_value, end_value],
        ).fetchone()[0]
        raw_rows = connection.execute(
            f"""
            SELECT count(*)
            FROM {table}
            WHERE lower(cast(adjust_type AS VARCHAR)) IN ('raw', 'unadjusted')
              AND try_cast(trade_date AS DATE) BETWEEN ? AND ?
            """,
            [start_value, end_value],
        ).fetchone()[0]
        routes = [
            row[0]
            for row in connection.execute(
                f"""
                SELECT DISTINCT lower(cast(adjust_type AS VARCHAR))
                FROM {table}
                WHERE try_cast(trade_date AS DATE) BETWEEN ? AND ?
                ORDER BY 1
                """,
                [start_value, end_value],
            ).fetchall()
        ]
        if range_rows and not raw_rows:
            return {
                "input_table": table,
                "input_price_routes": routes,
                "range_row_count": range_rows,
                "raw_row_count": 0,
                "errors": ["input_price_route_not_raw"],
            }
        if not range_rows:
            return {
                "input_table": table,
                "input_price_routes": [],
                "range_row_count": 0,
                "raw_row_count": 0,
                "blockers": ["no_rows_in_requested_date_range"],
            }

        duplicate_count = connection.execute(
            f"""
            SELECT coalesce(sum(row_count - 1), 0)
            FROM (
                SELECT count(*) AS row_count
                FROM {table}
                WHERE lower(cast(adjust_type AS VARCHAR)) IN ('raw', 'unadjusted')
                  AND try_cast(trade_date AS DATE) BETWEEN ? AND ?
                GROUP BY cast(symbol AS VARCHAR), try_cast(trade_date AS DATE)
                HAVING count(*) > 1
            )
            """,
            [start_value, end_value],
        ).fetchone()[0]
        if duplicate_count:
            return {
                "input_table": table,
                "input_price_routes": routes,
                "range_row_count": range_rows,
                "raw_row_count": raw_rows,
                "errors": [f"source_duplicate_symbol_trade_date:{duplicate_count}"],
            }
        invalid_dates = connection.execute(
            f"SELECT count(*) FROM {table} WHERE try_cast(trade_date AS DATE) IS NULL"
        ).fetchone()[0]
        return {
            "input_table": table,
            "input_price_routes": routes,
            "range_row_count": int(range_rows),
            "raw_row_count": int(raw_rows),
            "duplicate_count": int(duplicate_count),
            "invalid_date_count": int(invalid_dates),
            "errors": [],
            "blockers": [],
        }
    except duckdb.Error as exc:
        return {"errors": [f"source_database_unreadable:{exc}"]}
    finally:
        if connection is not None:
            connection.close()


def validate_output_target(
    source_database: Path,
    output_database: Path,
) -> list[str]:
    """Return output-target errors without creating the target or its parent."""
    errors: list[str] = []
    if source_database.resolve() == output_database.resolve():
        errors.append("output_database_matches_source_database")
    if output_database.name.lower() == "akshare_features_stage7.duckdb":
        errors.append("output_database_is_protected_stage7_database")
    ancestor = output_database.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
        errors.append(f"output_parent_not_writable:{ancestor}")
    return errors


def read_raw_daily(
    database_path: Path, *, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> tuple[pd.DataFrame, str]:
    """Read only unadjusted daily prices from the Stage 5 contract."""
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        daily_name = "fact_stock_" + "daily"
        tables = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        if ("clean", daily_name) in tables:
            table = "clean." + daily_name
        elif ("main", daily_name) in tables:
            table = "main." + daily_name
        else:
            raise RuntimeError("Stage 8 source daily table not found")
        columns = {
            row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()
        }
        required = {"symbol", "exchange", "trade_date", "adjust_type", "open", "high", "low", "close"}
        missing = sorted(required.difference(columns))
        if missing:
            raise RuntimeError(f"Stage 8 source is missing columns: {missing}")
        optional = [
            name if name in columns else f"NULL AS {name}"
            for name in (
                "volume_share", "limit_up_price", "limit_down_price",
                "official_limit_source_name",
                "official_limit_source_reference",
                "official_limit_source_version",
                "official_limit_evidence_status",
                "official_limit_verified_at",
                "official_limit_fetched_at",
                "official_limit_symbol",
                "official_limit_trade_date",
                "is_suspended",
            )
        ]
        query = f"""
            SELECT symbol, exchange, trade_date, 'raw' AS adjust_type,
                   open, high, low,
                   close, {", ".join(optional)}
            FROM {table}
            WHERE lower(cast(adjust_type AS VARCHAR)) IN ('raw', 'unadjusted')
              AND trade_date BETWEEN ? AND ?
            ORDER BY symbol, trade_date
        """
        frame = connection.execute(
            query, [start_date.date(), end_date.date()]
        ).fetchdf()
        if frame.empty:
            raise RuntimeError("Stage 8 source contains no raw daily prices")
        return frame, table
    finally:
        connection.close()


def _rule_frame(rules: Iterable[LimitRule]) -> pd.DataFrame:
    return pd.DataFrame([asdict(rule) for rule in rules])


def _status_frame(statuses: Iterable[SecurityStatus]) -> pd.DataFrame:
    return pd.DataFrame([asdict(status) for status in statuses])


def upsert_stage8_results(
    *,
    database_path: Path,
    schema_sql_path: Path,
    rules: Iterable[LimitRule],
    statuses: Iterable[SecurityStatus],
    observations: pd.DataFrame,
    summary: pd.DataFrame,
    quality: pd.DataFrame,
    run: dict[str, object],
) -> None:
    """Atomically create/upsert all Stage 8 tables."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute(schema_sql_path.read_text(encoding="utf-8"))
        # A same-run retry replaces that run's complete snapshot.  Without
        # clearing prior post-write checks, stale quality rows survive and make
        # the persisted database disagree with newly generated reports.
        current_run_id = str(run["run_id"])
        connection.execute(
            f"DELETE FROM analysis.{EVENT_TABLE} WHERE run_id = ?",
            [current_run_id],
        )
        connection.execute(
            "DELETE FROM analysis.limit_event_annual_summary WHERE run_id = ?",
            [current_run_id],
        )
        connection.execute(
            "DELETE FROM quality.stage8_quality_result WHERE run_id = ?",
            [current_run_id],
        )
        connection.execute(
            "DELETE FROM audit.stage8_run WHERE run_id = ?", [current_run_id]
        )
        rule_frame, status_frame = _rule_frame(rules), _status_frame(statuses)
        relations = [
            ("stage8_events", observations[EVENT_COLUMNS], "analysis." + EVENT_TABLE, EVENT_COLUMNS),
            ("stage8_summary", summary[SUMMARY_COLUMNS], "analysis.limit_event_annual_summary", SUMMARY_COLUMNS),
            ("stage8_quality", quality[QUALITY_COLUMNS], "quality.stage8_quality_result", QUALITY_COLUMNS),
        ]
        if not rule_frame.empty:
            rule_columns = list(rule_frame.columns)
            relations.append(("stage8_rules", rule_frame, "reference.limit_rule", rule_columns))
        if not status_frame.empty:
            status_columns = list(status_frame.columns)
            relations.append(("stage8_statuses", status_frame, "reference.security_status_history", status_columns))
        for relation, frame, table, columns in relations:
            connection.register(relation, frame[columns])
            names = ", ".join(columns)
            connection.execute(
                f"INSERT OR REPLACE INTO {table} ({names}) SELECT {names} FROM {relation}"
            )
            connection.unregister(relation)
        run_frame = pd.DataFrame(
            [{
                **run,
                "blockers_json": json.dumps(run["blockers"], ensure_ascii=False),
            }]
        ).drop(columns=["blockers"])
        connection.register("stage8_run", run_frame)
        run_columns = list(run_frame.columns)
        names = ", ".join(run_columns)
        connection.execute(
            f"INSERT OR REPLACE INTO audit.stage8_run ({names}) "
            f"SELECT {names} FROM stage8_run"
        )
        connection.unregister("stage8_run")
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        connection.close()


def finalize_stage8_results(
    *,
    database_path: Path,
    summary: pd.DataFrame,
    quality: pd.DataFrame,
    run: dict[str, object],
) -> None:
    """Atomically persist final post-write quality, summary status, and run."""
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        for relation, frame, table, columns in [
            (
                "stage8_final_summary",
                summary[SUMMARY_COLUMNS],
                "analysis.limit_event_annual_summary",
                SUMMARY_COLUMNS,
            ),
            (
                "stage8_final_quality",
                quality[QUALITY_COLUMNS],
                "quality.stage8_quality_result",
                QUALITY_COLUMNS,
            ),
        ]:
            connection.register(relation, frame)
            names = ", ".join(columns)
            connection.execute(
                f"INSERT OR REPLACE INTO {table} ({names}) "
                f"SELECT {names} FROM {relation}"
            )
            connection.unregister(relation)
        run_frame = pd.DataFrame(
            [{**run, "blockers_json": json.dumps(run["blockers"], ensure_ascii=False)}]
        ).drop(columns=["blockers"])
        connection.register("stage8_final_run", run_frame)
        columns = list(run_frame.columns)
        names = ", ".join(columns)
        connection.execute(
            f"INSERT OR REPLACE INTO audit.stage8_run ({names}) "
            f"SELECT {names} FROM stage8_final_run"
        )
        connection.unregister("stage8_final_run")
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        connection.close()


def read_stage8_counts(database_path: Path) -> dict[str, int]:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        return {
            "observations": connection.execute(
                "SELECT count(*) FROM analysis." + EVENT_TABLE
            ).fetchone()[0],
            "formal_events": connection.execute(
                "SELECT count(*) FROM analysis.v_formal_limit_event"
            ).fetchone()[0],
            "summaries": connection.execute(
                "SELECT count(*) FROM analysis.limit_event_annual_summary"
            ).fetchone()[0],
        }
    finally:
        connection.close()
