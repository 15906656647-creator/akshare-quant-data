"""Stage 9 causal, per-security sideways-style feature engineering."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


STYLE_FEATURE_COLUMNS = [
    "symbol", "as_of_date", "window_size", "price_adjust_type",
    "observation_count", "window_start", "window_end", "rolling_high",
    "rolling_low", "box_width", "close_position_in_box",
    "distance_to_upper_bound", "distance_to_lower_bound",
    "upper_touch_count", "lower_touch_count", "middle_zone_ratio",
    "breakout_up_count", "breakout_down_count", "linear_slope",
    "normalized_slope", "regression_r_squared", "trend_direction",
    "slope_stability", "realized_volatility", "annualized_volatility",
    "average_amplitude", "atr", "atr_ratio", "bollinger_band_width",
    "rolling_max_drawdown", "average_recovery_days", "large_move_frequency",
    "average_amount", "average_turnover", "volume_ma", "amount_ma",
    "volume_trend_slope", "amount_trend_slope", "volume_contraction_ratio",
    "volume_spike_frequency", "high_turnover_frequency",
    "price_volume_correlation", "up_day_volume_ratio", "down_day_volume_ratio",
    "long_upper_shadow_frequency", "long_lower_shadow_frequency",
    "large_body_frequency", "small_body_frequency", "high_low_range_frequency",
    "positive_large_move_frequency", "negative_large_move_frequency",
    "alternating_direction_frequency", "confirmed_false_breakout_up_count",
    "confirmed_false_breakout_down_count", "pending_breakout_count",
    "breakout_with_volume_count", "breakout_return_to_box_days",
    "failed_breakout_frequency", "stage8_publication_status",
    "stage8_formal_event_frequency", "stage8_candidate_event_frequency",
    "stage8_proxy_event_frequency", "stage8_gap_proxy_frequency",
    "stage8_unresolved_event_frequency", "data_quality_status",
]


@dataclass(frozen=True)
class Stage9Config:
    raw: dict[str, Any]

    @property
    def windows(self) -> tuple[int, ...]:
        return tuple(int(v) for v in self.raw["windows"])

    @property
    def primary_window(self) -> int:
        return int(self.raw["primary_window"])

    def minimum_history(self, window: int) -> int:
        values = self.raw["minimum_history_by_window"]
        return int(values.get(window, values.get(str(window), window)))


def load_stage9_config(path: Path) -> Stage9Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Stage 9 config root must be a mapping")
    required = {
        "schema_version", "model_version", "price_adjust_type", "windows",
        "primary_window", "annualization_days", "minimum_history_by_window",
        "box", "trend", "volatility", "volume", "candlestick", "breakout",
        "classification", "stage8",
    }
    missing = sorted(required.difference(raw))
    unknown = sorted(set(raw).difference(required))
    if missing or unknown:
        raise ValueError(f"Invalid Stage 9 config fields missing={missing}, unknown={unknown}")
    if raw["price_adjust_type"] != "qfq":
        raise ValueError("Stage 9 price_adjust_type must be qfq")
    windows = raw["windows"]
    if not isinstance(windows, list) or sorted(windows) != [20, 40, 60]:
        raise ValueError("Stage 9 windows must be exactly 20, 40, 60")
    if raw["primary_window"] not in windows:
        raise ValueError("primary_window must be one of windows")
    if type(raw["breakout"]["confirmation_days"]) is not int or not 1 <= raw["breakout"]["confirmation_days"] <= 3:
        raise ValueError("breakout.confirmation_days must be an integer from 1 to 3")
    classification = raw["classification"]
    required_classification = {
        "minimum_score", "mixed_score_margin", "low_activity_amount_quantile",
        "low_activity_turnover", "volume_spike_frequency",
        "false_breakout_frequency", "maximum_confidence", "numeric_epsilon",
        "scales", "confidence", "weights",
    }
    missing_classification = sorted(required_classification.difference(classification))
    if missing_classification:
        raise ValueError(
            "Stage 9 classification config is missing fields: "
            + ",".join(missing_classification)
        )
    required_weights = {
        "gentle_box": {"flat", "inverse_r_squared", "box", "low_atr", "touches"},
        "high_volatility": {"flat", "box", "atr", "shadows", "large_moves"},
        "volume_shock": {"volume_spike", "false_breakout", "breakout_count", "flat"},
        "low_activity": {"flat", "low_atr", "narrow_box", "low_turnover", "contraction"},
        "trend": {"slope", "r_squared", "box_position"},
    }
    weights = classification["weights"]
    for style, fields in required_weights.items():
        if style not in weights or set(weights[style]) != fields:
            raise ValueError(f"Invalid Stage 9 classification weights for {style}")
        values = [float(value) for value in weights[style].values()]
        if any(not np.isfinite(value) or value < 0 for value in values):
            raise ValueError(f"Stage 9 classification weights for {style} must be finite and non-negative")
        if not np.isclose(sum(values), 1.0, atol=1e-12, rtol=0):
            raise ValueError(f"Stage 9 classification weights for {style} must sum to 1")
    scales = classification["scales"]
    if set(scales) != {
        "gentle_box_target_fraction", "touch_count", "shadow_frequency",
        "breakout_count",
    } or any(float(value) <= 0 for value in scales.values()):
        raise ValueError("Stage 9 classification scales must be complete and positive")
    confidence = classification["confidence"]
    if set(confidence) != {
        "insufficient_history_multiplier", "strength_base", "strength_weight",
        "margin_base", "margin_weight",
    }:
        raise ValueError("Stage 9 confidence configuration is incomplete")
    if float(classification["numeric_epsilon"]) <= 0:
        raise ValueError("classification.numeric_epsilon must be positive")
    return Stage9Config(raw)


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _regression(values: pd.Series) -> tuple[float | None, float | None, float | None]:
    y = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if len(y) < 2 or not np.isfinite(y).all() or (y <= 0).any():
        return None, None, None
    log_y = np.log(y)
    x = np.arange(len(log_y), dtype=float)
    slope, intercept = np.polyfit(x, log_y, 1)
    fitted = slope * x + intercept
    total = float(np.sum((log_y - log_y.mean()) ** 2))
    residual = float(np.sum((log_y - fitted) ** 2))
    r_squared = 1.0 if total == 0 else max(0.0, min(1.0, 1.0 - residual / total))
    return float(slope), float(np.expm1(slope)), r_squared


def _slope_stability(close: pd.Series) -> float | None:
    if len(close) < 4:
        return None
    midpoint = len(close) // 2
    left = _regression(close.iloc[:midpoint])[1]
    right = _regression(close.iloc[midpoint:])[1]
    if left is None or right is None:
        return None
    denominator = abs(left) + abs(right) + 1e-12
    return float(max(0.0, 1.0 - min(1.0, abs(left - right) / denominator)))


def _average_recovery_days(close: pd.Series) -> float | None:
    values = close.to_numpy(dtype=float)
    peak = values[0]
    start: int | None = None
    durations: list[int] = []
    for index, value in enumerate(values):
        if value >= peak:
            if start is not None:
                durations.append(index - start)
                start = None
            peak = value
        elif start is None:
            start = index
    return float(np.mean(durations)) if durations else None


def _normalized_trend(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce")
    if len(clean) < 2 or clean.isna().any() or clean.mean() == 0:
        return None
    return float(np.polyfit(np.arange(len(clean)), clean, 1)[0] / clean.mean())


def _safe_correlation(left: pd.Series, right: pd.Series) -> float | None:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 2 or aligned.iloc[:, 0].nunique() < 2 or aligned.iloc[:, 1].nunique() < 2:
        return None
    return _finite(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def _false_breakouts(
    history: pd.DataFrame, positions: list[int], config: Stage9Config
) -> dict[str, object]:
    lookback = int(config.raw["box"]["breakout_lookback"])
    confirmation = int(config.raw["breakout"]["confirmation_days"])
    spike = float(config.raw["volume"]["spike_ratio_threshold"])
    up = down = pending = with_volume = 0
    return_days: list[int] = []
    breakout_up = breakout_down = 0
    for position in positions:
        if position < lookback:
            continue
        prior = history.iloc[position - lookback:position]
        upper, lower = prior["high"].max(), prior["low"].min()
        close = history.iloc[position]["close"]
        direction = 1 if close > upper else (-1 if close < lower else 0)
        if not direction:
            continue
        breakout_up += int(direction == 1)
        breakout_down += int(direction == -1)
        ratio = history.iloc[position].get("volume_ratio_20")
        if pd.notna(ratio) and float(ratio) >= spike:
            with_volume += 1
        future = history.iloc[position + 1:position + 1 + confirmation]
        if len(future) < confirmation:
            pending += 1
            continue
        returned = None
        for offset, value in enumerate(future["close"], start=1):
            if lower <= value <= upper:
                returned = offset
                break
        if returned is not None:
            up += int(direction == 1)
            down += int(direction == -1)
            return_days.append(returned)
    confirmed = up + down
    attempted = breakout_up + breakout_down
    return {
        "breakout_up_count": breakout_up,
        "breakout_down_count": breakout_down,
        "confirmed_false_breakout_up_count": up,
        "confirmed_false_breakout_down_count": down,
        "pending_breakout_count": pending,
        "breakout_with_volume_count": with_volume,
        "breakout_return_to_box_days": float(np.mean(return_days)) if return_days else None,
        "failed_breakout_frequency": confirmed / attempted if attempted else None,
    }


def _stage8_values(auxiliary: dict[str, object] | None) -> dict[str, object]:
    if not auxiliary:
        return {
            "stage8_publication_status": "not_available",
            "stage8_formal_event_frequency": None,
            "stage8_candidate_event_frequency": None,
            "stage8_proxy_event_frequency": None,
            "stage8_gap_proxy_frequency": None,
            "stage8_unresolved_event_frequency": None,
        }
    status = str(auxiliary.get("publication_status", "not_available"))
    return {
        "stage8_publication_status": status,
        "stage8_formal_event_frequency": (
            auxiliary.get("formal_event_frequency") if status == "formal" else None
        ),
        "stage8_candidate_event_frequency": auxiliary.get("candidate_event_frequency"),
        "stage8_proxy_event_frequency": auxiliary.get("proxy_event_frequency"),
        "stage8_gap_proxy_frequency": auxiliary.get("gap_proxy_frequency"),
        "stage8_unresolved_event_frequency": auxiliary.get("unresolved_event_frequency"),
    }


def compute_style_features(
    daily: pd.DataFrame,
    config: Stage9Config,
    *,
    as_of_date: pd.Timestamp,
    symbols: list[str] | None = None,
    windows: list[int] | None = None,
    stage8_auxiliary: dict[str, dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Compute one causal snapshot per symbol/window using valid qfq trading rows."""
    required = {
        "symbol", "trade_date", "adjust_type", "open", "high", "low", "close",
        "volume_share", "amount_cny", "turnover_rate",
    }
    missing = sorted(required.difference(daily.columns))
    if missing:
        raise ValueError(f"Stage 9 input is missing columns: {missing}")
    frame = daily.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    if frame["trade_date"].isna().any():
        raise ValueError("Stage 9 trade_date contains invalid values")
    if set(frame["adjust_type"].dropna().astype(str).str.lower()) != {"qfq"}:
        raise ValueError("Stage 9 input requires adjust_type='qfq'")
    if frame.duplicated(["symbol", "trade_date", "adjust_type"]).any():
        raise ValueError("Stage 9 input primary key is not unique")
    frame = frame.loc[frame["trade_date"] <= pd.Timestamp(as_of_date).normalize()].copy()
    numeric = ["open", "high", "low", "close", "volume_share", "amount_cny", "turnover_rate"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    valid = (
        frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & frame["volume_share"].gt(0)
        & frame["amount_cny"].ge(0)
        & frame["turnover_rate"].ge(0)
        & frame["high"].ge(frame[["open", "close", "low"]].max(axis=1))
        & frame["low"].le(frame[["open", "close", "high"]].min(axis=1))
    )
    if "is_suspended" in frame:
        suspended = pd.to_numeric(frame["is_suspended"], errors="coerce").fillna(0).ne(0)
        valid &= ~suspended
    frame = frame.loc[valid].sort_values(["symbol", "trade_date"], kind="mergesort")
    selected_symbols = sorted(set(symbols or frame["symbol"].unique()))
    selected_windows = list(windows or config.windows)
    if not set(selected_windows).issubset(config.windows):
        raise ValueError("Requested windows are not enabled by Stage 9 config")
    rows: list[dict[str, object]] = []
    for symbol in selected_symbols:
        history = frame.loc[frame["symbol"].eq(symbol)].reset_index(drop=True)
        history["return_1d"] = history["close"].pct_change()
        if "volume_ratio_20" not in history or history["volume_ratio_20"].isna().all():
            ma_window = int(config.raw["volume"]["moving_average_window"])
            history["volume_ratio_20"] = history["volume_share"] / history["volume_share"].rolling(ma_window, min_periods=ma_window).mean()
        for window in selected_windows:
            sample = history.tail(window).copy()
            base: dict[str, object] = {
                "symbol": symbol, "as_of_date": pd.Timestamp(as_of_date).normalize(),
                "window_size": window, "price_adjust_type": "qfq",
                "observation_count": len(sample),
                "window_start": sample["trade_date"].min() if not sample.empty else None,
                "window_end": sample["trade_date"].max() if not sample.empty else None,
                **_stage8_values((stage8_auxiliary or {}).get(symbol)),
            }
            if len(sample) < config.minimum_history(window):
                rows.append({**{name: None for name in STYLE_FEATURE_COLUMNS}, **base, "data_quality_status": "insufficient_history"})
                continue
            close = sample["close"]
            high, low = float(sample["high"].max()), float(sample["low"].min())
            if low <= 0 or high < low:
                rows.append({**{name: None for name in STYLE_FEATURE_COLUMNS}, **base, "data_quality_status": "invalid_price_range"})
                continue
            box_width = high / low - 1.0
            position = (float(close.iloc[-1]) - low) / (high - low) if high > low else 0.5
            previous_close = close.shift(1)
            true_range = pd.concat([
                sample["high"] - sample["low"],
                (sample["high"] - previous_close).abs(),
                (sample["low"] - previous_close).abs(),
            ], axis=1).max(axis=1)
            atr = float(true_range.mean())
            atr_ratio = atr / float(close.iloc[-1])
            tolerance = max(
                float(config.raw["box"]["minimum_relative_distance"]),
                box_width * float(config.raw["box"]["touch_box_fraction"]),
                atr_ratio * float(config.raw["box"]["touch_atr_fraction"]),
            )
            positions = ((close - low) / (high - low)).fillna(0.5) if high > low else pd.Series(0.5, index=sample.index)
            slope, normalized_slope, r_squared = _regression(close)
            returns = close.pct_change()
            realized = float(returns.std(ddof=1)) if returns.notna().sum() > 1 else 0.0
            direction = "flat"
            flat = float(config.raw["trend"]["flat_slope_abs"])
            if normalized_slope is not None and normalized_slope > flat:
                direction = "up"
            elif normalized_slope is not None and normalized_slope < -flat:
                direction = "down"
            body = (sample["close"] - sample["open"]).abs()
            candle_range = sample["high"] - sample["low"]
            safe_range = candle_range.replace(0, np.nan)
            upper_shadow = sample["high"] - sample[["open", "close"]].max(axis=1)
            lower_shadow = sample[["open", "close"]].min(axis=1) - sample["low"]
            large_move = float(config.raw["volatility"]["large_move_threshold"])
            shadow_threshold = float(config.raw["candlestick"]["long_shadow_ratio"])
            signs = np.sign(returns.dropna())
            amount = sample["amount_cny"]
            volume = sample["volume_share"]
            half = max(1, len(sample) // 2)
            first_volume, second_volume = volume.iloc[:half].mean(), volume.iloc[half:].mean()
            volume_contraction = second_volume / first_volume if first_volume > 0 else None
            absolute_positions = list(range(len(history) - len(sample), len(history)))
            breakout = _false_breakouts(history, absolute_positions, config)
            row = {
                **base,
                "rolling_high": high, "rolling_low": low, "box_width": box_width,
                "close_position_in_box": position,
                "distance_to_upper_bound": (high - float(close.iloc[-1])) / high,
                "distance_to_lower_bound": (float(close.iloc[-1]) - low) / low,
                "upper_touch_count": int(((high - sample["high"]) / high <= tolerance).sum()),
                "lower_touch_count": int(((sample["low"] - low) / low <= tolerance).sum()),
                "middle_zone_ratio": float(positions.between(config.raw["box"]["middle_zone_lower"], config.raw["box"]["middle_zone_upper"]).mean()),
                **breakout,
                "linear_slope": slope, "normalized_slope": normalized_slope,
                "regression_r_squared": r_squared, "trend_direction": direction,
                "slope_stability": _slope_stability(close),
                "realized_volatility": realized,
                "annualized_volatility": realized * np.sqrt(float(config.raw["annualization_days"])),
                "average_amplitude": float(((sample["high"] - sample["low"]) / previous_close).dropna().mean()),
                "atr": atr, "atr_ratio": atr_ratio,
                "bollinger_band_width": float(2 * config.raw["volatility"]["bollinger_std_multiplier"] * close.std(ddof=0) / close.mean()),
                "rolling_max_drawdown": float((close / close.cummax() - 1).min()),
                "average_recovery_days": _average_recovery_days(close),
                "large_move_frequency": float(returns.abs().ge(large_move).mean()),
                "average_amount": float(amount.mean()), "average_turnover": float(sample["turnover_rate"].mean()),
                "volume_ma": float(volume.mean()), "amount_ma": float(amount.mean()),
                "volume_trend_slope": _normalized_trend(volume),
                "amount_trend_slope": _normalized_trend(amount),
                "volume_contraction_ratio": _finite(volume_contraction),
                "volume_spike_frequency": float(history.loc[sample.index, "volume_ratio_20"].ge(config.raw["volume"]["spike_ratio_threshold"]).mean()),
                "high_turnover_frequency": float(sample["turnover_rate"].ge(config.raw["volume"]["high_turnover_threshold"]).mean()),
                "price_volume_correlation": _safe_correlation(returns, volume.pct_change()),
                "up_day_volume_ratio": float(volume[returns.gt(0)].sum() / volume.sum()),
                "down_day_volume_ratio": float(volume[returns.lt(0)].sum() / volume.sum()),
                "long_upper_shadow_frequency": float((upper_shadow / safe_range).ge(shadow_threshold).mean()),
                "long_lower_shadow_frequency": float((lower_shadow / safe_range).ge(shadow_threshold).mean()),
                "large_body_frequency": float((body / safe_range).ge(config.raw["candlestick"]["large_body_ratio"]).mean()),
                "small_body_frequency": float((body / safe_range).le(config.raw["candlestick"]["small_body_ratio"]).fillna(False).mean()),
                "high_low_range_frequency": float((candle_range / previous_close).ge(config.raw["candlestick"]["high_low_range_threshold"]).mean()),
                "positive_large_move_frequency": float(returns.ge(large_move).mean()),
                "negative_large_move_frequency": float(returns.le(-large_move).mean()),
                "alternating_direction_frequency": float((signs * signs.shift(1) < 0).mean()) if len(signs) else 0.0,
                "data_quality_status": "pass",
            }
            rows.append(row)
    return pd.DataFrame(rows).reindex(columns=STYLE_FEATURE_COLUMNS)
