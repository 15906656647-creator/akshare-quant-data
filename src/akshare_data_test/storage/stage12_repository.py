"""Transactional, conflict-safe Stage 12 DuckDB repository."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd


TABLES = {
    "active": "analysis.stage12_active_stock",
    "breakouts": "analysis.stage12_volume_breakout",
    "ranges": "analysis.stage12_range_bound",
    "combined": "analysis.stage12_fundamental_price_volume",
    "quality": "quality.stage12_quality_result",
}


def _storage_frame(frame: pd.DataFrame, *, run_id: str, created_at: pd.Timestamp) -> pd.DataFrame:
    result = frame.copy()
    if "reason_codes" in result:
        result["reason_codes_json"] = result.pop("reason_codes").map(
            lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
    result.insert(0, "run_id", run_id)
    result["created_at"] = created_at
    return result


def write_stage12_run(
    database_path: Path, *, schema_path: Path, run_id: str,
    frames: dict[str, pd.DataFrame], quality: pd.DataFrame,
    manifest: dict, created_at: pd.Timestamp,
) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        try:
            connection.execute("BEGIN TRANSACTION")
            connection.execute(schema_path.read_text(encoding="utf-8"))
            existing = connection.execute(
                "SELECT input_sha256,config_sha256 FROM audit.stage12_run WHERE run_id=?", [run_id]
            ).fetchone()
            if existing and tuple(existing) != (manifest["input_sha256"], manifest["config_sha256"]):
                raise ValueError("Stage 12 run_id already exists with different input or configuration")
            for table in [*TABLES.values(), "audit.stage12_run"]:
                connection.execute(f"DELETE FROM {table} WHERE run_id=?", [run_id])
            for name in ("active", "breakouts", "ranges", "combined"):
                stored = _storage_frame(frames[name], run_id=run_id, created_at=created_at)
                relation = f"stage12_{name}"
                connection.register(relation, stored)
                columns = list(stored.columns)
                names = ",".join(columns)
                connection.execute(f"INSERT INTO {TABLES[name]} ({names}) SELECT {names} FROM {relation}")
                connection.unregister(relation)
            connection.register("stage12_quality", quality)
            quality_names = ",".join(quality.columns)
            connection.execute(f"INSERT INTO {TABLES['quality']} ({quality_names}) SELECT {quality_names} FROM stage12_quality")
            connection.unregister("stage12_quality")
            audit = pd.DataFrame([{
                "run_id": run_id, "run_status": manifest["status"], "stage": 12,
                "as_of_date": manifest["as_of_date"], "started_at": manifest["started_at"],
                "completed_at": manifest["completed_at"], "input_sha256": manifest["input_sha256"],
                "config_sha256": manifest["config_sha256"], "canonical_sha256": manifest["canonical_sha256"],
                "blocking_reasons_json": json.dumps(manifest["blocking_reasons"], ensure_ascii=False),
                "warnings_json": json.dumps(manifest["warnings"], ensure_ascii=False),
                "manifest_json": json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False),
                "created_at": created_at,
            }])
            connection.register("stage12_audit", audit)
            audit_names = ",".join(audit.columns)
            connection.execute(f"INSERT INTO audit.stage12_run ({audit_names}) SELECT {audit_names} FROM stage12_audit")
            connection.unregister("stage12_audit")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def stage12_counts(database_path: Path, run_id: str) -> dict[str, int]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        return {
            name: int(connection.execute(f"SELECT count(*) FROM {table} WHERE run_id=?", [run_id]).fetchone()[0])
            for name, table in TABLES.items()
        }
