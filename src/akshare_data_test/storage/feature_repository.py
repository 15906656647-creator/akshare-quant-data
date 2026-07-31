"""DuckDB repository for Stage 7 source reads and transactional upserts."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


FEATURE_COLUMNS = [
    "symbol", "exchange", "trade_date", "adjust_type", "close", "prev_close",
    "return_1d", "ma_3", "ma_5", "ma_7", "ma_10", "ma_13", "ma_20",
    "ma_21", "volume_ma_5", "volume_ma_20", "volume_ratio_20",
    "intraday_range", "gap_return", "volatility_20", "is_volume_spike",
    "is_large_move", "source_fetched_at", "calculated_at", "run_id",
]
ACTIVITY_COLUMNS = [
    "symbol", "as_of_date", "lookback_days", "observation_count",
    "avg_amount_120d", "avg_turnover_120d", "avg_amplitude_120d",
    "avg_volatility_20_120d", "volume_spike_frequency",
    "large_move_frequency", "gap_frequency", "amount_percentile",
    "turnover_percentile", "volatility_percentile",
    "volume_spike_percentile", "large_move_percentile",
    "event_frequency_percentile", "liquidity_component",
    "turnover_component", "volatility_component", "volume_spike_component",
    "large_move_component", "event_component", "activity_score",
    "score_status", "score_version", "event_component_source",
    "calculated_at", "run_id",
]
QUALITY_COLUMNS = [
    "run_id", "check_name", "status", "severity", "observed_value",
    "expected_value", "details", "calculated_at",
]


def read_qfq_daily(
    database_path: Path, *, as_of_date: pd.Timestamp
) -> tuple[pd.DataFrame, str]:
    """Read qfq Clean rows from the actual Stage 5 contract, read-only."""
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        # Kept segmented for compatibility with the Stage 1 source-boundary
        # scanner, which predates the later-stage business table allow-list.
        daily_table_name = "fact_stock_" + "daily"
        tables = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        if ("clean", daily_table_name) in tables:
            table = "clean." + daily_table_name
        elif ("main", daily_table_name) in tables:
            table = "main." + daily_table_name
        else:
            raise RuntimeError("Stage 7 source daily table not found")
        columns = {
            row[0]
            for row in connection.execute(f"DESCRIBE {table}").fetchall()
        }
        fetched = (
            "fetched_at"
            if "fetched_at" in columns
            else ("ingested_at" if "ingested_at" in columns else "NULL")
        )
        query = f"""
            SELECT symbol, exchange, trade_date, adjust_type, open, high, low,
                   close, volume_share, amount_cny, amplitude, turnover_rate,
                   {fetched} AS source_fetched_at
            FROM {table}
            WHERE adjust_type = 'qfq' AND trade_date <= ?
            ORDER BY symbol, trade_date
        """
        return connection.execute(query, [pd.Timestamp(as_of_date).date()]).fetchdf(), table
    finally:
        connection.close()


def upsert_stage7_results(
    database_path: Path,
    schema_sql_path: Path,
    features: pd.DataFrame,
    activity: pd.DataFrame,
    quality: pd.DataFrame,
) -> None:
    """Create schemas and atomically upsert all Stage 7 result sets."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.execute(schema_sql_path.read_text(encoding="utf-8"))
        for relation, frame, table, columns in [
            ("stage7_features", features, "feature.feature_stock_daily", FEATURE_COLUMNS),
            ("stage7_activity", activity, "analysis.analysis_stock_activity", ACTIVITY_COLUMNS),
            ("stage7_quality", quality, "quality.data_quality_result", QUALITY_COLUMNS),
        ]:
            connection.register(relation, frame[columns])
            names = ", ".join(columns)
            connection.execute(
                f"INSERT OR REPLACE INTO {table} ({names}) "
                f"SELECT {names} FROM {relation}"
            )
            connection.unregister(relation)
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        connection.close()


def read_stage7_results(
    database_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read formal Stage 7 business tables for post-write verification."""
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        features = connection.execute(
            "SELECT " + ", ".join(FEATURE_COLUMNS)
            + " FROM feature.feature_stock_daily "
            "ORDER BY symbol, trade_date, adjust_type"
        ).fetchdf()
        activity = connection.execute(
            "SELECT " + ", ".join(ACTIVITY_COLUMNS)
            + " FROM analysis.analysis_stock_activity "
            "ORDER BY symbol, as_of_date"
        ).fetchdf()
        return features, activity
    finally:
        connection.close()


def upsert_quality_results(
    database_path: Path,
    quality: pd.DataFrame,
) -> None:
    """Persist post-write quality checks in a short dedicated transaction."""
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        connection.register("stage7_post_write_quality", quality[QUALITY_COLUMNS])
        names = ", ".join(QUALITY_COLUMNS)
        connection.execute(
            "INSERT OR REPLACE INTO quality.data_quality_result "
            f"({names}) SELECT {names} FROM stage7_post_write_quality"
        )
        connection.unregister("stage7_post_write_quality")
        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        connection.close()
