# -*- coding: utf-8 -*-
"""Pure, offline Stage 6 feature calculations.

Every function accepts already-cleaned frames.  This module deliberately has
no adapter, collector, AKShare, HTTP, or clock dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd


REQUIRED_MA_WINDOWS = [3, 5, 7, 10, 13, 20, 21]
FUNDAMENTAL_FEATURES = [
    "revenue",
    "net_profit",
    "net_profit_parent",
    "revenue_yoy",
    "net_profit_yoy",
    "revenue_ttm",
    "net_profit_ttm",
    "gross_margin",
    "net_margin",
    "operating_cf_over_net_profit",
    "roe",
    "debt_to_asset_ratio",
]


@dataclass(frozen=True)
class Stage6Parameters:
    ma_windows: list[int]
    volume_ma_windows: list[int]
    volatility_window: int
    annual_trading_days: int
    activity_window: int
    volume_spike_threshold: float
    large_move_threshold: float
    activity_weights: dict[str, float]
    consolidation_windows: list[int]
    consolidation_primary_window: int
    limit_lookback_natural_days: int
    financial_annual_reports_years: int
    financial_quarterly_reports_count: int

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Stage6Parameters":
        params = cls(
            ma_windows=[int(x) for x in config["ma_windows"]["price"]],
            volume_ma_windows=[int(x) for x in config["ma_windows"]["volume"]],
            volatility_window=int(
                config["volume_price_metrics"]["volatility_window"]
            ),
            annual_trading_days=int(
                config["volume_price_metrics"]["annual_trading_days"]
            ),
            activity_window=int(config["activity_scoring"]["lookback_window"]),
            volume_spike_threshold=float(
                config["volume_price_metrics"]["volume_spike_threshold"]["value"]
            ),
            large_move_threshold=float(
                config["volume_price_metrics"]["large_move_threshold"]["value"]
            ),
            activity_weights={
                str(k): float(v)
                for k, v in config["activity_scoring"]["weights"].items()
            },
            consolidation_windows=[
                int(x) for x in config["consolidation_analysis"]["windows"]
            ],
            consolidation_primary_window=int(
                config["consolidation_analysis"]["primary_window"]
            ),
            limit_lookback_natural_days=int(
                config["data_ranges"]["limit_event"]["lookback_natural_days"]
            ),
            financial_annual_reports_years=int(
                config["data_ranges"]["financial"]["annual_reports_years"]
            ),
            financial_quarterly_reports_count=int(
                config["data_ranges"]["financial"]["quarterly_reports_count"]
            ),
        )
        if params.ma_windows != REQUIRED_MA_WINDOWS:
            raise ValueError(
                "stage6_ma_windows_must_equal_[3,5,7,10,13,20,21]"
            )
        if not np.isclose(sum(params.activity_weights.values()), 1.0):
            raise ValueError("stage6_activity_weights_must_sum_to_one")
        return params


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide without turning missing or zero denominators into zero/inf."""
    den = pd.to_numeric(denominator, errors="coerce")
    num = pd.to_numeric(numerator, errors="coerce")
    result = num / den.where(den.ne(0))
    return result.replace([np.inf, -np.inf], np.nan)


def _base_daily(daily: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.DataFrame:
    frame = daily.copy()
    frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.loc[frame["trade_date"].le(as_of_date)].copy()
    return frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def build_price_and_trend(
    qfq_daily: pd.DataFrame,
    as_of_date: pd.Timestamp,
    params: Stage6Parameters,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build qfq price/return/volume and strict moving-average features."""
    frame = _base_daily(qfq_daily, as_of_date)
    if not frame["adjust_type"].eq("qfq").all():
        raise ValueError("price_and_trend_features_require_qfq")

    grouped = frame.groupby("symbol", sort=False, group_keys=False)
    previous_close = grouped["close"].shift(1)
    frame["return_1d"] = safe_divide(frame["close"], previous_close) - 1.0

    for window in params.volume_ma_windows:
        frame[f"volume_ma_{window}"] = grouped["volume_share"].transform(
            lambda values, w=window: values.rolling(
                window=w, min_periods=w
            ).mean()
        )
    frame["volume_ratio_20"] = safe_divide(
        frame["volume_share"], frame["volume_ma_20"]
    )
    frame["rolling_volatility_20"] = grouped["return_1d"].transform(
        lambda values: values.rolling(
            window=params.volatility_window,
            min_periods=params.volatility_window,
        ).std(ddof=1)
        * sqrt(params.annual_trading_days)
    )

    price_columns = [
        "transform_run_id",
        "source_run_id",
        "symbol",
        "exchange",
        "trade_date",
        "close",
        "volume_lot",
        "volume_share",
        "amount_cny",
        "turnover_rate",
        "amplitude",
        "source_file",
        "return_1d",
        "volume_ma_5",
        "volume_ma_20",
        "volume_ratio_20",
        "rolling_volatility_20",
    ]
    price = frame[price_columns].rename(columns={"close": "close_qfq"})

    trend = frame[
        [
            "transform_run_id",
            "source_run_id",
            "symbol",
            "exchange",
            "trade_date",
            "source_file",
            "close",
        ]
    ].rename(columns={"close": "close_qfq"})
    for window in params.ma_windows:
        trend[f"ma_{window}"] = grouped["close"].transform(
            lambda values, w=window: values.rolling(
                window=w, min_periods=w
            ).mean()
        )
    return price, trend


def build_limit_features(
    raw_daily: pd.DataFrame,
    as_of_date: pd.Timestamp,
    matching_tolerance: float,
    lookback_natural_days: int = 365,
) -> pd.DataFrame:
    """Build conservative raw-price limit evidence.

    The Stage 5 database has no complete historical ST/board/listing-rule
    dimension.  The frozen policy forbids guessing, so calculable raw returns
    are retained while the actual limit classification is ``uncertain``.
    """
    frame = _base_daily(raw_daily, as_of_date)
    if not frame["adjust_type"].eq("raw").all():
        raise ValueError("limit_features_require_raw_prices")
    grouped = frame.groupby("symbol", sort=False, group_keys=False)
    frame["previous_raw_close"] = grouped["close"].shift(1)
    frame["daily_return_raw"] = (
        safe_divide(frame["close"], frame["previous_raw_close"]) - 1.0
    )
    first = frame["previous_raw_close"].isna()
    frame["limit_direction"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["limit_status"] = np.where(first, "warmup", "uncertain")
    frame["limit_threshold"] = np.nan
    frame["threshold_source"] = np.where(
        first, "previous_trading_close_unavailable", "security_rule_history_unavailable"
    )
    frame["detection_confidence"] = np.nan
    frame["uncertainty_reason"] = np.where(
        first,
        "first available trading row",
        "ST/board/listing status history is unavailable; frozen rules forbid guessing",
    )
    frame["matching_tolerance_tick_fraction"] = float(matching_tolerance)
    lower_bound = as_of_date - pd.Timedelta(days=lookback_natural_days)
    frame = frame.loc[frame["trade_date"].ge(lower_bound)].copy()
    return frame[
        [
            "transform_run_id",
            "source_run_id",
            "symbol",
            "exchange",
            "trade_date",
            "source_file",
            "close",
            "previous_raw_close",
            "daily_return_raw",
            "limit_direction",
            "limit_status",
            "limit_threshold",
            "threshold_source",
            "detection_confidence",
            "uncertainty_reason",
            "matching_tolerance_tick_fraction",
        ]
    ].rename(columns={"close": "raw_close"})


def _cross_sectional_rank(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.groupby("trade_date", sort=False)[column].rank(
        method="average", pct=True, na_option="keep"
    )


def build_activity_features(
    price: pd.DataFrame,
    raw_daily: pd.DataFrame,
    as_of_date: pd.Timestamp,
    params: Stage6Parameters,
) -> pd.DataFrame:
    """Build trailing activity components and cross-sectional score."""
    frame = price.copy().sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    grouped = frame.groupby("symbol", sort=False, group_keys=False)
    window = params.activity_window
    frame["turnover_amount_120"] = grouped["amount_cny"].transform(
        lambda values: values.rolling(window, min_periods=window).mean()
    )
    frame["turnover_rate_120"] = grouped["turnover_rate"].transform(
        lambda values: values.rolling(window, min_periods=window).mean()
    )
    frame["volatility_120"] = grouped["return_1d"].transform(
        lambda values: values.rolling(window, min_periods=window).std(ddof=1)
        * sqrt(params.annual_trading_days)
    )
    spikes = frame["volume_ratio_20"].ge(params.volume_spike_threshold).where(
        frame["volume_ratio_20"].notna()
    )
    large_moves = frame["return_1d"].abs().ge(params.large_move_threshold).where(
        frame["return_1d"].notna()
    )
    frame["volume_spike_frequency_120"] = spikes.groupby(frame["symbol"]).transform(
        lambda values: values.astype(float).rolling(
            window, min_periods=window
        ).mean()
    )
    frame["large_move_frequency_120"] = large_moves.groupby(
        frame["symbol"]
    ).transform(
        lambda values: values.astype(float).rolling(
            window, min_periods=window
        ).mean()
    )

    raw = _base_daily(raw_daily, as_of_date)
    previous_raw_close = raw.groupby("symbol", sort=False)["close"].shift(1)
    gap_return = safe_divide(raw["open"], previous_raw_close) - 1.0
    raw["gap_event"] = gap_return.abs().ge(params.large_move_threshold).where(
        gap_return.notna()
    )
    raw["limit_and_gap_event_frequency_120"] = raw.groupby(
        "symbol", sort=False
    )["gap_event"].transform(
        lambda values: values.astype(float).rolling(
            window, min_periods=window
        ).mean()
    )
    frame = frame.merge(
        raw[["symbol", "trade_date", "limit_and_gap_event_frequency_120"]],
        on=["symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )

    component_map = {
        "turnover_amount_quantile": "turnover_amount_120",
        "turnover_rate_quantile": "turnover_rate_120",
        "volatility_quantile": "volatility_120",
        "volume_spike_frequency_quantile": "volume_spike_frequency_120",
        "large_move_frequency_quantile": "large_move_frequency_120",
        "limit_and_gap_event_frequency_quantile": (
            "limit_and_gap_event_frequency_120"
        ),
    }
    for score_name, value_name in component_map.items():
        frame[score_name] = _cross_sectional_rank(frame, value_name)

    score = pd.Series(0.0, index=frame.index)
    complete = pd.Series(True, index=frame.index)
    for name, weight in params.activity_weights.items():
        score = score + frame[name] * weight
        complete &= frame[name].notna()
    frame["activity_score"] = score.where(complete)
    return frame[
        [
            "transform_run_id",
            "source_run_id",
            "symbol",
            "exchange",
            "trade_date",
            "turnover_amount_120",
            "turnover_rate_120",
            "volatility_120",
            "volume_spike_frequency_120",
            "large_move_frequency_120",
            "limit_and_gap_event_frequency_120",
            *component_map.keys(),
            "activity_score",
        ]
    ]


def _rolling_ols(values: np.ndarray) -> float:
    if np.isnan(values).any() or np.any(values <= 0):
        return np.nan
    y = np.log(values)
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _rolling_r_squared(values: np.ndarray) -> float:
    if np.isnan(values).any() or np.any(values <= 0):
        return np.nan
    y = np.log(values)
    x = np.arange(len(values), dtype=float)
    fitted = np.polyval(np.polyfit(x, y, 1), x)
    total = np.square(y - y.mean()).sum()
    if total == 0:
        return np.nan
    return float(1.0 - np.square(y - fitted).sum() / total)


def _rolling_linear_slope(values: np.ndarray) -> float:
    if np.isnan(values).any():
        return np.nan
    return float(np.polyfit(np.arange(len(values), dtype=float), values, 1)[0])


def build_style_features(
    qfq_daily: pd.DataFrame,
    fund_flow: pd.DataFrame,
    as_of_date: pd.Timestamp,
    params: Stage6Parameters,
) -> pd.DataFrame:
    """Build the frozen neutral consolidation evidence fields."""
    frame = _base_daily(qfq_daily, as_of_date)
    if not frame["adjust_type"].eq("qfq").all():
        raise ValueError("style_features_require_qfq")
    grouped = frame.groupby("symbol", sort=False, group_keys=False)
    previous_close = grouped["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    body = (frame["close"] - frame["open"]).abs()
    shadows = (frame["high"] - frame[["open", "close"]].max(axis=1)) + (
        frame[["open", "close"]].min(axis=1) - frame["low"]
    )
    long_shadow = shadows.gt(body).where(
        frame[["open", "high", "low", "close"]].notna().all(axis=1)
    )
    returns = safe_divide(frame["close"], previous_close) - 1.0

    fund = fund_flow[["symbol", "trade_date", "main_net_inflow_ratio"]].copy()
    fund["trade_date"] = pd.to_datetime(fund["trade_date"])
    frame = frame.merge(
        fund, on=["symbol", "trade_date"], how="left", validate="one_to_one"
    )
    frame["_return_1d"] = returns
    frame["_true_range"] = true_range
    frame["_long_shadow"] = long_shadow.astype(float)

    result = frame[
        [
            "transform_run_id",
            "source_run_id",
            "symbol",
            "exchange",
            "trade_date",
        ]
    ].copy()
    for window in params.consolidation_windows:
        close_group = frame.groupby("symbol", sort=False)["close"]
        high = close_group.transform(
            lambda values, w=window: values.rolling(w, min_periods=w).max()
        )
        low = close_group.transform(
            lambda values, w=window: values.rolling(w, min_periods=w).min()
        )
        mean = close_group.transform(
            lambda values, w=window: values.rolling(w, min_periods=w).mean()
        )
        std = close_group.transform(
            lambda values, w=window: values.rolling(w, min_periods=w).std(ddof=1)
        )
        result[f"box_width_{window}"] = safe_divide(high, low) - 1.0
        result[f"trend_slope_{window}"] = close_group.transform(
            lambda values, w=window: values.rolling(
                w, min_periods=w
            ).apply(_rolling_ols, raw=True)
        )
        result[f"r_squared_{window}"] = close_group.transform(
            lambda values, w=window: values.rolling(
                w, min_periods=w
            ).apply(_rolling_r_squared, raw=True)
        )
        result[f"bollinger_bandwidth_{window}"] = safe_divide(4.0 * std, mean)
        atr = frame.groupby("symbol", sort=False)["_true_range"].transform(
            lambda values, w=window: values.rolling(w, min_periods=w).mean()
        )
        result[f"atr_over_close_{window}"] = safe_divide(atr, frame["close"])
        result[f"upper_touch_count_{window}"] = (
            frame["close"].eq(high).astype(float).groupby(frame["symbol"]).transform(
                lambda values, w=window: values.rolling(w, min_periods=w).sum()
            )
        )
        result[f"lower_touch_count_{window}"] = (
            frame["close"].eq(low).astype(float).groupby(frame["symbol"]).transform(
                lambda values, w=window: values.rolling(w, min_periods=w).sum()
            )
        )
        result[f"volume_trend_slope_{window}"] = frame.groupby(
            "symbol", sort=False
        )["volume_share"].transform(
            lambda values, w=window: values.rolling(
                w, min_periods=w
            ).apply(_rolling_linear_slope, raw=True)
        )
        # A false breakout is not evaluated with unknown future rows.  The
        # frozen config does not define a backward-looking confirmation rule,
        # therefore it remains NULL instead of introducing lookahead.
        result[f"false_breakout_count_{window}"] = np.nan
        result[f"long_shadow_frequency_{window}"] = frame.groupby(
            "symbol", sort=False
        )["_long_shadow"].transform(
            lambda values, w=window: values.rolling(w, min_periods=w).mean()
        )
        divergence = pd.Series(np.nan, index=frame.index, dtype=float)
        for _, positions in frame.groupby("symbol", sort=False).groups.items():
            local = frame.loc[positions]
            divergence.loc[positions] = (
                local["_return_1d"]
                .rolling(window, min_periods=window)
                .corr(local["main_net_inflow_ratio"])
            )
        result[f"fund_flow_divergence_{window}"] = divergence

    result["style_label"] = "证据不足"
    result["style_confidence"] = np.nan
    result["style_explanation"] = (
        "冻结配置未提供风格分类阈值；仅保留中性横盘特征，不作确定性分类"
    )
    return result


def build_fund_flow_features(
    safe_fund_flow: pd.DataFrame, as_of_date: pd.Timestamp
) -> pd.DataFrame:
    """Retain only configured direct as-of-safe fund-flow measurements."""
    frame = safe_fund_flow.copy()
    frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.loc[frame["trade_date"].le(as_of_date)].copy()
    return frame.sort_values(["symbol", "trade_date"])[
        [
            "transform_run_id",
            "source_run_id",
            "symbol",
            "exchange",
            "trade_date",
            "main_net_inflow_cny",
            "main_net_inflow_ratio",
            "source_file",
        ]
    ].reset_index(drop=True)


def _single_quarter(series: pd.Series, periods: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=series.index, dtype=float)
    by_period = dict(zip(pd.to_datetime(periods), series, strict=False))
    for idx, period in zip(series.index, pd.to_datetime(periods), strict=False):
        value = series.loc[idx]
        if pd.isna(value):
            continue
        quarter = period.quarter
        if quarter == 1:
            result.loc[idx] = value
            continue
        previous = pd.Timestamp(period.year, (quarter - 1) * 3, 1) + pd.offsets.MonthEnd(0)
        previous_value = by_period.get(previous)
        if previous_value is not None and pd.notna(previous_value):
            result.loc[idx] = value - previous_value
    return result


def _ttm_if_four_consecutive(values: pd.Series, periods: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    ordered_periods = pd.to_datetime(periods).reset_index(drop=True)
    ordered_values = values.reset_index(drop=True)
    for pos in range(3, len(ordered_values)):
        dates = ordered_periods.iloc[pos - 3 : pos + 1]
        quarter_codes = dates.dt.year * 4 + dates.dt.quarter
        if (
            quarter_codes.diff().dropna().eq(1).all()
            and ordered_values.iloc[pos - 3 : pos + 1].notna().all()
        ):
            result.iloc[pos] = ordered_values.iloc[pos - 3 : pos + 1].sum()
    result.index = values.index
    return result


def build_financial_features(
    safe_statements: pd.DataFrame,
    as_of_date: pd.Timestamp,
    annual_reports_years: int = 5,
    quarterly_reports_count: int = 12,
) -> pd.DataFrame:
    """Build point-in-time financial features from announced statements only."""
    frame = safe_statements.copy()
    frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    frame["report_period"] = pd.to_datetime(frame["report_period"])
    frame["announcement_date"] = pd.to_datetime(frame["announcement_date"])
    frame = frame.loc[
        frame["announcement_date"].notna()
        & frame["announcement_date"].le(as_of_date)
    ].copy()
    wanted = {
        "TOTAL_OPERATE_INCOME": "revenue_cumulative",
        "NETPROFIT": "net_profit_cumulative",
        "PARENT_NETPROFIT": "net_profit_parent_cumulative",
        "TOTAL_OPERATE_COST": "operating_cost_cumulative",
        "NETCASH_OPERATE": "operating_cash_flow_cumulative",
        "TOTAL_ASSETS": "total_assets",
        "TOTAL_LIABILITIES": "total_liabilities",
        "TOTAL_PARENT_EQUITY": "parent_equity",
    }
    frame = frame.loc[frame["item_name"].isin(wanted)].copy()
    frame["canonical_input"] = frame["item_name"].map(wanted)
    frame = frame.sort_values(
        ["symbol", "report_period", "canonical_input", "announcement_date"]
    ).drop_duplicates(
        ["symbol", "report_period", "canonical_input"], keep="last"
    )
    wide = frame.pivot(
        index=["symbol", "report_period"],
        columns="canonical_input",
        values="item_value",
    ).reset_index()
    announcement = (
        frame.groupby(["symbol", "report_period"], as_index=False)[
            "announcement_date"
        ]
        .max()
    )
    wide = wide.merge(
        announcement,
        on=["symbol", "report_period"],
        how="left",
        validate="one_to_one",
    ).sort_values(["symbol", "report_period"])
    for input_name in wanted.values():
        if input_name not in wide:
            wide[input_name] = np.nan

    pieces: list[pd.DataFrame] = []
    for symbol, group in wide.groupby("symbol", sort=False):
        group = group.copy().sort_values("report_period")
        for base in [
            "revenue",
            "net_profit",
            "net_profit_parent",
            "operating_cash_flow",
        ]:
            cumulative = f"{base}_cumulative"
            if cumulative not in group:
                group[cumulative] = np.nan
            group[f"{base}_single_quarter"] = _single_quarter(
                group[cumulative], group["report_period"]
            )
        group["revenue_ttm"] = _ttm_if_four_consecutive(
            group["revenue_single_quarter"], group["report_period"]
        )
        group["net_profit_ttm"] = _ttm_if_four_consecutive(
            group["net_profit_single_quarter"], group["report_period"]
        )
        for metric in ["revenue", "net_profit"]:
            prior = group.set_index("report_period")[f"{metric}_cumulative"]
            prior.index = prior.index + pd.DateOffset(years=1)
            comparable = group["report_period"].map(prior)
            group[f"{metric}_yoy"] = (
                safe_divide(group[f"{metric}_cumulative"], comparable) - 1.0
            )
        group["gross_margin"] = 1.0 - safe_divide(
            group.get("operating_cost_cumulative"),
            group.get("revenue_cumulative"),
        )
        group["net_margin"] = safe_divide(
            group.get("net_profit_cumulative"),
            group.get("revenue_cumulative"),
        )
        group["operating_cf_over_net_profit"] = safe_divide(
            group.get("operating_cash_flow_cumulative"),
            group.get("net_profit_cumulative"),
        )
        prior_equity = group.get("parent_equity", pd.Series(np.nan, index=group.index)).shift(1)
        average_equity = (
            group.get("parent_equity", pd.Series(np.nan, index=group.index))
            + prior_equity
        ) / 2.0
        annualization = group["report_period"].dt.quarter.rdiv(4.0)
        group["roe"] = safe_divide(
            group.get("net_profit_parent_cumulative"), average_equity
        ) * annualization
        group["debt_to_asset_ratio"] = safe_divide(
            group.get("total_liabilities"), group.get("total_assets")
        )
        group["revenue"] = group.get("revenue_cumulative")
        group["net_profit"] = group.get("net_profit_cumulative")
        group["net_profit_parent"] = group.get("net_profit_parent_cumulative")
        pieces.append(group)
    calculated = pd.concat(pieces, ignore_index=True) if pieces else wide

    retained: list[pd.DataFrame] = []
    for _, group in calculated.groupby("symbol", sort=False):
        ordered = group.sort_values("report_period")
        recent_quarters = ordered.tail(quarterly_reports_count)
        recent_annual = ordered.loc[
            ordered["report_period"].dt.month.eq(12)
            & ordered["report_period"].dt.day.eq(31)
        ].tail(annual_reports_years)
        retained.append(
            pd.concat([recent_quarters, recent_annual], ignore_index=True)
            .drop_duplicates("report_period")
            .sort_values("report_period")
        )
    calculated = (
        pd.concat(retained, ignore_index=True) if retained else calculated.iloc[0:0]
    )
    long = calculated.melt(
        id_vars=["symbol", "report_period", "announcement_date"],
        value_vars=FUNDAMENTAL_FEATURES,
        var_name="feature_name",
        value_name="feature_value",
    )
    long["feature_as_of_date"] = as_of_date
    long["formula_version"] = "stage6_v1"
    long["quality_status"] = np.where(
        long["feature_value"].notna(), "available", "insufficient_quarters_or_input"
    )
    long["source_lineage"] = "v_financial_point_in_time_safe"
    return long.sort_values(
        ["symbol", "report_period", "feature_name"]
    ).reset_index(drop=True)


def build_current_snapshot(
    spot: pd.DataFrame, target_symbols: list[str]
) -> pd.DataFrame:
    """Build a current-only valuation snapshot, never a historical as-of row."""
    frame = spot.copy()
    frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    frame = frame.loc[frame["symbol"].isin(target_symbols)].copy()
    preferred = frame.loc[frame["snapshot_scope"].eq("target_16")]
    if not preferred.empty:
        frame = preferred
    frame["snapshot_at"] = pd.to_datetime(frame["snapshot_at"], utc=True)
    frame = frame.sort_values(["symbol", "snapshot_at"]).drop_duplicates(
        "symbol", keep="last"
    )
    frame["is_historical_as_of"] = False
    frame["pe_status"] = np.select(
        [frame["pe_dynamic"].isna(), frame["pe_dynamic"].lt(0)],
        ["unavailable", "loss_making"],
        default="available",
    )
    return frame[
        [
            "transform_run_id",
            "source_run_id",
            "symbol",
            "exchange",
            "snapshot_at",
            "pe_dynamic",
            "pb",
            "market_cap_cny",
            "float_market_cap_cny",
            "is_historical_as_of",
            "pe_status",
            "source_file",
        ]
    ].rename(
        columns={
            "pe_dynamic": "current_pe_dynamic",
            "pb": "current_pb",
            "market_cap_cny": "current_market_cap_cny",
            "float_market_cap_cny": "current_float_market_cap_cny",
        }
    )


def build_suspected_behavior_evidence(
    price: pd.DataFrame,
    activity: pd.DataFrame,
    fund_flow: pd.DataFrame,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    """Emit neutral evidence with explicit insufficiency.

    The frozen config supplies no confidence formula or evidence threshold.
    Inventing either is prohibited, so confidence remains NULL and the record
    explicitly states that evidence is insufficient.
    """
    latest_price = (
        price.loc[price["trade_date"].le(as_of_date)]
        .sort_values(["symbol", "trade_date"])
        .drop_duplicates("symbol", keep="last")
    )
    latest_activity = (
        activity.loc[activity["trade_date"].le(as_of_date)]
        .sort_values(["symbol", "trade_date"])
        .drop_duplicates("symbol", keep="last")
    )
    latest_fund = (
        fund_flow.loc[fund_flow["trade_date"].le(as_of_date)]
        .sort_values(["symbol", "trade_date"])
        .drop_duplicates("symbol", keep="last")
    )
    result = latest_price[["symbol", "exchange", "trade_date"]].merge(
        latest_activity[
            [
                "symbol",
                "volume_spike_frequency_120",
                "turnover_rate_120",
                "activity_score",
            ]
        ],
        on="symbol",
        how="left",
        validate="one_to_one",
    ).merge(
        latest_fund[["symbol", "main_net_inflow_ratio"]],
        on="symbol",
        how="left",
        validate="one_to_one",
    )
    result["as_of_date"] = as_of_date
    result["abnormal_volume_evidence"] = result["volume_spike_frequency_120"]
    result["turnover_change_evidence"] = result["turnover_rate_120"]
    result["fund_flow_persistence_evidence"] = np.nan
    result["price_volume_divergence_evidence"] = np.nan
    result["limit_event_evidence"] = np.nan
    result["evidence_count"] = result[
        [
            "abnormal_volume_evidence",
            "turnover_change_evidence",
            "fund_flow_persistence_evidence",
            "price_volume_divergence_evidence",
            "limit_event_evidence",
        ]
    ].notna().sum(axis=1)
    result["confidence_score"] = np.nan
    result["confidence_level"] = "证据不足"
    result["evidence_summary"] = (
        "疑似主力行为特征：仅记录中性量价与资金流证据；"
        "冻结配置未定义置信度公式，不能推断任何个人或机构意图"
    )
    result["insufficient_evidence"] = True
    return result[
        [
            "symbol",
            "exchange",
            "as_of_date",
            "abnormal_volume_evidence",
            "turnover_change_evidence",
            "fund_flow_persistence_evidence",
            "price_volume_divergence_evidence",
            "limit_event_evidence",
            "evidence_count",
            "confidence_score",
            "confidence_level",
            "evidence_summary",
            "insufficient_evidence",
        ]
    ]
