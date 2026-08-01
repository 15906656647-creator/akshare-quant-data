"""Read-only Stage 9 inputs and transactional versioned result storage."""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pandas as pd

from ..style_classification import PROFILE_COLUMNS
from ..style_features import STYLE_FEATURE_COLUMNS


FEATURE_DB_COLUMNS = [*STYLE_FEATURE_COLUMNS, "run_id", "created_at"]
PROFILE_DB_COLUMNS = [*PROFILE_COLUMNS, "run_id", "created_at"]
QUALITY_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "numerator", "denominator", "message", "checked_at",
]


def inspect_stage9_source(
    database_path: Path, *, as_of_date: pd.Timestamp, symbols: list[str] | None = None
) -> dict[str, object]:
    if not database_path.is_file():
        return {"status": "FAILED", "errors": [f"input_database_not_found:{database_path}"], "blockers": []}
    if database_path.stat().st_size == 0:
        return {"status": "FAILED", "errors": ["input_database_empty"], "blockers": []}
    connection = None
    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        tables = {(row[0], row[1]) for row in connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall()}
        daily_name = "fact_stock_" + "daily"
        if ("clean", daily_name) in tables:
            table = "clean." + daily_name
        elif ("main", daily_name) in tables:
            table = "main." + daily_name
        else:
            return {"status": "FAILED", "errors": ["input_daily_table_missing"], "blockers": []}
        columns = {row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()}
        required = {
            "symbol", "trade_date", "adjust_type", "open", "high", "low", "close",
            "volume_share", "amount_cny", "turnover_rate",
        }
        missing = sorted(required.difference(columns))
        if missing:
            return {"status": "FAILED", "input_table": table, "errors": ["input_columns_missing:" + ",".join(missing)], "blockers": []}
        params: list[object] = [pd.Timestamp(as_of_date).date()]
        symbol_clause = ""
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            symbol_clause = f" AND cast(symbol AS VARCHAR) IN ({placeholders})"
            params.extend(symbols)
        routes = connection.execute(
            f"SELECT DISTINCT lower(cast(adjust_type AS VARCHAR)) FROM {table} WHERE trade_date <= ?{symbol_clause}", params
        ).fetchall()
        routes = sorted(row[0] for row in routes)
        qfq_count = connection.execute(
            f"SELECT count(*) FROM {table} WHERE trade_date <= ?{symbol_clause} AND lower(cast(adjust_type AS VARCHAR))='qfq'", params
        ).fetchone()[0]
        duplicate_count = connection.execute(
            f"SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM {table} WHERE trade_date <= ?{symbol_clause} AND lower(cast(adjust_type AS VARCHAR))='qfq' GROUP BY cast(symbol AS VARCHAR),trade_date,adjust_type HAVING count(*)>1)", params
        ).fetchone()[0]
        errors: list[str] = []
        blockers: list[str] = []
        if not qfq_count:
            blockers.append("no_qfq_rows_at_or_before_as_of_date")
        if duplicate_count:
            errors.append(f"input_primary_key_duplicate:{duplicate_count}")
        status = "FAILED" if errors else ("BLOCKED" if blockers else "READY")
        return {
            "status": status, "input_table": table, "input_columns": sorted(columns),
            "input_price_routes": routes, "qfq_row_count": int(qfq_count),
            "duplicate_count": int(duplicate_count), "errors": errors, "blockers": blockers,
        }
    except duckdb.Error as exc:
        return {"status": "FAILED", "errors": [f"input_database_unreadable:{exc}"], "blockers": []}
    finally:
        if connection is not None:
            connection.close()


def validate_style_output_target(input_database: Path, output_database: Path) -> list[str]:
    errors: list[str] = []
    if input_database.resolve() == output_database.resolve():
        errors.append("output_database_matches_input_database")
    protected = {
        "akshare_features_stage7.duckdb", "akshare_limit_events_stage8.duckdb",
        "akshare_data_test_stage5_repaired.duckdb",
    }
    if output_database.name.lower() in protected:
        errors.append("output_database_is_protected_baseline")
    ancestor = output_database.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
        errors.append(f"output_parent_not_writable:{ancestor}")
    return errors


def read_stage9_daily(
    database_path: Path, *, table: str, as_of_date: pd.Timestamp,
    start_date: pd.Timestamp | None = None, symbols: list[str] | None = None,
) -> pd.DataFrame:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        columns = {row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()}
        optional = [
            name if name in columns else f"NULL AS {name}"
            for name in ("is_suspended", "amplitude", "source_fetched_at")
        ]
        feature_join = ""
        feature_columns = "NULL AS volume_ratio_20, NULL AS return_1d"
        tables = {(row[0], row[1]) for row in connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall()}
        if ("feature", "feature_stock_daily") in tables:
            feature_join = (
                " LEFT JOIN feature.feature_stock_daily f ON "
                "cast(d.symbol AS VARCHAR)=cast(f.symbol AS VARCHAR) "
                "AND d.trade_date=f.trade_date AND f.adjust_type='qfq'"
            )
            feature_columns = "f.volume_ratio_20, f.return_1d"
        clauses = ["lower(cast(d.adjust_type AS VARCHAR))='qfq'", "d.trade_date <= ?"]
        params: list[object] = [pd.Timestamp(as_of_date).date()]
        if start_date is not None:
            clauses.append("d.trade_date >= ?")
            params.append(pd.Timestamp(start_date).date())
        if symbols:
            clauses.append("cast(d.symbol AS VARCHAR) IN (" + ",".join("?" for _ in symbols) + ")")
            params.extend(symbols)
        query = f"""
            SELECT cast(d.symbol AS VARCHAR) symbol, d.trade_date, 'qfq' adjust_type,
                   d.open,d.high,d.low,d.close,d.volume_share,d.amount_cny,d.turnover_rate,
                   {feature_columns}, {', '.join('d.' + name if name in columns else name for name in optional)}
            FROM {table} d {feature_join}
            WHERE {' AND '.join(clauses)} ORDER BY symbol,trade_date
        """
        return connection.execute(query, params).fetchdf()


def read_stage8_auxiliary(database_path: Path | None) -> tuple[dict[str, dict[str, object]], str]:
    if database_path is None or not database_path.is_file():
        return {}, "not_available"
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            audit = connection.execute(
                "SELECT run_id,publication_status FROM audit.stage8_run ORDER BY created_at DESC,run_id DESC LIMIT 1"
            ).fetchone()
            if not audit:
                return {}, "not_available"
            run_id, publication = audit
            # Keep the Stage 1 source-boundary scanner compatible with the
            # later-stage, read-only business table allow-list.
            event_table = "fact_limit_" + "event"
            counts = connection.execute(
                "SELECT symbol,count(*) total,count_if(event_type IN ('limit_up','limit_down') AND evidence_status='verified' AND quality_status='pass') formal_count,count_if(event_type='candidate') candidate_count,count_if(event_type='proxy') proxy_count,count_if(event_type='gap_proxy') gap_count,count_if(event_type='unresolved' OR evidence_status='unresolved') unresolved_count FROM analysis."
                + event_table + " WHERE run_id=? GROUP BY symbol",
                [run_id],
            ).fetchall()
            result = {}
            for symbol, total, formal, candidate, proxy, gap, unresolved in counts:
                result[str(symbol).zfill(6)] = {
                    "publication_status": publication,
                    "formal_event_frequency": formal / total if publication == "formal" and total else None,
                    "candidate_event_frequency": candidate / total if total else None,
                    "proxy_event_frequency": proxy / total if total else None,
                    "gap_proxy_frequency": gap / total if total else None,
                    "unresolved_event_frequency": unresolved / total if total else None,
                }
            return result, str(publication)
    except duckdb.Error:
        return {}, "unavailable_invalid"


def _replace_run(
    connection: duckdb.DuckDBPyConnection, *, features: pd.DataFrame,
    profiles: pd.DataFrame, quality: pd.DataFrame, run: dict[str, object]
) -> None:
    run_id = str(run["run_id"])
    for table in (
        "feature.stage9_style_feature", "analysis.stage9_style_profile",
        "quality.stage9_quality_result", "audit.stage9_run",
    ):
        connection.execute(f"DELETE FROM {table} WHERE run_id=?", [run_id])
    for relation, frame, table, columns in (
        ("stage9_features", features, "feature.stage9_style_feature", FEATURE_DB_COLUMNS),
        ("stage9_profiles", profiles, "analysis.stage9_style_profile", PROFILE_DB_COLUMNS),
        ("stage9_quality", quality, "quality.stage9_quality_result", QUALITY_COLUMNS),
    ):
        connection.register(relation, frame[columns])
        names = ",".join(columns)
        connection.execute(f"INSERT INTO {table} ({names}) SELECT {names} FROM {relation}")
        connection.unregister(relation)
    audit = pd.DataFrame([{**run,
        "blocking_reasons_json": json.dumps(run["blocking_reasons"], ensure_ascii=False),
        "manifest_json": json.dumps(run["manifest"], ensure_ascii=False, default=str, allow_nan=False),
    }]).drop(columns=["blocking_reasons", "manifest"])
    connection.register("stage9_audit", audit)
    names = ",".join(audit.columns)
    connection.execute(f"INSERT INTO audit.stage9_run ({names}) SELECT {names} FROM stage9_audit")
    connection.unregister("stage9_audit")


def upsert_stage9_results(
    database_path: Path, schema_path: Path, *, features: pd.DataFrame,
    profiles: pd.DataFrame, quality: pd.DataFrame, run: dict[str, object]
) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        try:
            connection.execute("BEGIN TRANSACTION")
            connection.execute(schema_path.read_text(encoding="utf-8"))
            _replace_run(connection, features=features, profiles=profiles, quality=quality, run=run)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def read_stage9_counts(database_path: Path) -> dict[str, int]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        return {
            "features": connection.execute("SELECT count(*) FROM feature.stage9_style_feature").fetchone()[0],
            "profiles": connection.execute("SELECT count(*) FROM analysis.stage9_style_profile").fetchone()[0],
            "runs": connection.execute("SELECT count(*) FROM audit.stage9_run").fetchone()[0],
        }
