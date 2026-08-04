"""Strict configuration loader for Stage 13 presentation outputs."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Stage13Config:
    raw: dict[str, Any]
    sha256: str


_SCHEMA: dict[str, Any] = {
    "stage": int,
    "schema_version": str,
    "universe": {"expected_symbol_count": int},
    "inputs": {"feature_database": str, "activity_database": str},
    "presentation": {
        "price_lookback_days": int,
        "range_lookback_days": int,
        "event_lookback_days": int,
        "financial_periods": int,
        "image_format": str,
        "image_dpi": int,
        "float_precision": int,
        "overwrite": bool,
    },
    "moving_averages": {"price": list, "volume": list},
    "outputs": {
        "reports_dir": str,
        "charts_subdir": str,
        "tables_subdir": str,
        "sql_subdir": str,
    },
    "quality": {
        "require_stable_hashes": bool,
        "require_offline": bool,
        "require_read_only_database": bool,
    },
}


def _shape(value: Any, schema: Any, path: str) -> None:
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be a mapping")
        unknown = sorted(set(value) - set(schema))
        missing = sorted(set(schema) - set(value))
        if unknown:
            raise ValueError(f"{path} contains unknown keys: {unknown}")
        if missing:
            raise ValueError(f"{path} is missing required keys: {missing}")
        for key, child in schema.items():
            _shape(value[key], child, f"{path}.{key}")
        return
    expected = schema if isinstance(schema, tuple) else (schema,)
    if bool in expected:
        if type(value) is not bool:
            raise ValueError(f"{path} must be a boolean")
    elif isinstance(value, bool) or not isinstance(value, expected):
        raise ValueError(f"{path} has invalid type")
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ValueError(f"{path} must be finite")


def _positive_integer(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")


def _relative_path(value: str, path: str, *, stage13_only: bool = False) -> None:
    candidate = Path(value)
    if not value.strip() or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{path} must be a safe relative path")
    lowered = {part.lower() for part in candidate.parts}
    if lowered.intersection({".git", ".venv"}) or tuple(candidate.parts[:2]) == ("data", "raw"):
        raise ValueError(f"{path} targets a protected directory")
    if stage13_only and candidate.as_posix().rstrip("/") != "reports/stage13":
        raise ValueError(f"{path} must be reports/stage13")


def _windows(values: Any, required: list[int], path: str) -> None:
    if not isinstance(values, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise ValueError(f"{path} must contain integers")
    if values != sorted(set(values)) or values != required:
        raise ValueError(f"{path} must equal {required}")


def load_stage13_config(path: Path) -> Stage13Config:
    raw_bytes = Path(path).read_bytes()
    loaded = yaml.safe_load(raw_bytes)
    _shape(loaded, _SCHEMA, "stage13")
    assert isinstance(loaded, dict)
    if loaded["stage"] != 13:
        raise ValueError("stage13.stage must be 13")
    if not loaded["schema_version"].strip():
        raise ValueError("stage13.schema_version cannot be empty")
    _positive_integer(loaded["universe"]["expected_symbol_count"], "stage13.universe.expected_symbol_count")
    if loaded["universe"]["expected_symbol_count"] != 16:
        raise ValueError("Stage 13 requires exactly 16 target stocks")
    for key in ("price_lookback_days", "range_lookback_days", "event_lookback_days", "financial_periods"):
        _positive_integer(loaded["presentation"][key], f"stage13.presentation.{key}")
    dpi = loaded["presentation"]["image_dpi"]
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise ValueError("stage13.presentation.image_dpi must be within [72, 600]")
    precision = loaded["presentation"]["float_precision"]
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 15:
        raise ValueError("stage13.presentation.float_precision must be within [0, 15]")
    if loaded["presentation"]["image_format"].lower() != "png":
        raise ValueError("Stage 13 image_format must be png")
    _windows(loaded["moving_averages"]["price"], [3, 5, 7, 10, 13, 20, 21], "stage13.moving_averages.price")
    _windows(loaded["moving_averages"]["volume"], [5, 20], "stage13.moving_averages.volume")
    for key in ("feature_database", "activity_database"):
        _relative_path(loaded["inputs"][key], f"stage13.inputs.{key}")
    _relative_path(loaded["outputs"]["reports_dir"], "stage13.outputs.reports_dir", stage13_only=True)
    for key in ("charts_subdir", "tables_subdir", "sql_subdir"):
        value = loaded["outputs"][key]
        if not value.strip() or Path(value).is_absolute() or len(Path(value).parts) != 1:
            raise ValueError(f"stage13.outputs.{key} must be one safe relative directory name")
    if not all(loaded["quality"].values()):
        raise ValueError("All Stage 13 quality safeguards must be enabled")
    return Stage13Config(raw=loaded, sha256=hashlib.sha256(raw_bytes).hexdigest())
