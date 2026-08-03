from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml

from akshare_data_test.stage12_config import load_stage12_config


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ConfigCase:
    path: tuple[str, ...]
    invalid_value: Any
    expected_field: str
    operation: Literal["set", "delete"] = "set"


REQUIRED_CONFIG_CASES = [
    pytest.param(
        ConfigCase(("unknown",), True, "unknown"),
        id="required-01-unknown-root-key",
    ),
    pytest.param(
        ConfigCase(("active_stock", "unknown"), True, "unknown"),
        id="required-02-unknown-nested-key",
    ),
    pytest.param(
        ConfigCase(
            ("active_stock", "min_valid_days"),
            None,
            "stage12.active_stock",
            operation="delete",
        ),
        id="required-03-missing-required-key",
    ),
    pytest.param(
        ConfigCase(
            ("volume_breakout", "require_positive_return"),
            "false",
            "stage12.volume_breakout.require_positive_return",
        ),
        id="required-04-string-is-not-boolean",
    ),
    pytest.param(
        ConfigCase(
            ("active_stock", "weights", "amount_percentile"),
            0.9,
            "active_stock weights",
        ),
        id="required-05-weights-must-sum-to-one",
    ),
    pytest.param(
        ConfigCase(
            ("range_bound", "min_history_days"),
            41,
            "stage12.range_bound.min_history_days",
        ),
        id="required-06-min-history-exceeds-lookback",
    ),
    pytest.param(
        ConfigCase(
            ("active_stock", "score_threshold"),
            float("inf"),
            "stage12.active_stock.score_threshold",
        ),
        id="required-07-score-positive-infinity",
    ),
    pytest.param(
        ConfigCase(
            ("active_stock", "score_threshold"),
            float("nan"),
            "stage12.active_stock.score_threshold",
        ),
        id="required-08-score-nan",
    ),
    pytest.param(
        ConfigCase(
            ("volume_breakout", "lookback_days"),
            "20",
            "stage12.volume_breakout.lookback_days",
        ),
        id="required-09-lookback-string",
    ),
    pytest.param(
        ConfigCase(
            ("volume_breakout", "lookback_days"),
            True,
            "stage12.volume_breakout.lookback_days",
        ),
        id="required-10-lookback-boolean",
    ),
    pytest.param(
        ConfigCase(
            ("volume_breakout", "lookback_days"),
            1.5,
            "stage12.volume_breakout.lookback_days",
        ),
        id="required-11-lookback-float",
    ),
    pytest.param(
        ConfigCase(
            ("fundamental_price_volume", "signal_thresholds", "strong"),
            0.4,
            "stage12.fundamental_price_volume.signal_thresholds",
        ),
        id="required-12-signal-threshold-order",
    ),
]


# The independent audit counted signal-threshold upper-bound validation as one
# Extended category.  ``strong=2.0`` is its representative matrix case;
# ``moderate=1.5`` remains a separate supplementary regression below.
EXTENDED_CONFIG_CASES = [
    pytest.param(
        ConfigCase(
            ("volume_breakout", "ratio_to_mean_threshold"),
            -1,
            "stage12.volume_breakout.ratio_to_mean_threshold",
        ),
        id="extended-01-negative-mean-ratio",
    ),
    pytest.param(
        ConfigCase(
            ("range_bound", "max_range_width_pct"),
            -0.1,
            "stage12.range_bound.max_range_width_pct",
        ),
        id="extended-02-negative-range-width",
    ),
    pytest.param(
        ConfigCase(
            ("fundamental_price_volume", "signal_thresholds", "strong"),
            2.0,
            "stage12.fundamental_price_volume.signal_thresholds.strong",
        ),
        id="extended-03-strong-signal-above-one",
    ),
    pytest.param(
        ConfigCase(
            ("active_stock", "min_average_amount"),
            -1,
            "stage12.active_stock.min_average_amount",
        ),
        id="extended-04-negative-minimum-average-amount",
    ),
    pytest.param(
        ConfigCase(
            ("volume_breakout", "minimum_volume"),
            -1,
            "stage12.volume_breakout.minimum_volume",
        ),
        id="extended-05-negative-minimum-volume",
    ),
    pytest.param(
        ConfigCase(
            ("output", "float_precision"),
            -1,
            "stage12.output.float_precision",
        ),
        id="extended-06-negative-float-precision",
    ),
]


NUMERIC_STAGE12_CONFIG_FIELDS = [
    ("active_stock", "lookback_days"),
    ("active_stock", "min_valid_days"),
    ("active_stock", "min_average_amount"),
    ("active_stock", "max_zero_volume_ratio"),
    ("active_stock", "score_threshold"),
    ("active_stock", "weights", "amount_percentile"),
    ("active_stock", "weights", "volume_percentile"),
    ("active_stock", "weights", "turnover_percentile"),
    ("volume_breakout", "lookback_days"),
    ("volume_breakout", "min_history_days"),
    ("volume_breakout", "ratio_to_mean_threshold"),
    ("volume_breakout", "ratio_to_median_threshold"),
    ("volume_breakout", "zscore_threshold"),
    ("volume_breakout", "minimum_volume"),
    ("volume_breakout", "amount_change_threshold"),
    ("range_bound", "lookback_days"),
    ("range_bound", "min_history_days"),
    ("range_bound", "max_range_width_pct"),
    ("range_bound", "max_abs_slope_pct"),
    ("range_bound", "max_trend_r2"),
    ("range_bound", "max_outside_ratio"),
    ("range_bound", "inner_quantile_lower"),
    ("range_bound", "inner_quantile_upper"),
    ("fundamental_price_volume", "signal_thresholds", "strong"),
    ("fundamental_price_volume", "signal_thresholds", "moderate"),
    ("fundamental_price_volume", "fundamental_weights", "valuation_score"),
    ("fundamental_price_volume", "fundamental_weights", "profitability_score"),
    ("fundamental_price_volume", "fundamental_weights", "growth_score"),
    ("fundamental_price_volume", "fundamental_weights", "quality_score"),
    ("fundamental_price_volume", "composite_weights", "fundamental_score"),
    ("fundamental_price_volume", "composite_weights", "activity_score"),
    ("fundamental_price_volume", "composite_weights", "volume_breakout_score"),
    ("fundamental_price_volume", "composite_weights", "range_bound_score"),
    ("fundamental_price_volume", "composite_weights", "price_momentum_score"),
    ("output", "float_precision"),
]

NON_FINITE_VALUES = [
    ("nan", float("nan")),
    ("positive-infinity", float("inf")),
    ("negative-infinity", float("-inf")),
]

NON_FINITE_CONFIG_CASES = [
    pytest.param(
        ConfigCase(path, invalid_value, f"stage12.{'.'.join(path)}"),
        id=f"{'.'.join(path)}-{value_id}",
    )
    for path in NUMERIC_STAGE12_CONFIG_FIELDS
    for value_id, invalid_value in NON_FINITE_VALUES
]


ADDITIONAL_CONFIG_CASES = [
    pytest.param(
        ConfigCase(
            ("volume_breakout", "ratio_to_median_threshold"),
            -1,
            "stage12.volume_breakout.ratio_to_median_threshold",
        ),
        id="negative-median-ratio",
    ),
    pytest.param(
        ConfigCase(
            ("volume_breakout", "zscore_threshold"),
            -1,
            "stage12.volume_breakout.zscore_threshold",
        ),
        id="negative-zscore",
    ),
    pytest.param(
        ConfigCase(
            ("range_bound", "max_abs_slope_pct"),
            -0.1,
            "stage12.range_bound.max_abs_slope_pct",
        ),
        id="negative-maximum-slope",
    ),
    pytest.param(
        ConfigCase(
            ("fundamental_price_volume", "signal_thresholds", "moderate"),
            1.5,
            "stage12.fundamental_price_volume.signal_thresholds.moderate",
        ),
        id="moderate-signal-above-one",
    ),
    pytest.param(
        ConfigCase(
            ("output", "float_precision"),
            1.5,
            "stage12.output.float_precision",
        ),
        id="float-precision-is-float",
    ),
    pytest.param(
        ConfigCase(
            ("output", "float_precision"),
            True,
            "stage12.output.float_precision",
        ),
        id="float-precision-is-boolean",
    ),
    pytest.param(
        ConfigCase(
            ("output", "float_precision"),
            16,
            "stage12.output.float_precision",
        ),
        id="float-precision-above-maximum",
    ),
    pytest.param(
        ConfigCase(
            ("output", "csv_encoding"),
            "not-a-real-codec",
            "stage12.output.csv_encoding",
        ),
        id="unknown-csv-codec",
    ),
]


@pytest.fixture
def valid_stage12_config() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config/stage12.yml").read_text(encoding="utf-8"))


def _set_path(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _delete_path(config: dict[str, Any], path: tuple[str, ...]) -> None:
    target = config
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]


def _write_case(tmp_path: Path, valid_config: dict[str, Any], case: ConfigCase) -> Path:
    config = copy.deepcopy(valid_config)
    if case.operation == "delete":
        _delete_path(config, case.path)
    else:
        _set_path(config, case.path, case.invalid_value)
    path = tmp_path / "stage12-invalid.yml"
    path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _assert_config_case_is_blocked(
    tmp_path: Path, valid_config: dict[str, Any], case: ConfigCase
) -> None:
    with pytest.raises(ValueError) as error:
        load_stage12_config(_write_case(tmp_path, valid_config, case))
    assert case.expected_field in str(error.value)


def test_config_is_valid_and_hash_stable():
    first = load_stage12_config(ROOT / "config/stage12.yml")
    second = load_stage12_config(ROOT / "config/stage12.yml")
    assert first.sha256 == second.sha256
    assert first.raw["active_stock"]["lookback_days"] == 120
    assert first.raw["range_bound"]["lookback_days"] == 40


@pytest.mark.parametrize("case", REQUIRED_CONFIG_CASES)
def test_required_configuration_matrix_is_blocked(
    tmp_path: Path, valid_stage12_config: dict[str, Any], case: ConfigCase
) -> None:
    _assert_config_case_is_blocked(tmp_path, valid_stage12_config, case)


@pytest.mark.parametrize("case", EXTENDED_CONFIG_CASES)
def test_extended_configuration_matrix_is_blocked(
    tmp_path: Path, valid_stage12_config: dict[str, Any], case: ConfigCase
) -> None:
    _assert_config_case_is_blocked(tmp_path, valid_stage12_config, case)


@pytest.mark.parametrize("case", NON_FINITE_CONFIG_CASES)
def test_all_numeric_config_fields_reject_non_finite(
    tmp_path: Path, valid_stage12_config: dict[str, Any], case: ConfigCase
) -> None:
    _assert_config_case_is_blocked(tmp_path, valid_stage12_config, case)


@pytest.mark.parametrize("case", ADDITIONAL_CONFIG_CASES)
def test_additional_configuration_contracts_are_blocked(
    tmp_path: Path, valid_stage12_config: dict[str, Any], case: ConfigCase
) -> None:
    _assert_config_case_is_blocked(tmp_path, valid_stage12_config, case)


def test_required_configuration_matrix_size():
    assert len(REQUIRED_CONFIG_CASES) == 12


def test_extended_configuration_matrix_size():
    assert len(EXTENDED_CONFIG_CASES) == 6


def test_non_finite_configuration_matrix_size():
    assert len(NUMERIC_STAGE12_CONFIG_FIELDS) == 35
    assert len(set(NUMERIC_STAGE12_CONFIG_FIELDS)) == 35
    assert len(NON_FINITE_VALUES) == 3
    assert len(NON_FINITE_CONFIG_CASES) == 105
