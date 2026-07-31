"""Stable Stage 5 metadata identities and idempotent DuckDB loading helpers."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Any

import duckdb
import pandas as pd


class IdempotencyPayloadConflict(RuntimeError):
    """A stable business key was reused with different registered content."""


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NA:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, bool) else False


def _canonical_path(value: str | Path, root: Path | None) -> str:
    text = str(value)
    windows = PureWindowsPath(text)
    is_windows_absolute = windows.is_absolute()
    path = Path(text)
    if path.is_absolute():
        if root is None:
            raise ValueError(f"Absolute path is not canonical: {text}")
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f"Path is outside project root: {text}") from exc
    if is_windows_absolute:
        if root is None:
            raise ValueError(f"Absolute path is not canonical: {text}")
        root_windows = PureWindowsPath(str(root))
        try:
            return windows.relative_to(root_windows).as_posix()
        except ValueError as exc:
            raise ValueError(f"Path is outside project root: {text}") from exc
    return text.replace("\\", "/")


def _canonical_value(value: Any, root: Path | None) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item, root)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item, root) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return _canonical_path(value, root)
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return _canonical_value(value.item(), root)
    if isinstance(value, float):
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return 0.0 if value == 0 else value
    return value


def canonical_json(value: Any, root: Path | None = None) -> str:
    """Return deterministic UTF-8 JSON with explicit null and stable scalars."""

    return json.dumps(
        _canonical_value(value, root),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_record_hash(value: Any, root: Path | None = None) -> str:
    """Hash complete effective record content with SHA-256."""

    return hashlib.sha256(canonical_json(value, root).encode("utf-8")).hexdigest()


def stable_business_key(value: Any, root: Path | None = None) -> str:
    """Hash stable identity fields using the same canonical representation."""

    return stable_record_hash(value, root)


MAPPING_COLUMNS = [
    "transform_run_id",
    "source_dataset",
    "source_field",
    "canonical_field",
    "data_type",
    "source_unit",
    "target_unit",
    "scale_factor",
    "nullable",
    "required",
    "mapping_status",
    "mapping_evidence",
    "notes",
    "mapping_key",
    "record_hash",
]

QUALITY_COLUMNS = [
    "transform_run_id",
    "dataset_id",
    "check_name",
    "severity",
    "status",
    "issue_count",
    "message",
    "issue_code",
    "symbol",
    "field_name",
    "business_key_json",
    "source_file",
    "source_row_number",
    "issue_scope",
    "issue_key",
    "record_hash",
]


def prepare_mapping_records(frame: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Add stable mapping identity and payload hashes."""

    prepared = frame.copy()
    for column in MAPPING_COLUMNS[:-2]:
        if column not in prepared:
            prepared[column] = None
    keys: list[str] = []
    hashes: list[str] = []
    for record in prepared[MAPPING_COLUMNS[:-2]].to_dict("records"):
        identity = {
            key: record.get(key)
            for key in (
                "transform_run_id",
                "source_dataset",
                "source_field",
                "canonical_field",
                "mapping_status",
            )
        }
        keys.append(stable_business_key(identity, root))
        hashes.append(stable_record_hash(record, root))
    prepared["mapping_key"] = keys
    prepared["record_hash"] = hashes
    return prepared[MAPPING_COLUMNS]


def prepare_quality_records(frame: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Add explicit issue identity fields plus stable issue and payload hashes."""

    prepared = frame.copy()
    defaults = {
        "issue_code": prepared.get("check_name"),
        "symbol": None,
        "field_name": None,
        "business_key_json": "{}",
        "source_file": None,
        "source_row_number": None,
        "issue_scope": "dataset",
    }
    for column, default in defaults.items():
        if column not in prepared:
            prepared[column] = default
    for column in QUALITY_COLUMNS[:7]:
        if column not in prepared:
            prepared[column] = None
    prepared["issue_code"] = prepared["issue_code"].fillna(prepared["check_name"])
    prepared["issue_scope"] = prepared["issue_scope"].fillna("dataset")
    prepared["business_key_json"] = prepared["business_key_json"].map(
        lambda value: canonical_json(
            json.loads(value) if isinstance(value, str) and value.strip() else {},
            root,
        )
    )
    prepared["source_file"] = prepared["source_file"].map(
        lambda value: (
            None if _is_missing(value) else _canonical_path(str(value), root)
        )
    )
    keys: list[str] = []
    hashes: list[str] = []
    for record in prepared[QUALITY_COLUMNS[:-2]].to_dict("records"):
        identity = {
            key: record.get(key)
            for key in (
                "transform_run_id",
                "dataset_id",
                "severity",
                "issue_code",
                "symbol",
                "field_name",
                "business_key_json",
                "source_file",
                "source_row_number",
                "issue_scope",
            )
        }
        keys.append(stable_business_key(identity, root))
        hashes.append(stable_record_hash(record, root))
    prepared["issue_key"] = keys
    prepared["record_hash"] = hashes
    return prepared[QUALITY_COLUMNS]


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        connection.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table],
        ).fetchone()[0]
    )


def _table_columns(
    connection: duckdb.DuckDBPyConnection, table: str
) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info('{table}')"
        ).fetchall()
    }


def preflight_metadata_columns(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Add nullable repair columns before the schema creates unique indexes."""

    additions = {
        "field_mapping_registry": {
            "mapping_key": "VARCHAR",
            "record_hash": "VARCHAR",
        },
        "data_quality_issue": {
            "issue_code": "VARCHAR",
            "symbol": "VARCHAR",
            "field_name": "VARCHAR",
            "business_key_json": "VARCHAR",
            "source_file": "VARCHAR",
            "source_row_number": "BIGINT",
            "issue_scope": "VARCHAR",
            "issue_key": "VARCHAR",
            "record_hash": "VARCHAR",
        },
    }
    for table, columns in additions.items():
        existing = _table_columns(connection, table)
        for column, sql_type in columns.items():
            if existing and column not in existing:
                connection.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}'
                )


def _assert_unique_prepared(
    frame: pd.DataFrame, key_column: str, table: str
) -> pd.DataFrame:
    hash_counts = frame.groupby(key_column, dropna=False)["record_hash"].nunique()
    conflicts = hash_counts[hash_counts > 1]
    if not conflicts.empty:
        raise IdempotencyPayloadConflict(
            f"idempotency_payload_conflict:{table}:incoming:{conflicts.index[0]}"
        )
    return frame.drop_duplicates(key_column, keep="first").reset_index(drop=True)


def migrate_metadata_schema(
    connection: duckdb.DuckDBPyConnection, root: Path
) -> dict[str, int]:
    """Backfill stable metadata keys in a copied legacy database."""

    migrated: dict[str, int] = {}
    specifications = [
        (
            "field_mapping_registry",
            "mapping_key",
            prepare_mapping_records,
            MAPPING_COLUMNS,
        ),
        (
            "data_quality_issue",
            "issue_key",
            prepare_quality_records,
            QUALITY_COLUMNS,
        ),
    ]
    for table, key_column, prepare, columns in specifications:
        if not _table_exists(connection, table):
            continue
        existing = connection.execute(
            f'SELECT rowid AS __rowid, * FROM "{table}" ORDER BY rowid'
        ).fetchdf()
        if existing.empty:
            migrated[table] = 0
        else:
            source_columns = [
                column for column in columns[:-2] if column in existing.columns
            ]
            prepared = prepare(existing[source_columns], root)
            _assert_unique_prepared(prepared, key_column, table)
            provided_keys = existing.get(key_column)
            provided_hashes = existing.get("record_hash")
            if provided_keys is not None:
                for old, new in zip(provided_keys, prepared[key_column]):
                    if not _is_missing(old) and old != new:
                        raise IdempotencyPayloadConflict(
                            f"idempotency_payload_conflict:{table}:stored_key"
                        )
            if provided_hashes is not None:
                for old, new in zip(provided_hashes, prepared["record_hash"]):
                    if not _is_missing(old) and old != new:
                        raise IdempotencyPayloadConflict(
                            f"idempotency_payload_conflict:{table}:stored_payload"
                        )
            update = prepared.copy()
            update["__rowid"] = existing["__rowid"].to_numpy()
            original_columns = {
                "transform_run_id",
                "dataset_id",
                "check_name",
                "severity",
                "status",
                "issue_count",
                "message",
                "source_dataset",
                "source_field",
                "canonical_field",
                "data_type",
                "source_unit",
                "target_unit",
                "scale_factor",
                "nullable",
                "required",
                "mapping_status",
                "mapping_evidence",
                "notes",
            }
            update_columns = [
                column for column in columns if column not in original_columns
            ]
            assignments = ", ".join(
                f'"{column}" = ?' for column in update_columns
            )
            parameters = [
                [
                    *[
                        None if _is_missing(row[column]) else row[column]
                        for column in update_columns
                    ],
                    int(row["__rowid"]),
                ]
                for row in update.to_dict("records")
            ]
            connection.executemany(
                f'UPDATE "{table}" SET {assignments} WHERE rowid = ?',
                parameters,
            )
            migrated[table] = len(prepared)
    return migrated


def finalize_metadata_schema(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Apply non-null constraints after legacy backfill has committed."""

    for table, columns in {
        "field_mapping_registry": ["mapping_key", "record_hash"],
        "data_quality_issue": ["issue_key", "record_hash"],
    }.items():
        info = {
            row[1]: bool(row[3])
            for row in connection.execute(
                f"PRAGMA table_info('{table}')"
            ).fetchall()
        }
        for column in columns:
            if not info.get(column, False):
                connection.execute(
                    f'ALTER TABLE "{table}" '
                    f'ALTER COLUMN "{column}" SET NOT NULL'
                )


def upsert_hashed_records(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    frame: pd.DataFrame,
    key_column: str,
) -> dict[str, int]:
    """Insert missing keys, skip identical payloads, and reject conflicts."""

    incoming = _assert_unique_prepared(frame, key_column, table)
    if incoming.empty:
        return {"inserted": 0, "unchanged": 0}
    view = f"incoming_{table}"
    connection.register(view, incoming)
    try:
        conflict = connection.execute(
            f"""
            SELECT i."{key_column}"
            FROM "{view}" i
            JOIN "{table}" t USING ("{key_column}")
            WHERE i.record_hash <> t.record_hash
            LIMIT 1
            """
        ).fetchone()
        if conflict:
            raise IdempotencyPayloadConflict(
                f"idempotency_payload_conflict:{table}:{conflict[0]}"
            )
        unchanged = int(
            connection.execute(
                f"""
                SELECT count(*) FROM "{view}" i
                JOIN "{table}" t USING ("{key_column}")
                WHERE i.record_hash = t.record_hash
                """
            ).fetchone()[0]
        )
        columns = list(incoming.columns)
        quoted = ", ".join(f'"{column}"' for column in columns)
        connection.execute(
            f"""
            INSERT INTO "{table}" ({quoted})
            SELECT {quoted} FROM "{view}" i
            WHERE NOT EXISTS (
                SELECT 1 FROM "{table}" t
                WHERE t."{key_column}" = i."{key_column}"
            )
            """
        )
        return {"inserted": len(incoming) - unchanged, "unchanged": unchanged}
    finally:
        connection.unregister(view)


def _columns_content_hash(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[str],
) -> str:
    parts = []
    for column in columns:
        quoted = '"' + column.replace('"', '""') + '"'
        value = f"CAST({quoted} AS VARCHAR)"
        parts.append(
            f"CASE WHEN {quoted} IS NULL THEN '-1:' "
            f"ELSE CAST(length({value}) AS VARCHAR) || ':' || {value} END"
        )
    row_expression = " || '|' || ".join(parts) if parts else "''"
    return str(
        connection.execute(
            f"""
            SELECT sha256(
                COALESCE(string_agg(row_hash, '' ORDER BY row_hash), '')
            )
            FROM (
                SELECT sha256({row_expression}) AS row_hash
                FROM "{table}"
            )
            """
        ).fetchone()[0]
    )


def table_content_hash(
    connection: duckdb.DuckDBPyConnection, table: str
) -> str:
    """Return a SHA-256 over the sorted multiset of complete table rows."""

    columns = [
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info('{table}')"
        ).fetchall()
    ]
    return _columns_content_hash(connection, table, columns)


def snapshot_tables(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, Any]]:
    """Snapshot all twelve formal Stage 5 base tables."""

    tables = [
        row[0]
        for row in connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ).fetchall()
    ]
    business_keys = {
        "dim_security": ["symbol"],
        "etl_run": ["transform_run_id"],
        "source_file_manifest": ["source_run_id", "source_file"],
        "data_lineage": [
            "transform_run_id",
            "dataset_id",
            "clean_file",
            "source_file",
        ],
        "data_quality_issue": ["issue_key"],
        "field_mapping_registry": ["mapping_key"],
        "fact_stock_daily": [
            "symbol",
            "trade_date",
            "adjust_type",
            "source_run_id",
        ],
        "fact_stock_spot": [
            "symbol",
            "snapshot_at",
            "snapshot_scope",
            "source_run_id",
        ],
        "fact_financial_abstract": [
            "symbol",
            "report_period",
            "metric_code",
            "source_run_id",
        ],
        "fact_financial_indicator": [
            "symbol",
            "report_period",
            "metric_code",
            "source_run_id",
        ],
        "fact_financial_statement": [
            "symbol",
            "statement_type",
            "report_period",
            "line_item_code",
            "source_run_id",
        ],
        "fact_stock_fund_flow": [
            "symbol",
            "trade_date",
            "source_run_id",
        ],
    }
    return {
        table: {
            "row_count": int(
                connection.execute(
                    f'SELECT count(*) FROM "{table}"'
                ).fetchone()[0]
            ),
            "content_hash": table_content_hash(connection, table),
            "business_key_hash": _columns_content_hash(
                connection, table, business_keys[table]
            ),
        }
        for table in tables
    }
