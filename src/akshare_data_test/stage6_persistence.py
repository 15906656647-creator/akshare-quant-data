"""Deterministic Stage 6 artifact identity, hashing, and conflict errors."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


class Stage6PersistenceError(RuntimeError):
    """Base class for explicit, machine-readable Stage 6 persistence errors."""

    error_code = "stage6_persistence_error"

    def __init__(
        self,
        message: str,
        *,
        artifact_type: str,
        feature_run_id: str | None = None,
        path: str | Path | None = None,
        table_name: str | None = None,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ) -> None:
        self.artifact_type = artifact_type
        self.feature_run_id = feature_run_id
        self.path = _safe_path(path)
        self.table_name = table_name
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        details = {
            "error_code": self.error_code,
            "artifact_type": artifact_type,
            "feature_run_id": feature_run_id,
            "path": self.path,
            "table_name": table_name,
            "expected_hash": expected_hash,
            "actual_hash": actual_hash,
        }
        rendered = ",".join(
            f"{key}={value}" for key, value in details.items() if value is not None
        )
        super().__init__(f"{self.error_code}:{message}:{rendered}")


class Stage6PayloadConflictError(Stage6PersistenceError):
    error_code = "feature_payload_conflict"


class Stage6ArtifactIdentityConflictError(Stage6PersistenceError):
    error_code = "feature_run_path_conflict"


class Stage6IncompleteArtifactError(Stage6PersistenceError):
    error_code = "incomplete_existing_stage6_artifact"


class Stage6TransactionError(Stage6PersistenceError):
    error_code = "stage6_transaction_error"


@dataclass(frozen=True)
class Stage6ArtifactIdentity:
    feature_run_id: str
    transform_run_id: str
    market_source_run_id: str
    fundamental_source_run_id: str
    as_of_date: str
    source_database_path: str
    source_database_sha256: str
    feature_config_sha256: str


def _safe_path(path: str | Path | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    parts = candidate.parts
    for marker in ("data", "database", "reports"):
        if marker in parts:
            return Path(*parts[parts.index(marker) :]).as_posix()
    return candidate.name


def canonical_scalar(value: Any) -> Any:
    """Return a stable JSON-compatible scalar representation."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        if value.tzinfo is not None:
            value = value.tz_convert(timezone.utc)
        return value.isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            return str(value)
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value == 0:
            return "0"
        return format(value, ".17g")
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [canonical_scalar(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): canonical_scalar(value[key])
            for key in sorted(value, key=str)
        }
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def canonical_dataframe(
    frame: pd.DataFrame,
    business_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Canonicalize a frame without temporary paths, mtimes, or binary encoding."""
    columns = [str(column) for column in frame.columns]
    records = [
        [canonical_scalar(value) for value in row]
        for row in frame.itertuples(index=False, name=None)
    ]
    key_columns = list(business_keys or [])
    missing = [column for column in key_columns if column not in columns]
    if missing:
        raise ValueError(f"missing_business_key_columns:{','.join(missing)}")
    if key_columns:
        positions = [columns.index(column) for column in key_columns]
        records.sort(
            key=lambda row: json.dumps(
                [row[position] for position in positions],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        records.sort(
            key=lambda row: json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    return {"columns": columns, "rows": records}


def stable_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        canonical_scalar(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_dataframe_hash(
    frame: pd.DataFrame,
    business_keys: Iterable[str] | None = None,
) -> str:
    payload = canonical_dataframe(frame, business_keys)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_business_key_hash(
    frame: pd.DataFrame,
    business_keys: Iterable[str],
) -> str:
    keys = list(business_keys)
    return stable_dataframe_hash(frame.loc[:, keys], keys)


def resolve_existing_artifact_action(
    feature_paths: Iterable[Path],
    database_path: Path,
    manifest_path: Path,
) -> str:
    """Classify a requested run path without modifying any existing artifact."""
    paths = list(feature_paths)
    file_exists = [path.is_file() for path in paths]
    run_directory_exists = any(path.parent.exists() for path in paths)
    database_exists = database_path.is_file()
    manifest_exists = manifest_path.is_file()
    anything_exists = (
        any(file_exists)
        or run_directory_exists
        or database_path.exists()
        or manifest_path.exists()
        or manifest_path.parent.exists()
    )
    if not anything_exists:
        return "create_new"
    if all(file_exists) and database_exists and manifest_exists:
        return "reuse_identical"
    raise Stage6IncompleteArtifactError(
        "requested run has only a partial artifact set",
        artifact_type="stage6_artifact_set",
        path=manifest_path,
    )
