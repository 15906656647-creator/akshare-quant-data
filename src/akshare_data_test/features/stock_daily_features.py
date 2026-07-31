"""Stage 7 daily technical and volume-price features."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_INPUT_COLUMNS = {
    "symbol",
    "exchange",
    "trade_date",
    "adjust_type",
    "open",
    "high",
    "low",
    "close",
    "volume_share",
}


@dataclass(frozen=True)
class Stage7Parameters:
    """Calculation parameters resolved from the frozen and Stage 7 configs."""

    ma_windows: tuple[int, ...]
    volume_ma_windows: tuple[int, ...]
    volatility_window: int
    annualization_days: int
    activity_lookback_days: int
    volume_spike_ratio: float
    large_move_abs_return: float
    gap_abs_threshold: float
    minimum_scoring_observations: int
    activity_weights: dict[str, float]
    score_version: str
    event_component_source: str

    @classmethod
    def from_config(
        cls, metric_config: dict[str, Any], stage7_config: dict[str, Any]
    ) -> "Stage7Parameters":
        """Build and validate parameters without silently inventing thresholds."""
        expected_weight_keys = {
            "turnover_amount_quantile",
            "turnover_rate_quantile",
            "volatility_quantile",
            "volume_spike_frequency_quantile",
            "large_move_frequency_quantile",
            "limit_and_gap_event_frequency_quantile",
        }
        raw_weights = dict(metric_config["activity_scoring"]["weights"])
        if set(raw_weights) != expected_weight_keys:
            raise ValueError("Stage 7 activity weight keys do not match the contract")
        weights = {key: float(value) for key, value in raw_weights.items()}
        if (
            not all(np.isfinite(value) and value >= 0 for value in weights.values())
            or not np.isclose(sum(weights.values()), 1.0)
        ):
            raise ValueError("Stage 7 activity weights must sum to 1")
        ma_windows = tuple(int(v) for v in metric_config["ma_windows"]["price"])
        if ma_windows != (3, 5, 7, 10, 13, 20, 21):
            raise ValueError("Stage 7 requires MA windows 3,5,7,10,13,20,21")
        volume_windows = tuple(
            int(v) for v in metric_config["ma_windows"]["volume"]
        )
        if volume_windows != (5, 20):
            raise ValueError("Stage 7 requires unique volume MA windows 5,20")
        volatility_window = int(
            metric_config["volume_price_metrics"]["volatility_window"]
        )
        annualization_days = int(
            metric_config["volume_price_metrics"]["annual_trading_days"]
        )
        activity_lookback_days = int(
            metric_config["activity_scoring"]["lookback_window"]
        )
        minimum_observations = int(
            stage7_config["minimum_scoring_observations"]
        )
        positive_values = {
            "volatility_window": volatility_window,
            "annual_trading_days": annualization_days,
            "activity_lookback_window": activity_lookback_days,
            "minimum_scoring_observations": minimum_observations,
        }
        invalid_positive = [
            name for name, value in positive_values.items() if value <= 0
        ]
        if invalid_positive:
            raise ValueError(
                "Stage 7 positive configuration required for: "
                + ", ".join(invalid_positive)
            )
        if minimum_observations > activity_lookback_days:
            raise ValueError(
                "minimum_scoring_observations cannot exceed activity lookback"
            )
        thresholds = {
            "volume_spike_ratio": float(
                metric_config["volume_price_metrics"]["volume_spike_threshold"][
                    "value"
                ]
            ),
            "large_move_abs_return": float(
                metric_config["volume_price_metrics"]["large_move_threshold"][
                    "value"
                ]
            ),
            "gap_abs_threshold": float(stage7_config["gap_abs_threshold"]),
        }
        if not all(
            np.isfinite(value) and value >= 0 for value in thresholds.values()
        ):
            raise ValueError("Stage 7 thresholds must be finite and non-negative")
        score_version = str(stage7_config["score_version"]).strip()
        event_source = str(stage7_config["event_component_source"]).strip()
        if not score_version or not event_source:
            raise ValueError("Stage 7 score metadata cannot be empty")
        return cls(
            ma_windows=ma_windows,
            volume_ma_windows=volume_windows,
            volatility_window=volatility_window,
            annualization_days=annualization_days,
            activity_lookback_days=activity_lookback_days,
            volume_spike_ratio=thresholds["volume_spike_ratio"],
            large_move_abs_return=thresholds["large_move_abs_return"],
            gap_abs_threshold=thresholds["gap_abs_threshold"],
            minimum_scoring_observations=minimum_observations,
            activity_weights=weights,
            score_version=score_version,
            event_component_source=event_source,
        )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    valid_denominator = denominator.notna() & np.isfinite(denominator) & denominator.ne(0)
    result = numerator.astype(float).div(denominator.astype(float))
    result = result.where(valid_denominator)
    return result.replace([np.inf, -np.inf], np.nan)


def compute_stock_daily_features(
    daily: pd.DataFrame,
    parameters: Stage7Parameters,
    *,
    adjust_type: str = "qfq",
) -> pd.DataFrame:
    """Calculate Stage 7 daily features independently within each stock.

    Input rows are filtered to ``adjust_type='qfq'`` and sorted by symbol/date.
    Moving averages require full windows. Returns, gap and intraday range use
    the same stock's prior close. Rolling volatility uses sample standard
    deviation (``ddof=1``) and 252-day annualisation from configuration.
    """
    missing = sorted(REQUIRED_INPUT_COLUMNS.difference(daily.columns))
    if missing:
        raise ValueError(f"Missing core daily columns: {missing}")
    if adjust_type != "qfq":
        raise ValueError("Stage 7 daily features require adjust_type='qfq'")

    frame = daily.loc[daily["adjust_type"].eq(adjust_type)].copy()
    frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    invalid_symbols = ~frame["symbol"].str.fullmatch(r"\d{6}", na=False)
    if invalid_symbols.any():
        raise ValueError("Invalid six-digit symbol in Stage 7 input")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    if frame["trade_date"].isna().any():
        raise ValueError("Invalid trade_date in Stage 7 input")
    key = ["symbol", "trade_date", "adjust_type"]
    duplicates = frame.duplicated(key, keep=False)
    if duplicates.any():
        sample = frame.loc[duplicates, key].head(5).to_dict("records")
        raise ValueError(f"Duplicate Stage 7 input business keys: {sample}")
    frame = frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume_share",
        "amount_cny",
        "amplitude",
        "turnover_rate",
    ]
    for column in numeric_columns:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    input_infinite_count = int(
        np.isinf(frame[numeric_columns].to_numpy(dtype=float)).sum()
    )
    required_numeric = ["close", "high", "low", "volume_share"]
    invalid_core = frame[required_numeric].isna() | ~np.isfinite(
        frame[required_numeric]
    )
    if invalid_core.any().any():
        columns = invalid_core.any().loc[lambda values: values].index.tolist()
        raise ValueError(f"Missing or invalid core numeric values: {columns}")

    grouped = frame.groupby("symbol", sort=False, group_keys=False)
    frame["prev_close"] = grouped["close"].shift(1)
    frame["return_1d"] = _safe_ratio(frame["close"], frame["prev_close"]) - 1.0
    frame["intraday_range"] = _safe_ratio(
        frame["high"] - frame["low"], frame["prev_close"]
    )
    frame["gap_return"] = _safe_ratio(frame["open"], frame["prev_close"]) - 1.0

    for window in parameters.ma_windows:
        frame[f"ma_{window}"] = grouped["close"].transform(
            lambda values, n=window: values.rolling(n, min_periods=n).mean()
        )
    for window in parameters.volume_ma_windows:
        frame[f"volume_ma_{window}"] = grouped["volume_share"].transform(
            lambda values, n=window: values.rolling(n, min_periods=n).mean()
        )

    frame["volume_ratio_20"] = _safe_ratio(
        frame["volume_share"], frame["volume_ma_20"]
    )
    frame["volatility_20"] = grouped["return_1d"].transform(
        lambda values: values.rolling(
            parameters.volatility_window,
            min_periods=parameters.volatility_window,
        ).std(ddof=1)
    ) * np.sqrt(parameters.annualization_days)

    frame["is_volume_spike"] = (
        frame["volume_ratio_20"].ge(parameters.volume_spike_ratio).astype("boolean")
    ).where(frame["volume_ratio_20"].notna())
    frame["is_large_move"] = (
        frame["return_1d"].abs().ge(parameters.large_move_abs_return).astype("boolean")
    ).where(frame["return_1d"].notna())

    feature_columns = [
        "symbol",
        "exchange",
        "trade_date",
        "adjust_type",
        "close",
        "prev_close",
        "return_1d",
        *[f"ma_{window}" for window in parameters.ma_windows],
        "volume_ma_5",
        "volume_ma_20",
        "volume_ratio_20",
        "intraday_range",
        "gap_return",
        "volatility_20",
        "is_volume_spike",
        "is_large_move",
        "amount_cny",
        "turnover_rate",
        "amplitude",
        "source_fetched_at",
    ]
    if "source_fetched_at" not in frame:
        frame["source_fetched_at"] = pd.NaT
    result = frame[feature_columns].copy()
    numeric_result = result.select_dtypes(include=[np.number])
    infinite_count = input_infinite_count + int(
        np.isinf(numeric_result.to_numpy()).sum()
    )
    result.replace([np.inf, -np.inf], np.nan, inplace=True)
    result.attrs["infinite_values_cleaned"] = infinite_count
    return result.reset_index(drop=True)
