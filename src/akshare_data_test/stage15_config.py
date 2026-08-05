"""Strict configuration loader for Stage 15 quality control."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import yaml

from .config import load_universe


ALLOWED_CHECK_ITEMS = {
    "last_5_days_close_volume",
    "latest_revenue",
    "latest_net_profit",
    "latest_pe_dynamic",
    "latest_pb",
    "recent_limit_up_day",
    "next_day_open_after_limit_up",
}

REQUIRED_INPUT_KEYS = {
    "stage5_database",
    "stage8_database",
    "stage3_market_coverage",
    "stage4_financial_coverage",
    "interface_smoke_csv",
}
REQUIRED_OUTPUT_KEYS = {"reports_dir", "database_dir"}
REQUIRED_TOP_LEVEL = {
    "stage",
    "schema_version",
    "model_version",
    "universe",
    "inputs",
    "outputs",
    "daily_checks",
    "cross_validation",
    "performance",
    "stage8",
    "risk",
    "quality",
}
REQUIRED_TABLES = (
    "fact_" + "stock_" + "daily",
    "fact_" + "stock_" + "spot",
    "fact_" + "financial_" + "abstract",
    "fact_" + "financial_" + "indicator",
    "fact_" + "financial_" + "statement",
    "fact_" + "stock_" + "fund_" + "flow",
)


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a mapping")
    return value


def _require_keys(value: dict[str, Any], required: set[str], path: str) -> None:
    missing = sorted(required.difference(value))
    if missing:
        raise ValueError(f"{path} is missing required keys: {missing}")


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: Any, path: str, *, upper: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    if upper is not None and value > upper:
        raise ValueError(f"{path} must not exceed {upper}")
    return value


def _require_finite_float(
    value: Any, path: str, *, lower: float | None = None, upper: float | None = None
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite")
    if lower is not None and number < lower:
        raise ValueError(f"{path} must be at least {lower}")
    if upper is not None and number > upper:
        raise ValueError(f"{path} must not exceed {upper}")
    return number


def _safe_relative_path(value: str, path: str, *, exact: str | None = None) -> str:
    candidate = Path(value)
    if not value.strip() or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{path} must be a safe relative path")
    lowered = {part.lower() for part in candidate.parts}
    if lowered.intersection({".git", ".venv"}) or tuple(candidate.parts[:2]) == (
        "data",
        "raw",
    ):
        raise ValueError(f"{path} targets a protected directory")
    if exact is not None and candidate.as_posix().rstrip("/") != exact:
        raise ValueError(f"{path} must be {exact}")
    return candidate.as_posix()


def _require_string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} must be a non-empty string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{path} must contain non-empty strings")
        result.append(item.strip())
    return result


def _require_symbols(value: Any, path: str, allowed: set[str]) -> list[str]:
    symbols = _require_string_list(value, path)
    if any(len(item) != 6 or not item.isdigit() for item in symbols):
        raise ValueError(f"{path} must contain 6-digit symbols")
    unknown = sorted(set(symbols).difference(allowed))
    if unknown:
        raise ValueError(f"{path} contains symbols outside the frozen universe: {unknown}")
    if len(symbols) != len(set(symbols)):
        raise ValueError(f"{path} must not contain duplicates")
    return symbols


def _validate_inputs(inputs: Any) -> None:
    payload = _require_mapping(inputs, "stage15.inputs")
    _require_keys(payload, REQUIRED_INPUT_KEYS, "stage15.inputs")
    for key in ("stage5_database", "stage3_market_coverage", "stage4_financial_coverage", "interface_smoke_csv"):
        _safe_relative_path(_require_string(payload[key], f"stage15.inputs.{key}"), f"stage15.inputs.{key}")
    stage8 = payload["stage8_database"]
    if stage8 is not None:
        _safe_relative_path(_require_string(stage8, "stage15.inputs.stage8_database"), "stage15.inputs.stage8_database")


def _validate_outputs(outputs: Any) -> None:
    payload = _require_mapping(outputs, "stage15.outputs")
    _require_keys(payload, REQUIRED_OUTPUT_KEYS, "stage15.outputs")
    _safe_relative_path(
        _require_string(payload["reports_dir"], "stage15.outputs.reports_dir"),
        "stage15.outputs.reports_dir",
        exact="reports/stage15",
    )
    _safe_relative_path(
        _require_string(payload["database_dir"], "stage15.outputs.database_dir"),
        "stage15.outputs.database_dir",
        exact="database/stage15",
    )


def _validate_daily_checks(daily: Any, expected_tables: set[str]) -> None:
    payload = _require_mapping(daily, "stage15.daily_checks")
    tolerance = _require_positive_int(
        payload.get("latest_trade_date_tolerance_days"),
        "stage15.daily_checks.latest_trade_date_tolerance_days",
        upper=30,
    )
    if tolerance == 0:
        raise ValueError("stage15.daily_checks.latest_trade_date_tolerance_days must be positive")
    _require_finite_float(
        payload.get("row_count_decline_ratio"),
        "stage15.daily_checks.row_count_decline_ratio",
        lower=0.0,
        upper=1.0,
    )
    _require_finite_float(
        payload.get("pe_pb_missing_rate_threshold"),
        "stage15.daily_checks.pe_pb_missing_rate_threshold",
        lower=0.0,
        upper=1.0,
    )
    _require_finite_float(
        payload.get("financial_key_fields_coverage_threshold"),
        "stage15.daily_checks.financial_key_fields_coverage_threshold",
        lower=0.0,
        upper=1.0,
    )
    minimums = _require_mapping(
        payload.get("row_count_expected_minimum"),
        "stage15.daily_checks.row_count_expected_minimum",
    )
    if set(minimums) != expected_tables:
        raise ValueError(
            "stage15.daily_checks.row_count_expected_minimum tables must match the Stage 5 fact tables"
        )
    for table in expected_tables:
        _require_positive_int(minimums[table], f"stage15.daily_checks.row_count_expected_minimum.{table}")
    columns = _require_mapping(
        payload.get("expected_columns"),
        "stage15.daily_checks.expected_columns",
    )
    if set(columns) != expected_tables:
        raise ValueError("stage15.daily_checks.expected_columns tables must match the Stage 5 fact tables")
    for table in expected_tables:
        listed = columns[table]
        if not isinstance(listed, list) or not listed or any(
            not isinstance(item, str) or not item.strip() for item in listed
        ):
            raise ValueError(f"stage15.daily_checks.expected_columns.{table} must be a non-empty string list")
        if len(listed) != len(set(listed)):
            raise ValueError(f"stage15.daily_checks.expected_columns.{table} must not contain duplicates")


def _validate_cross_validation(cross: Any, allowed_symbols: set[str]) -> None:
    payload = _require_mapping(cross, "stage15.cross_validation")
    symbols = _require_symbols(
        payload.get("symbols"), "stage15.cross_validation.symbols", allowed_symbols
    )
    if not 2 <= len(symbols) <= 3:
        raise ValueError("stage15.cross_validation.symbols must contain 2 or 3 symbols")
    _require_positive_int(
        payload.get("last_trade_days"),
        "stage15.cross_validation.last_trade_days",
        upper=10,
    )
    adjust = _require_string(
        payload.get("price_adjust_type"), "stage15.cross_validation.price_adjust_type"
    )
    if adjust not in {"raw", "qfq"}:
        raise ValueError("stage15.cross_validation.price_adjust_type must be raw or qfq")
    items = _require_string_list(
        payload.get("check_items"), "stage15.cross_validation.check_items"
    )
    unknown = sorted(set(items).difference(ALLOWED_CHECK_ITEMS))
    if unknown:
        raise ValueError(f"stage15.cross_validation.check_items contains unknown items: {unknown}")
    if len(items) != len(set(items)):
        raise ValueError("stage15.cross_validation.check_items must not contain duplicates")


def _validate_performance(performance: Any) -> None:
    payload = _require_mapping(performance, "stage15.performance")
    _require_finite_float(
        payload.get("elapsed_spike_multiplier"),
        "stage15.performance.elapsed_spike_multiplier",
        lower=1.0,
    )
    maximums = _require_mapping(
        payload.get("max_elapsed_seconds"), "stage15.performance.max_elapsed_seconds"
    )
    if not maximums:
        raise ValueError("stage15.performance.max_elapsed_seconds must not be empty")
    for interface, seconds in maximums.items():
        value = _require_finite_float(
            seconds, f"stage15.performance.max_elapsed_seconds.{interface}", lower=0.0
        )
        if value <= 0:
            raise ValueError(
                f"stage15.performance.max_elapsed_seconds.{interface} must be positive"
            )


def _validate_stage8(stage8: Any) -> None:
    payload = _require_mapping(stage8, "stage15.stage8")
    for key in ("required_for_cross_validation", "block_whole_run"):
        if type(payload.get(key)) is not bool:
            raise ValueError(f"stage15.stage8.{key} must be a boolean")
    if payload.get("required_for_cross_validation") is not True:
        raise ValueError("stage15.stage8.required_for_cross_validation must be true")
    if payload.get("block_whole_run") is not False:
        raise ValueError("stage15.stage8.block_whole_run must be false")
    _require_string_list(
        payload.get("blocker_codes"), "stage15.stage8.blocker_codes"
    )


def _validate_risk(risk: Any) -> None:
    payload = _require_mapping(risk, "stage15.risk")
    for key in ("categories", "severities", "statuses"):
        _require_string_list(payload.get(key), f"stage15.risk.{key}")


def _validate_quality(quality: Any) -> None:
    payload = _require_mapping(quality, "stage15.quality")
    for key in ("require_offline", "require_read_only_input"):
        if type(payload.get(key)) is not bool:
            raise ValueError(f"stage15.quality.{key} must be a boolean")
    if payload.get("require_offline") is not True or payload.get("require_read_only_input") is not True:
        raise ValueError("All Stage 15 quality safeguards must be enabled")


def load_stage15_config(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate Stage 15 configuration with a reproducible hash."""
    raw_bytes = Path(path).read_bytes()
    loaded = yaml.safe_load(raw_bytes)
    if not isinstance(loaded, dict):
        raise ValueError("stage15 config root must be a mapping")
    _require_keys(loaded, REQUIRED_TOP_LEVEL, "stage15")
    if loaded.get("stage") != 15:
        raise ValueError("stage15.stage must be 15")
    if not _require_string(loaded.get("schema_version"), "stage15.schema_version"):
        raise ValueError("stage15.schema_version cannot be empty")
    if not _require_string(loaded.get("model_version"), "stage15.model_version"):
        raise ValueError("stage15.model_version cannot be empty")
    universe = _require_mapping(loaded.get("universe"), "stage15.universe")
    expected_count = universe.get("expected_symbol_count")
    if type(expected_count) is not int or expected_count != 16:
        raise ValueError("stage15.universe.expected_symbol_count must be 16")
    universe_config = load_universe()
    allowed_symbols = {item.symbol for item in universe_config.stocks}
    _validate_inputs(loaded.get("inputs"))
    _validate_outputs(loaded.get("outputs"))
    _validate_daily_checks(loaded.get("daily_checks"), set(REQUIRED_TABLES))
    _validate_cross_validation(loaded.get("cross_validation"), allowed_symbols)
    _validate_performance(loaded.get("performance"))
    _validate_stage8(loaded.get("stage8"))
    _validate_risk(loaded.get("risk"))
    _validate_quality(loaded.get("quality"))
    return loaded, hashlib.sha256(raw_bytes).hexdigest()
