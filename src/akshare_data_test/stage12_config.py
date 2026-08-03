"""Strict, closed-world configuration for Stage 12."""
from __future__ import annotations

import hashlib
import codecs
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Stage12Config:
    raw: dict[str, Any]
    sha256: str

    @property
    def model_version(self) -> str:
        return str(self.raw["model_version"])


_SCHEMA: dict[str, Any] = {
    "schema_version": str,
    "model_version": str,
    "price_adjust_type": str,
    "ranking_method": str,
    "missing_value_policy": str,
    "active_stock": {
        "lookback_days": int, "min_valid_days": int,
        "min_average_amount": (int, float), "max_zero_volume_ratio": (int, float),
        "score_threshold": (int, float),
        "weights": {
            "amount_percentile": (int, float),
            "volume_percentile": (int, float),
            "turnover_percentile": (int, float),
        },
    },
    "volume_breakout": {
        "lookback_days": int, "min_history_days": int,
        "ratio_to_mean_threshold": (int, float),
        "ratio_to_median_threshold": (int, float),
        "zscore_threshold": (int, float), "minimum_volume": (int, float),
        "require_positive_return": bool, "require_amount_confirmation": bool,
        "amount_change_threshold": (int, float),
    },
    "range_bound": {
        "lookback_days": int, "min_history_days": int,
        "max_range_width_pct": (int, float),
        "max_abs_slope_pct": (int, float), "max_trend_r2": (int, float),
        "max_outside_ratio": (int, float),
        "inner_quantile_lower": (int, float),
        "inner_quantile_upper": (int, float),
    },
    "fundamental_price_volume": {
        "missing_subscore_policy": str,
        "signal_thresholds": {"strong": (int, float), "moderate": (int, float)},
        "fundamental_weights": {
            "valuation_score": (int, float), "profitability_score": (int, float),
            "growth_score": (int, float), "quality_score": (int, float),
        },
        "composite_weights": {
            "fundamental_score": (int, float), "activity_score": (int, float),
            "volume_breakout_score": (int, float), "range_bound_score": (int, float),
            "price_momentum_score": (int, float),
        },
    },
    "output": {"csv_encoding": str, "stable_sort": bool, "float_precision": int},
    "quality_gates": {
        "require_unique_input_keys": bool, "require_unique_output_keys": bool,
        "require_finite_scores": bool, "require_no_future_data": bool,
        "require_all_instruments": bool,
    },
}


def _validate_shape(value: Any, schema: Any, path: str) -> None:
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be a mapping")
        unknown = sorted(set(value).difference(schema))
        missing = sorted(set(schema).difference(value))
        if unknown:
            raise ValueError(f"{path} contains unknown keys: {unknown}")
        if missing:
            raise ValueError(f"{path} is missing required keys: {missing}")
        for key, child in schema.items():
            _validate_shape(value[key], child, f"{path}.{key}")
        return
    expected = schema if isinstance(schema, tuple) else (schema,)
    if bool in expected:
        if type(value) is not bool:
            raise ValueError(f"{path} must be a boolean")
    elif isinstance(value, bool) or not isinstance(value, expected):
        names = "/".join(item.__name__ for item in expected)
        raise ValueError(f"{path} must be {names}")
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ValueError(f"{path} must be finite")


def _validate_weights(config: dict[str, Any], path: str) -> None:
    weights = config
    if any(float(value) < 0 for value in weights.values()):
        raise ValueError(f"{path} weights must be non-negative")
    total = sum(float(value) for value in weights.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"{path} weights must sum to 1 within 1e-9, got {total}")


def _require_range(
    value: int | float, path: str, *, minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{path} must be >= {minimum}, got {value!r}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{path} must be <= {maximum}, got {value!r}")


def _require_nonempty(value: str, path: str) -> None:
    if not value.strip():
        raise ValueError(f"{path} must be a non-empty string, got {value!r}")


def load_stage12_config(path: Path) -> Stage12Config:
    """Load Stage 12 YAML and reject every unrecognised or ambiguous value."""
    raw_bytes = path.read_bytes()
    loaded = yaml.safe_load(raw_bytes)
    _validate_shape(loaded, _SCHEMA, "stage12")
    assert isinstance(loaded, dict)
    _require_nonempty(loaded["schema_version"], "stage12.schema_version")
    _require_nonempty(loaded["model_version"], "stage12.model_version")
    if loaded["price_adjust_type"] != "qfq":
        raise ValueError("Stage 12 price_adjust_type must be qfq")
    if loaded["ranking_method"] not in {"average", "min", "dense"}:
        raise ValueError("Unsupported Stage 12 ranking_method")
    if loaded["missing_value_policy"] != "exclude_and_warn":
        raise ValueError("Unsupported Stage 12 missing_value_policy")
    active, breakout, range_cfg = (
        loaded["active_stock"], loaded["volume_breakout"], loaded["range_bound"]
    )
    for name, section in (("active_stock", active), ("volume_breakout", breakout), ("range_bound", range_cfg)):
        if section["lookback_days"] <= 0:
            raise ValueError(
                f"stage12.{name}.lookback_days must be an integer >= 1, "
                f"got {section['lookback_days']!r}"
            )
    if active["min_valid_days"] > active["lookback_days"] or active["min_valid_days"] <= 0:
        raise ValueError(
            "stage12.active_stock.min_valid_days must be within [1, lookback_days], "
            f"got {active['min_valid_days']!r}"
        )
    if breakout["min_history_days"] > breakout["lookback_days"] or breakout["min_history_days"] <= 0:
        raise ValueError(
            "stage12.volume_breakout.min_history_days must be within [1, lookback_days], "
            f"got {breakout['min_history_days']!r}"
        )
    if range_cfg["min_history_days"] > range_cfg["lookback_days"] or range_cfg["min_history_days"] <= 0:
        raise ValueError(
            "stage12.range_bound.min_history_days must be within [1, lookback_days], "
            f"got {range_cfg['min_history_days']!r}"
        )
    _require_range(active["min_average_amount"], "stage12.active_stock.min_average_amount", minimum=0)
    _require_range(active["max_zero_volume_ratio"], "stage12.active_stock.max_zero_volume_ratio", minimum=0, maximum=1)
    _require_range(active["score_threshold"], "stage12.active_stock.score_threshold", minimum=0, maximum=1)
    for key in (
        "ratio_to_mean_threshold", "ratio_to_median_threshold", "zscore_threshold",
        "minimum_volume",
    ):
        _require_range(breakout[key], f"stage12.volume_breakout.{key}", minimum=0)
    _require_range(
        breakout["amount_change_threshold"],
        "stage12.volume_breakout.amount_change_threshold", minimum=-1,
    )
    _require_range(range_cfg["max_range_width_pct"], "stage12.range_bound.max_range_width_pct", minimum=0)
    _require_range(range_cfg["max_abs_slope_pct"], "stage12.range_bound.max_abs_slope_pct", minimum=0)
    for key in ("max_trend_r2", "max_outside_ratio", "inner_quantile_lower", "inner_quantile_upper"):
        _require_range(range_cfg[key], f"stage12.range_bound.{key}", minimum=0, maximum=1)
    if range_cfg["inner_quantile_lower"] >= range_cfg["inner_quantile_upper"]:
        raise ValueError(
            "stage12.range_bound inner quantiles must satisfy lower < upper, got "
            f"{range_cfg['inner_quantile_lower']!r} >= {range_cfg['inner_quantile_upper']!r}"
        )
    fpv = loaded["fundamental_price_volume"]
    if fpv["missing_subscore_policy"] != "renormalize_available":
        raise ValueError("Unsupported missing_subscore_policy")
    for key in ("strong", "moderate"):
        _require_range(
            fpv["signal_thresholds"][key],
            f"stage12.fundamental_price_volume.signal_thresholds.{key}",
            minimum=0, maximum=1,
        )
    if fpv["signal_thresholds"]["strong"] < fpv["signal_thresholds"]["moderate"]:
        raise ValueError(
            "stage12.fundamental_price_volume.signal_thresholds must satisfy "
            f"0 <= moderate <= strong <= 1, got moderate={fpv['signal_thresholds']['moderate']!r}, "
            f"strong={fpv['signal_thresholds']['strong']!r}"
        )
    _validate_weights(active["weights"], "active_stock")
    _validate_weights(fpv["fundamental_weights"], "fundamental_price_volume.fundamental")
    _validate_weights(fpv["composite_weights"], "fundamental_price_volume.composite")
    precision = loaded["output"]["float_precision"]
    if not 0 <= precision <= 15:
        raise ValueError(
            "stage12.output.float_precision must be an integer within [0, 15], "
            f"got {precision!r}"
        )
    encoding = loaded["output"]["csv_encoding"]
    _require_nonempty(encoding, "stage12.output.csv_encoding")
    try:
        codecs.lookup(encoding)
    except LookupError as exc:
        raise ValueError(
            f"stage12.output.csv_encoding must name a registered Python codec, got {encoding!r}"
        ) from exc
    return Stage12Config(raw=loaded, sha256=hashlib.sha256(raw_bytes).hexdigest())
