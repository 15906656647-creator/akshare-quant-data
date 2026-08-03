"""Stage 11 crypto normalization, 24/7 time handling and indicator migration."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .assets import (
    AssetIdentity, AssetType, CryptoIdentityContract, ETHUSDT_OKX_SPOT,
    TradingCalendar,
)


PRICE_COLUMNS = ["open", "high", "low", "close"]
RAW_COLUMNS = [
    "requested_instrument", "raw_instrument", "normalized_instrument",
    "data_provider", "raw_exchange", "normalized_exchange",
    "instrument_type", "bar_interval", "confirmed",
    "symbol", "exchange", "market", "asset_type", "trading_calendar",
    "interval", "trade_time", "local_trade_time", "utc_trade_date",
    "local_trade_date", "open", "high", "low", "close", "volume",
    "quote_volume", "source", "run_id",
]
INDICATOR_COLUMNS = [
    "symbol", "exchange", "interval", "trade_time", "return_1bar",
    "realized_volatility", "annualized_volatility", "true_range", "atr",
    "atr_ratio", "bollinger_middle", "bollinger_upper", "bollinger_lower",
    "bollinger_band_width", "trend_slope", "trend_r_squared", "box_high",
    "box_low", "box_width", "false_breakout_up", "false_breakout_down",
    "indicator_status", "run_id",
]


def load_stage11_config(path: Path) -> tuple[dict[str, Any], str]:
    raw_bytes = path.read_bytes()
    config = yaml.safe_load(raw_bytes)
    required = {"schema_version", "model_version", "symbol", "exchange", "market", "asset_type", "trading_calendar", "identity", "source", "time", "indicators"}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("Stage 11 config fields are incomplete or unknown")
    if config["asset_type"] != "crypto" or config["trading_calendar"] != "continuous_24_7":
        raise ValueError("Stage 11 only supports crypto with continuous_24_7 calendar")
    if config["time"]["canonical_timezone"] != "UTC":
        raise ValueError("Stage 11 canonical timezone must be UTC")
    contract = identity_contract_from_config(config)
    if contract != ETHUSDT_OKX_SPOT:
        raise ValueError("Stage 11 exact identity must be OKX SPOT ETH-USDT at 1h")
    return config, hashlib.sha256(raw_bytes).hexdigest()


def identity_contract_from_config(config: dict[str, Any]) -> CryptoIdentityContract:
    identity = config.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("Stage 11 config identity contract is required")
    try:
        return CryptoIdentityContract(**identity)
    except TypeError as exc:
        raise ValueError(f"Stage 11 identity contract fields are invalid: {exc}") from exc


def validate_crypto_identity(
    frame: pd.DataFrame, *, expected: CryptoIdentityContract = ETHUSDT_OKX_SPOT,
) -> None:
    """Fail closed before normalization can write any standardized identity."""
    required = {
        "raw_instrument", "data_provider", "raw_exchange", "instrument_type",
        "bar_interval", "confirmed",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"crypto identity missing fields: {missing}")
    comparisons = {
        "raw_instrument": expected.raw_instrument,
        "data_provider": expected.data_provider,
        "raw_exchange": expected.raw_exchange,
        "instrument_type": expected.instrument_type,
        "bar_interval": expected.bar_interval,
    }
    for field, expected_value in comparisons.items():
        values = frame[field].dropna().astype(str).str.strip().unique().tolist()
        if len(values) != 1 or values[0] != expected_value:
            raise ValueError(
                f"crypto identity mismatch for {field}: expected {expected_value!r}, observed {values!r}"
            )
        if frame[field].isna().any():
            raise ValueError(f"crypto identity field {field} contains missing values")
    confirmed = frame["confirmed"].astype("string").str.lower()
    if not confirmed.isin({"1", "true"}).all():
        raise ValueError("crypto bars contain an unfinished candle (confirmed must be true/1)")


def normalize_crypto_bars(
    frame: pd.DataFrame, *, asset: AssetIdentity, interval: str,
    local_timezone: str, source: str, run_id: str,
    identity: CryptoIdentityContract = ETHUSDT_OKX_SPOT,
) -> pd.DataFrame:
    if asset.asset_type is not AssetType.CRYPTO or asset.trading_calendar is not TradingCalendar.CONTINUOUS_24_7:
        raise ValueError("crypto bars require a continuous_24_7 crypto asset")
    validate_crypto_identity(frame, expected=identity)
    if source != identity.data_provider:
        raise ValueError(
            f"source argument must match verified data_provider {identity.data_provider!r}, got {source!r}"
        )
    if interval != identity.bar_interval:
        raise ValueError(f"bar interval must be {identity.bar_interval!r}, got {interval!r}")
    if asset.symbol != identity.normalized_instrument or asset.exchange != identity.normalized_exchange:
        raise ValueError("asset identity does not match the verified crypto identity contract")
    required = {"trade_time", *PRICE_COLUMNS, "volume", "quote_volume"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"crypto input missing columns: {missing}")
    out = frame.copy()
    naive_rows = []
    for index, value in out["trade_time"].items():
        try:
            if pd.Timestamp(value).tzinfo is None:
                naive_rows.append(index)
        except (TypeError, ValueError):
            pass
    if naive_rows:
        raise ValueError(f"trade_time must carry an explicit timezone; naive rows: {naive_rows[:5]}")
    parsed = pd.to_datetime(out["trade_time"], errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError("trade_time contains invalid or timezone-unresolvable values")
    out["trade_time"] = parsed
    out["local_trade_time"] = parsed.dt.tz_convert(local_timezone)
    out["utc_trade_date"] = parsed.dt.date
    out["local_trade_date"] = out["local_trade_time"].dt.date
    for column in [*PRICE_COLUMNS, "volume", "quote_volume"]:
        if column not in out:
            out[column] = np.nan
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["requested_instrument"] = identity.requested_instrument
    out["normalized_instrument"] = identity.normalized_instrument
    out["normalized_exchange"] = identity.normalized_exchange
    out["confirmed"] = True
    out["symbol"], out["exchange"], out["market"] = identity.normalized_instrument, identity.normalized_exchange, identity.instrument_type
    out["asset_type"], out["trading_calendar"] = asset.asset_type.value, asset.trading_calendar.value
    out["interval"], out["source"], out["run_id"] = identity.bar_interval, identity.data_provider, run_id
    return out[RAW_COLUMNS].reset_index(drop=True)


def resample_crypto_bars(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Aggregate in UTC; daily boundaries are UTC boundaries, never stock sessions."""
    if frequency not in {"1h", "1d"}:
        raise ValueError("frequency must be 1h or 1d")
    rule = "1h" if frequency == "1h" else "1D"
    indexed = frame.set_index(pd.DatetimeIndex(pd.to_datetime(frame["trade_time"], utc=True)))
    grouped = indexed.resample(rule, label="left", closed="left")
    result = grouped.agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "quote_volume": "sum",
    }).dropna(subset=["open", "high", "low", "close"]).reset_index(names="trade_time")
    return result


def _rolling_regression(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 2 or not np.isfinite(values).all() or (values <= 0).any():
        return np.nan, np.nan
    x, y = np.arange(len(values), dtype=float), np.log(values)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    total = float(((y - y.mean()) ** 2).sum())
    residual = float(((y - fitted) ** 2).sum())
    return float(np.expm1(slope)), 1.0 if total == 0 else float(max(0, 1 - residual / total))


def compute_crypto_indicators(
    bars: pd.DataFrame, *, interval: str, config: dict[str, Any], run_id: str,
) -> pd.DataFrame:
    """Migrate Stage 9 descriptive indicators with crypto-specific annualization."""
    p = config["indicators"]
    window, atr_window = int(p["window"]), int(p["atr_window"])
    annualization = int(p["annualization_periods"][interval])
    frame = bars.sort_values("trade_time", kind="mergesort").copy()
    close = frame["close"].astype(float)
    returns = close.pct_change()
    previous = close.shift(1)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous).abs(), (frame["low"] - previous).abs(),
    ], axis=1).max(axis=1)
    middle = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std(ddof=0)
    box_high = frame["high"].shift(1).rolling(int(p["box_window"]), min_periods=int(p["box_window"])).max()
    box_low = frame["low"].shift(1).rolling(int(p["box_window"]), min_periods=int(p["box_window"])).min()
    confirmation = int(p["false_breakout_confirmation_bars"])
    breakout_up = close.gt(box_high)
    breakout_down = close.lt(box_low)
    false_up = pd.Series(False, index=frame.index)
    false_down = pd.Series(False, index=frame.index)
    for index in range(len(frame) - confirmation):
        future = close.iloc[index + 1:index + 1 + confirmation]
        if breakout_up.iloc[index] and future.le(box_high.iloc[index]).any():
            false_up.iloc[index] = True
        if breakout_down.iloc[index] and future.ge(box_low.iloc[index]).any():
            false_down.iloc[index] = True
    regressions = close.rolling(int(p["trend_window"]), min_periods=int(p["trend_window"])).apply(
        lambda values: _rolling_regression(values)[0], raw=True
    )
    r_squared = close.rolling(int(p["trend_window"]), min_periods=int(p["trend_window"])).apply(
        lambda values: _rolling_regression(values)[1], raw=True
    )
    result = pd.DataFrame({
        "symbol": frame["symbol"], "exchange": frame["exchange"], "interval": interval,
        "trade_time": frame["trade_time"], "return_1bar": returns,
        "realized_volatility": returns.rolling(window, min_periods=window).std(ddof=1),
        "annualized_volatility": returns.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(annualization),
        "true_range": true_range, "atr": true_range.rolling(atr_window, min_periods=atr_window).mean(),
        "bollinger_middle": middle,
        "bollinger_upper": middle + float(p["bollinger_std_multiplier"]) * std,
        "bollinger_lower": middle - float(p["bollinger_std_multiplier"]) * std,
        "bollinger_band_width": (2 * float(p["bollinger_std_multiplier"]) * std) / middle,
        "trend_slope": regressions, "trend_r_squared": r_squared,
        "box_high": box_high, "box_low": box_low, "box_width": box_high / box_low - 1,
        "false_breakout_up": false_up, "false_breakout_down": false_down,
    })
    result["atr_ratio"] = result["atr"] / close
    result["indicator_status"] = np.where(result["bollinger_middle"].notna(), "calculated", "insufficient_history")
    result["run_id"] = run_id
    return result[INDICATOR_COLUMNS]


def build_crypto_profile(indicators: pd.DataFrame, *, config: dict[str, Any], as_of_date: pd.Timestamp, run_id: str) -> pd.DataFrame:
    calculated = indicators.loc[indicators["indicator_status"].eq("calculated")]
    latest = calculated.tail(1)
    if latest.empty:
        values = {name: None for name in ["annualized_volatility", "atr_ratio", "bollinger_band_width", "trend_slope", "trend_r_squared", "box_width"]}
        status, explanation = "insufficient_history", "历史 K 线不足，无法形成统计特征摘要。"
    else:
        row = latest.iloc[0]
        values = {name: row[name] for name in ["annualized_volatility", "atr_ratio", "bollinger_band_width", "trend_slope", "trend_r_squared", "box_width"]}
        status = "descriptive_only"
        explanation = "仅描述波动、ATR、布林带、趋势、箱体和假突破统计；未形成价格预测、交易信号或投资结论。"
    return pd.DataFrame([{
        "symbol": config["symbol"], "exchange": config["exchange"],
        "asset_type": "crypto", "as_of_date": pd.Timestamp(as_of_date).date(),
        "interval": str(indicators["interval"].iloc[0]) if not indicators.empty else "unknown",
        **values,
        "false_breakout_count": int(calculated[["false_breakout_up", "false_breakout_down"]].sum().sum()) if not calculated.empty else 0,
        "profile_status": status, "explanation": explanation,
        "model_version": config["model_version"], "run_id": run_id,
    }])
