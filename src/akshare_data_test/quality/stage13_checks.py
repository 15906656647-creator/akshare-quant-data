"""Quality helpers for Stage 13 manifests and read-only SQL."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


_WRITE_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|ATTACH|DETACH|TRUNCATE|MERGE|CALL|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def validate_read_only_sql(sql: str) -> None:
    stripped = sql.strip()
    if not stripped or not re.match(r"^(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise ValueError("Stage 13 SQL must begin with SELECT or WITH")
    without_terminal = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in without_terminal:
        raise ValueError("Stage 13 SQL must contain one statement")
    if _WRITE_SQL.search(without_terminal):
        raise ValueError("Stage 13 SQL contains a forbidden operation")


def validate_asset_manifest(frame: pd.DataFrame, reports_dir: Path) -> list[str]:
    errors: list[str] = []
    if frame.duplicated(["symbol", "asset_id"]).any():
        errors.append("duplicate_asset_key")
    for row in frame.itertuples(index=False):
        if row.status in {"AVAILABLE", "PARTIAL"}:
            if not row.output_path:
                errors.append(f"missing_output_path:{row.symbol}:{row.asset_id}")
                continue
            target = reports_dir / row.output_path
            if not target.is_file():
                errors.append(f"missing_file:{row.symbol}:{row.asset_id}")
        elif row.output_path or row.sha256:
            errors.append(f"unavailable_has_output:{row.symbol}:{row.asset_id}")
    return errors


def inventory_blocking_reasons(frame: pd.DataFrame) -> list[str]:
    """Return stable, actionable reasons for every blocked inventory row."""
    required = {"database_file", "schema_name", "table_name", "status", "error"}
    missing = required.difference(frame.columns)
    if missing:
        return [f"inventory schema missing columns: {sorted(missing)}"]
    blocked = frame.loc[frame.status.eq("BLOCKED")].sort_values(
        ["database_file", "schema_name", "table_name"], kind="stable"
    )
    return [
        f"{row.database_file}:{row.schema_name}.{row.table_name}: {row.error or 'unspecified inventory failure'}"
        for row in blocked.itertuples(index=False)
    ]


def invalid_event_price_count(frame: pd.DataFrame) -> int:
    """Count confirmed-event rows without a finite positive authoritative price."""
    if frame.empty:
        return 0
    if "event_price" not in frame:
        return len(frame)
    values = pd.to_numeric(frame["event_price"], errors="coerce")
    return int((~values.map(lambda value: pd.notna(value) and float(value) > 0 and float(value) != float("inf"))).sum())
