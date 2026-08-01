from __future__ import annotations

import numpy as np
import pandas as pd

from akshare_data_test.quality.style_checks import _compare_frames, run_stage9_quality_checks
from test_stage9_repository import frames
from test_style_features import daily


def quality(source=None, mutate_features=None, mutate_profiles=None):
    features, profiles, _, _ = frames()
    if mutate_features:
        mutate_features(features)
    if mutate_profiles:
        mutate_profiles(profiles)
    source = daily() if source is None else source
    return run_stage9_quality_checks(
        source, features, profiles, run_id="style-run",
        as_of_date=daily().trade_date.max(), expected_symbols=["000001"],
        expected_windows=[20, 40, 60], config_hash="a" * 64,
        expected_config_hash="a" * 64,
        checked_at=pd.Timestamp("2026-07-27", tz="UTC"),
    )


def result(frame, name):
    return frame.loc[frame.check_name.eq(name)].iloc[0]


def test_quality_baseline_is_data_driven_and_has_all_required_prechecks():
    checks = quality()
    required = {
        "input_adjust_type_valid", "input_schema_complete", "input_primary_key_unique",
        "symbol_coverage_complete", "window_observation_sufficient",
        "window_date_order_valid", "no_future_data_leakage", "feature_value_finite",
        "box_bounds_valid", "confidence_range_valid", "style_label_valid",
        "explanation_complete", "insufficient_history_not_classified",
        "stage8_blocked_not_treated_as_zero", "feature_profile_row_count_consistent",
        "run_id_consistent", "configuration_hash_consistent",
    }
    assert required.issubset(set(checks.check_name))
    assert not ((checks.severity == "ERROR") & (checks.status == "FAIL")).any()


def test_each_safety_check_can_fail_from_real_values():
    scenarios = {
        "input_adjust_type_valid": quality(daily().assign(adjust_type="raw")),
        "input_primary_key_unique": quality(pd.concat([daily(), daily().iloc[[0]]])),
        "symbol_coverage_complete": quality(daily().assign(symbol="000002")),
        "no_future_data_leakage": quality(pd.concat([daily(), daily().iloc[[0]].assign(trade_date=pd.Timestamp("2027-01-01"))])),
        "window_date_order_valid": quality(mutate_features=lambda f: f.__setitem__("window_start", pd.Timestamp("2027-01-01"))),
        "box_bounds_valid": quality(mutate_features=lambda f: f.__setitem__("rolling_low", -1)),
        "confidence_range_valid": quality(mutate_profiles=lambda p: p.__setitem__("confidence", 2)),
        "style_label_valid": quality(mutate_profiles=lambda p: p.__setitem__("style_label", "确定主力操纵")),
        "explanation_complete": quality(mutate_profiles=lambda p: p.__setitem__("explanation", "买入信号")),
        "stage8_blocked_not_treated_as_zero": quality(mutate_features=lambda f: (f.__setitem__("stage8_publication_status", "blocked"), f.__setitem__("stage8_formal_event_frequency", 0))),
        "run_id_consistent": quality(mutate_features=lambda f: f.__setitem__("run_id", "wrong")),
    }
    for name, checks in scenarios.items():
        assert result(checks, name).status == "FAIL", name


def test_artifact_comparison_normalizes_nulls_and_uses_explicit_float_tolerance():
    database = pd.DataFrame({"id": [1, 2], "value": [None, 0.5]})
    equivalent = pd.DataFrame({"id": [1, 2], "value": [pd.NA, 0.5 + 5e-13]})
    matches, _ = _compare_frames(
        database, equivalent, columns=["id", "value"], sort_by=["id"]
    )
    assert matches

    nan_is_not_zero = pd.DataFrame({"id": [1, 2], "value": [0.0, 0.5]})
    matches, _ = _compare_frames(
        database, nan_is_not_zero, columns=["id", "value"], sort_by=["id"]
    )
    assert not matches

    outside_tolerance = pd.DataFrame({"id": [1, 2], "value": [np.nan, 0.5 + 2e-12]})
    matches, _ = _compare_frames(
        database, outside_tolerance, columns=["id", "value"], sort_by=["id"]
    )
    assert not matches
