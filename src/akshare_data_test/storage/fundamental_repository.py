"""Transactional DuckDB persistence for Stage 10."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import duckdb
import pandas as pd

from ..fundamental_analysis import (
    FACT_COLUMNS, INDICATOR_COLUMNS, RAW_COLUMNS, SUMMARY_COLUMNS, VALUATION_COLUMNS,
)


QUALITY_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "numerator", "denominator", "message", "checked_at",
]
AUDIT_COLUMNS = [
    "run_id", "run_status", "publication_status", "started_at", "completed_at",
    "input_database", "output_database", "as_of_date", "symbol_count",
    "raw_row_count", "fact_row_count", "indicator_row_count", "summary_row_count",
    "valuation_row_count", "quality_passed", "quality_failed",
    "blocking_reasons_json", "config_hash", "calculation_version", "model_version",
    "output_type", "manifest_json", "created_at",
]


TABLES: Mapping[str, tuple[str, list[str]]] = {
    "raw": ("raw.financial_statement", RAW_COLUMNS),
    "facts": ("clean.financial_fact", FACT_COLUMNS),
    "indicators": ("feature.fundamental_indicator", INDICATOR_COLUMNS),
    "summaries": ("analysis.fundamental_summary", SUMMARY_COLUMNS),
    "valuations": ("analysis.valuation_snapshot", VALUATION_COLUMNS),
    "quality": ("quality.stage10_quality_result", QUALITY_COLUMNS),
    "audit": ("audit.stage10_run", AUDIT_COLUMNS),
}


def _insert_frame(
    connection: duckdb.DuckDBPyConnection, name: str, table: str,
    frame: pd.DataFrame, columns: list[str],
) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{name} frame missing columns: {missing}")
    registered = f"_stage10_{name}"
    connection.register(registered, frame[columns])
    quoted = ", ".join(f'"{column}"' for column in columns)
    connection.execute(f"INSERT INTO {table} ({quoted}) SELECT {quoted} FROM {registered}")
    connection.unregister(registered)


def write_stage10_run(
    database_path: Path, schema_path: Path, *, run_id: str,
    raw: pd.DataFrame, facts: pd.DataFrame, indicators: pd.DataFrame,
    summaries: pd.DataFrame, valuations: pd.DataFrame, quality: pd.DataFrame,
    audit: pd.DataFrame,
) -> None:
    """Atomically replace one run while preserving every other run."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    frames = {
        "raw": raw, "facts": facts, "indicators": indicators,
        "summaries": summaries, "valuations": valuations,
        "quality": quality, "audit": audit,
    }
    with duckdb.connect(str(database_path)) as connection:
        try:
            connection.execute("BEGIN TRANSACTION")
            connection.execute(schema_path.read_text(encoding="utf-8"))
            for table, _ in TABLES.values():
                connection.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
            for name, frame in frames.items():
                table, columns = TABLES[name]
                _insert_frame(connection, name, table, frame, columns)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def read_stage10_run(database_path: Path, run_id: str) -> dict[str, pd.DataFrame]:
    """Read all persisted frames for a single run in read-only mode."""
    result: dict[str, pd.DataFrame] = {}
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for name, (table, _) in TABLES.items():
            result[name] = connection.execute(
                f"SELECT * FROM {table} WHERE run_id = ?", [run_id]
            ).fetchdf()
    return result


def stage10_counts(database_path: Path) -> dict[str, int]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        return {
            name: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for name, (table, _) in TABLES.items()
        }
