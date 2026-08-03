"""Asset identity and trading-calendar abstractions shared across asset classes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetType(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"


class TradingCalendar(str, Enum):
    EXCHANGE_SESSIONS = "exchange_sessions"
    CONTINUOUS_24_7 = "continuous_24_7"


@dataclass(frozen=True)
class AssetIdentity:
    symbol: str
    exchange: str
    market: str
    asset_type: AssetType
    trading_calendar: TradingCalendar

    def __post_init__(self) -> None:
        if not self.symbol or not self.exchange or not self.market:
            raise ValueError("symbol, exchange and market are required")
        if self.asset_type is AssetType.CRYPTO and self.trading_calendar is not TradingCalendar.CONTINUOUS_24_7:
            raise ValueError("crypto assets must use continuous_24_7 trading_calendar")
        if self.asset_type is AssetType.EQUITY and self.trading_calendar is TradingCalendar.CONTINUOUS_24_7:
            raise ValueError("equity assets cannot use continuous_24_7 trading_calendar")


@dataclass(frozen=True)
class CryptoIdentityContract:
    """Exact upstream and normalized identity accepted by Stage 11."""

    requested_instrument: str
    raw_instrument: str
    normalized_instrument: str
    data_provider: str
    raw_exchange: str
    normalized_exchange: str
    instrument_type: str
    bar_interval: str

    def __post_init__(self) -> None:
        values = {
            name: value for name, value in vars(self).items()
            if not isinstance(value, str) or not value.strip()
        }
        if values:
            raise ValueError(f"crypto identity fields must be non-empty: {sorted(values)}")


ETHUSDT_OKX_SPOT = CryptoIdentityContract(
    requested_instrument="ETH-USDT",
    raw_instrument="ETH-USDT",
    normalized_instrument="ETHUSDT",
    data_provider="okx_public_api",
    raw_exchange="OKX",
    normalized_exchange="OKX",
    instrument_type="spot",
    bar_interval="1h",
)


ETHUSDT = AssetIdentity(
    symbol="ETHUSDT", exchange="OKX", market="spot",
    asset_type=AssetType.CRYPTO,
    trading_calendar=TradingCalendar.CONTINUOUS_24_7,
)
