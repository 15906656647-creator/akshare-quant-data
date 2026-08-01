from __future__ import annotations

import copy

import numpy as np
import yaml

from akshare_data_test.style_classification import build_style_profiles, classify_style
from akshare_data_test.stage9_build import _hash
from akshare_data_test.style_features import Stage9Config, load_stage9_config
from test_style_features import CONFIG, compute, daily


def classified(close, mutate=None):
    frame = daily(close=np.asarray(close, dtype=float))
    if mutate:
        mutate(frame)
    feature = compute(frame, windows=[40]).iloc[0]
    return classify_style(feature, CONFIG)


def test_trend_is_not_misclassified_as_sideways():
    result = classified(np.linspace(10, 30, 80))
    assert result["style_label"] == "趋势型"
    assert 0 <= result["confidence"] <= 0.95


def test_gentle_box_and_high_volatility_have_explainable_outputs():
    gentle = classified(10 + 0.15 * np.sin(np.arange(80)))
    volatile = classified(10 + 1.5 * np.sin(np.arange(80)))
    assert gentle["style_label"] in {"温和箱体型", "低活跃盘整型", "未分类或混合型"}
    assert volatile["style_label"] in {"高波动震荡型", "放量冲击型", "未分类或混合型"}
    for result in (gentle, volatile):
        assert "%" in result["explanation"] and "R²" in result["explanation"]
        assert "主力正在" not in result["explanation"]
        assert "不构成投资建议" in result["explanation"]


def test_volume_shock_and_low_activity_are_supported():
    def shocks(frame):
        frame.loc[45:70:5, "volume_ratio_20"] = 4
        frame.loc[45:70:5, "volume_share"] *= 5
    shock = classified(10 + 0.3 * np.sin(np.arange(80)), shocks)
    low = classified(10 + 0.03 * np.sin(np.arange(80)))
    assert shock["style_label"] in {"放量冲击型", "未分类或混合型", "高波动震荡型"}
    assert low["style_label"] in {"低活跃盘整型", "温和箱体型", "未分类或混合型"}


def test_insufficient_history_has_reduced_confidence():
    feature = compute(daily(39), windows=[40]).iloc[0]
    result = classify_style(feature, CONFIG)
    assert result["style_label"] == "数据不足"
    assert result["confidence"] < 0.2


def test_profiles_keep_model_lineage_and_research_status():
    features = compute(daily())
    profile = build_style_profiles(features, CONFIG).iloc[0]
    assert profile.primary_window == 40
    assert profile.model_version == "stage9_style_rules_v2"
    assert profile.config_version == "1.1.0"
    assert profile.publication_status == "research_only"
    assert 0 <= profile.confidence <= 1


def test_classification_weights_are_config_driven_and_hash_tracked(tmp_path):
    feature = compute(daily(close=10 + 0.4 * np.sin(np.arange(80))), windows=[40]).iloc[0]
    baseline = classify_style(feature, CONFIG)
    changed_raw = copy.deepcopy(CONFIG.raw)
    changed_raw["classification"]["weights"]["gentle_box"] = {
        "flat": 0.0,
        "inverse_r_squared": 1.0,
        "box": 0.0,
        "low_atr": 0.0,
        "touches": 0.0,
    }
    original_path = tmp_path / "original.yml"
    changed_path = tmp_path / "changed.yml"
    original_path.write_text(
        yaml.safe_dump(CONFIG.raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    changed_path.write_text(
        yaml.safe_dump(changed_raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    changed_config = load_stage9_config(changed_path)
    changed = classify_style(feature, changed_config)
    assert (changed["style_label"], changed["confidence"]) != (
        baseline["style_label"], baseline["confidence"]
    )
    assert _hash(original_path) != _hash(changed_path)
