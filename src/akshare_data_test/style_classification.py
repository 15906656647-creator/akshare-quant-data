"""Explainable Stage 9 style scoring without deterministic actor claims."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .style_features import Stage9Config


PROFILE_COLUMNS = [
    "symbol", "as_of_date", "primary_window", "style_label", "confidence",
    "secondary_style_label", "secondary_confidence", "evidence_count",
    "conflicting_evidence_count", "data_coverage", "explanation",
    "model_version", "config_version", "publication_status",
]


def _closeness(value: float, target: float, scale: float, epsilon: float) -> float:
    return max(0.0, 1.0 - abs(value - target) / max(scale, epsilon))


def _number(value: object, default: float = 0.0) -> float:
    return default if value is None or pd.isna(value) else float(value)


def classify_style(row: pd.Series, config: Stage9Config) -> dict[str, Any]:
    c = config.raw["classification"]
    confidence_config = c["confidence"]
    coverage = min(1.0, float(row.get("observation_count", 0)) / max(float(row.get("window_size", 1)), 1.0))
    if row.get("data_quality_status") != "pass":
        return {
            "style_label": "数据不足",
            "confidence": round(
                float(confidence_config["insufficient_history_multiplier"]) * coverage,
                6,
            ),
            "secondary_style_label": "未分类或混合型", "secondary_confidence": 0.0,
            "evidence_count": 0, "conflicting_evidence_count": 0,
            "data_coverage": coverage,
            "explanation": "有效交易历史不足，无法形成可靠的横盘震荡风格判断；该结论仅描述量价行为特征，不构成投资建议。",
        }
    t = config.raw["trend"]
    v = config.raw["volatility"]
    scales = c["scales"]
    weights = c["weights"]
    epsilon = float(c["numeric_epsilon"])
    slope = abs(float(row["normalized_slope"]))
    r2 = float(row["regression_r_squared"])
    box = float(row["box_width"])
    atr = float(row["atr_ratio"])
    volume_spike = float(row["volume_spike_frequency"])
    false_breakout = _number(row["failed_breakout_frequency"])
    contraction = _number(row["volume_contraction_ratio"], 1.0)
    turnover = float(row["average_turnover"])
    touches = int(row["upper_touch_count"]) + int(row["lower_touch_count"])
    shadow = float(row["long_upper_shadow_frequency"]) + float(row["long_lower_shadow_frequency"])
    flat = _closeness(slope, 0.0, float(t["trend_slope_abs"]), epsilon)
    gentle = weights["gentle_box"]
    high_volatility = weights["high_volatility"]
    volume_shock = weights["volume_shock"]
    low_activity = weights["low_activity"]
    trend = weights["trend"]
    scores = {
        "温和箱体型": (
            gentle["flat"] * flat
            + gentle["inverse_r_squared"] * (1 - r2)
            + gentle["box"] * _closeness(
                box,
                v["narrow_box_threshold"] * scales["gentle_box_target_fraction"],
                v["narrow_box_threshold"],
                epsilon,
            )
            + gentle["low_atr"] * _closeness(atr, 0, v["high_atr_ratio"], epsilon)
            + gentle["touches"] * min(1.0, touches / scales["touch_count"])
        ),
        "高波动震荡型": (
            high_volatility["flat"] * flat
            + high_volatility["box"] * min(1.0, box / v["wide_box_threshold"])
            + high_volatility["atr"] * min(1.0, atr / v["high_atr_ratio"])
            + high_volatility["shadows"] * min(1.0, shadow / scales["shadow_frequency"])
            + high_volatility["large_moves"] * float(row["large_move_frequency"])
        ),
        "放量冲击型": (
            volume_shock["volume_spike"] * min(1.0, volume_spike / c["volume_spike_frequency"])
            + volume_shock["false_breakout"] * min(1.0, false_breakout / c["false_breakout_frequency"])
            + volume_shock["breakout_count"] * min(
                1.0,
                (row["breakout_up_count"] + row["breakout_down_count"])
                / scales["breakout_count"],
            )
            + volume_shock["flat"] * flat
        ),
        "低活跃盘整型": (
            low_activity["flat"] * flat
            + low_activity["low_atr"] * _closeness(atr, 0, v["low_atr_ratio"], epsilon)
            + low_activity["narrow_box"] * _closeness(box, 0, v["narrow_box_threshold"], epsilon)
            + low_activity["low_turnover"] * _closeness(turnover, 0, c["low_activity_turnover"], epsilon)
            + low_activity["contraction"] * min(
                1.0,
                max(
                    0.0,
                    (1 - contraction)
                    / max(
                        1 - config.raw["volume"]["contraction_ratio_threshold"],
                        epsilon,
                    ),
                ),
            )
        ),
        "趋势型": (
            trend["slope"] * min(1.0, slope / t["trend_slope_abs"])
            + trend["r_squared"] * min(1.0, r2 / t["trend_r_squared"])
            + trend["box_position"] * max(
                float(row["close_position_in_box"]),
                1 - float(row["close_position_in_box"]),
            )
        ),
    }
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    primary, top = ordered[0]
    secondary, second = ordered[1]
    margin = top - second
    conflict_count = sum(score >= top - c["mixed_score_margin"] for _, score in ordered[1:])
    if top < c["minimum_score"] or margin < c["mixed_score_margin"]:
        primary = "未分类或混合型"
    strength = math.tanh(max(0.0, top))
    confidence = min(
        c["maximum_confidence"],
        (
            confidence_config["strength_base"]
            + confidence_config["strength_weight"] * strength
        )
        * coverage
        * (
            confidence_config["margin_base"]
            + confidence_config["margin_weight"]
            * min(1.0, margin / max(c["mixed_score_margin"], epsilon))
        ),
    )
    evidence = sum(score >= c["minimum_score"] for score in scores.values())
    explanation = (
        f"近 {int(row['window_size'])} 个有效交易日的箱体宽度为 {box:.2%}，"
        f"log 收盘价归一化日斜率为 {float(row['normalized_slope']):.4%}，R² 为 {r2:.3f}，"
        f"ATR/收盘价为 {atr:.2%}，放量频率为 {volume_spike:.2%}，"
        f"已确认假突破频率为 {false_breakout:.2%}。当前量价行为特征更接近{primary}；"
        "这属于横盘震荡风格与疑似主力行为特征的统计描述，不代表确定的主力行为，也不构成投资建议。"
    )
    return {
        "style_label": primary, "confidence": round(float(confidence), 6),
        "secondary_style_label": secondary,
        "secondary_confidence": round(float(min(c["maximum_confidence"], second * coverage)), 6),
        "evidence_count": int(evidence), "conflicting_evidence_count": int(conflict_count),
        "data_coverage": coverage, "explanation": explanation,
    }


def build_style_profiles(features: pd.DataFrame, config: Stage9Config) -> pd.DataFrame:
    primary = features.loc[features["window_size"].eq(config.primary_window)].copy()
    rows: list[dict[str, Any]] = []
    for _, row in primary.iterrows():
        result = classify_style(row, config)
        rows.append({
            "symbol": row["symbol"], "as_of_date": row["as_of_date"],
            "primary_window": config.primary_window, **result,
            "model_version": config.raw["model_version"],
            "config_version": config.raw["schema_version"],
            "publication_status": "research_only",
        })
    return pd.DataFrame(rows, columns=PROFILE_COLUMNS)
