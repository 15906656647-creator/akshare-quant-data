"""Transactional DuckDB persistence for Stage 11."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ..assets import ETHUSDT_OKX_SPOT
from ..crypto_market import validate_crypto_identity


TABLES = {
    "raw.crypto_market_data": "raw",
    "clean.crypto_price_fact": "clean",
    "feature.crypto_indicator": "indicators",
    "analysis.crypto_profile": "profile",
    "quality.stage11_quality_result": "quality",
    "audit.stage11_run": "audit",
}
TABLE_KEYS = {
    "raw.crypto_market_data": ["run_id", "symbol", "exchange", "interval", "trade_time"],
    "clean.crypto_price_fact": ["run_id", "symbol", "exchange", "interval", "trade_time"],
    "feature.crypto_indicator": ["run_id", "symbol", "exchange", "interval", "trade_time"],
    "analysis.crypto_profile": ["run_id", "symbol", "exchange", "interval"],
    "quality.stage11_quality_result": ["run_id", "check_name"],
    "audit.stage11_run": ["run_id"],
}


def _upsert(connection: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, run_id: str) -> None:
    if frame.empty:
        connection.execute(f"DELETE FROM {table} WHERE run_id=?", [run_id])
        return
    columns = [row[1] for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()]
    connection.register("_stage11_frame", frame[columns])
    names = ",".join(f'"{name}"' for name in columns)
    connection.execute(f"INSERT OR REPLACE INTO {table} ({names}) SELECT {names} FROM _stage11_frame")
    keys = TABLE_KEYS[table]
    match = " AND ".join(f"target.\"{key}\" = staged.\"{key}\"" for key in keys)
    connection.execute(
        f"DELETE FROM {table} AS target WHERE target.run_id=? "
        f"AND NOT EXISTS (SELECT 1 FROM _stage11_frame AS staged WHERE {match})",
        [run_id],
    )
    connection.unregister("_stage11_frame")


def write_stage11_run(database_path: Path, *, schema_path: Path, frames: dict[str, pd.DataFrame], run_id: str) -> None:
    for key in ("raw", "clean"):
        frame = frames.get(key)
        if frame is None:
            raise ValueError(f"Stage 11 repository frame missing: {key}")
        validate_crypto_identity(frame, expected=ETHUSDT_OKX_SPOT)
        normalized_expectations = {
            "requested_instrument": ETHUSDT_OKX_SPOT.requested_instrument,
            "normalized_instrument": ETHUSDT_OKX_SPOT.normalized_instrument,
            "normalized_exchange": ETHUSDT_OKX_SPOT.normalized_exchange,
            "symbol": ETHUSDT_OKX_SPOT.normalized_instrument,
            "exchange": ETHUSDT_OKX_SPOT.normalized_exchange,
            "market": ETHUSDT_OKX_SPOT.instrument_type,
            "interval": ETHUSDT_OKX_SPOT.bar_interval,
            "source": ETHUSDT_OKX_SPOT.data_provider,
        }
        for column, expected in normalized_expectations.items():
            if column not in frame or frame[column].isna().any() or not frame[column].astype(str).eq(expected).all():
                raise ValueError(f"Stage 11 repository identity invariant failed: {column} must equal {expected!r}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(schema_path.read_text(encoding="utf-8"))
        connection.execute("BEGIN")
        try:
            for table, key in TABLES.items():
                _upsert(connection, table, frames[key], run_id)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def read_stage11_run(database_path: Path, run_id: str) -> dict[str, pd.DataFrame]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        return {
            key: connection.execute(
                f"SELECT * FROM {table} WHERE run_id=? ORDER BY "
                + ",".join(f'"{name}"' for name in TABLE_KEYS[table]),
                [run_id],
            ).fetchdf()
            for table, key in TABLES.items()
        }
