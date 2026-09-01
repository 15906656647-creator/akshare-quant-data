"""Strict configuration contract for Stage 17 multi-market collection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


EXPECTED_A_SHARES = (
    "002067", "002600", "002230", "600763", "603259", "603799",
    "601012", "600438", "002361", "601500", "600231", "300274",
    "601636", "002129", "000100", "300433",
)
EXPECTED_H_SHARES = (
    "02180.HK", "08365.HK", "08462.HK", "02076.HK", "06100.HK",
    "06919.HK", "09669.HK",
)
EXPECTED_ADJUSTMENTS = ("raw", "qfq", "hfq")
EXPECTED_CRYPTO_INTERVALS = ("1m", "3m", "5m", "15m", "1h", "1d")
EXPECTED_PROVIDER_POLICY = {
    "a_share": {
        "primary": {"source": "eastmoney", "interface": "stock_zh_a_hist"},
        "fallback": {"source": "sina", "interface": "stock_zh_a_daily"},
        "fallback_on": ("connection_error", "timeout", "rate_limit", "empty_result"),
    },
    "h_share": {
        "primary": {"source": "eastmoney", "interface": "stock_hk_hist"},
        "fallback": {"source": "sina", "interface": "stock_hk_daily"},
        "fallback_on": (
            "connection_error", "timeout", "rate_limit", "empty_result",
            "ohlc_logic_error",
        ),
    },
}
EXPECTED_HK_PROVIDER_ROUTES = {
    symbol: {
        "raw": ("tencent", "eastmoney", "sina"),
        "qfq": ("tencent", "eastmoney", "sina"),
        "hfq": ("tencent", "eastmoney", "sina"),
    }
    for symbol in EXPECTED_H_SHARES
}
EXPECTED_HK_PROVIDER_ROUTES["08462.HK"] = {
    "raw": ("tencent", "eastmoney", "sina"),
    "qfq": ("tencent", "tencent_compat", "eastmoney", "sina"),
    "hfq": ("tencent", "tencent_compat", "eastmoney", "sina"),
}
EXPECTED_HK_PROVIDER_ROUTES["09669.HK"] = {
    "raw": ("tencent", "eastmoney", "sina"),
    "qfq": ("tencent_compat", "eastmoney", "sina"),
    "hfq": ("tencent_compat", "eastmoney", "sina"),
}

def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ConfigError(f"Stage 17 {field} must be an explicit YYYY-MM-DD string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ConfigError(f"Invalid Stage 17 {field}: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ConfigError(f"Invalid Stage 17 {field}: {value!r}")
    return parsed


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 17 {field} must be a mapping")
    return value


def _keys(mapping: dict[str, Any], *, required: set[str], field: str) -> None:
    missing = sorted(required - set(mapping))
    unknown = sorted(set(mapping) - required)
    if missing or unknown:
        raise ConfigError(
            f"Stage 17 {field} keys invalid; missing={missing}, unknown={unknown}"
        )


@dataclass(frozen=True)
class EquityTarget:
    symbol: str
    market: str
    exchange: str
    currency: str
    timezone: str

    @property
    def source_symbol(self) -> str:
        return self.symbol[:-3] if self.market == "HK" else self.symbol


@dataclass(frozen=True)
class Stage17Config:
    path: Path
    schema_version: str
    model_version: str
    as_of_date: date
    equity_start_date: date
    adjustments: tuple[str, ...]
    strict_listing_coverage: bool
    provider_policy: dict[str, dict[str, Any]]
    hk_provider_routes: dict[str, dict[str, tuple[str, ...]]]
    equities: tuple[EquityTarget, ...]
    minute_direct_intervals: tuple[str, ...]
    minute_derived_interval: str
    minute_samples: tuple[str, ...]
    minute_start_date: date
    crypto_symbol: str
    crypto_instrument: str
    crypto_provider: str
    crypto_intervals: tuple[str, ...]
    crypto_minute_intervals: tuple[str, ...]
    crypto_long_intervals: tuple[str, ...]
    crypto_minute_lookback_days: int
    crypto_long_start_date: date
    max_attempts: int
    akshare_retry_delay_seconds: float
    max_retry_delay_seconds: float
    inter_request_delay_seconds: float
    request_timeout_seconds: float
    okx_page_limit: int
    raw_root: Path
    reports_root: Path

    @property
    def daily_expected_count(self) -> int:
        return len(self.equities) * len(self.adjustments)


def load_stage17_config(path: str | Path) -> Stage17Config:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 17 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 17 YAML parse error: {exc}") from exc
    root = _mapping(raw, "root")
    _keys(root, required={
        "schema_version", "stage", "as_of_date", "model_version",
        "equity_daily", "equity_minute_feasibility", "crypto", "runtime",
        "storage",
    }, field="root")
    if root["stage"] != 17:
        raise ConfigError("Stage 17 config stage must equal 17")
    if not str(root["schema_version"]).strip() or not str(root["model_version"]).strip():
        raise ConfigError("Stage 17 schema_version and model_version are required")

    daily = _mapping(root["equity_daily"], "equity_daily")
    _keys(daily, required={
        "start_date", "adjustments", "strict_listing_coverage", "a_shares",
        "h_shares", "providers",
    }, field="equity_daily")
    providers = _mapping(daily["providers"], "equity_daily.providers")
    _keys(
        providers, required={"a_share", "h_share"},
        field="equity_daily.providers",
    )
    provider_policy: dict[str, dict[str, Any]] = {}
    hk_provider_routes: dict[str, dict[str, tuple[str, ...]]] = {}
    for market_key, expected in EXPECTED_PROVIDER_POLICY.items():
        policy = _mapping(providers[market_key], f"providers.{market_key}")
        required = {"primary", "fallback", "fallback_on"}
        if market_key == "h_share":
            required.add("registry")
        _keys(
            policy, required=required,
            field=f"providers.{market_key}",
        )
        primary = _mapping(policy["primary"], f"providers.{market_key}.primary")
        fallback = _mapping(policy["fallback"], f"providers.{market_key}.fallback")
        _keys(primary, required={"source", "interface"}, field=f"providers.{market_key}.primary")
        _keys(fallback, required={"source", "interface"}, field=f"providers.{market_key}.fallback")
        normalized = {
            "primary": {"source": str(primary["source"]), "interface": str(primary["interface"])},
            "fallback": {"source": str(fallback["source"]), "interface": str(fallback["interface"])},
            "fallback_on": tuple(str(value) for value in policy["fallback_on"]),
        }
        if normalized != expected:
            raise ConfigError(f"Stage 17 {market_key} provider policy differs from the audited policy")
        provider_policy[market_key] = normalized
        if market_key == "h_share":
            registry = _mapping(policy["registry"], "providers.h_share.registry")
            _keys(
                registry, required=set(EXPECTED_H_SHARES),
                field="providers.h_share.registry",
            )
            for symbol in EXPECTED_H_SHARES:
                route = _mapping(registry[symbol], f"registry.{symbol}")
                _keys(
                    route, required=set(EXPECTED_ADJUSTMENTS),
                    field=f"registry.{symbol}",
                )
                normalized_route = {
                    adjust: tuple(str(value) for value in route[adjust])
                    for adjust in EXPECTED_ADJUSTMENTS
                }
                if normalized_route != EXPECTED_HK_PROVIDER_ROUTES[symbol]:
                    raise ConfigError(f"Stage 17 HK registry route differs for {symbol}")
                hk_provider_routes[symbol] = normalized_route
    a_rows = daily["a_shares"]
    if not isinstance(a_rows, list):
        raise ConfigError("Stage 17 equity_daily.a_shares must be a list")
    a_symbols: list[str] = []
    a_targets: list[EquityTarget] = []
    for index, row in enumerate(a_rows):
        item = _mapping(row, f"equity_daily.a_shares[{index}]")
        _keys(item, required={"symbol", "exchange"}, field=f"a_shares[{index}]")
        symbol, exchange = str(item["symbol"]), str(item["exchange"])
        if len(symbol) != 6 or not symbol.isdigit() or exchange not in {"SH", "SZ"}:
            raise ConfigError(f"Invalid A-share identity: {item!r}")
        a_symbols.append(symbol)
        a_targets.append(EquityTarget(symbol, "A", exchange, "CNY", "Asia/Shanghai"))
    if tuple(a_symbols) != EXPECTED_A_SHARES:
        raise ConfigError("Stage 17 A-share universe differs from the frozen 16-symbol order")

    h_symbols = tuple(str(value).upper() for value in daily["h_shares"])
    if h_symbols != EXPECTED_H_SHARES:
        raise ConfigError("Stage 17 H-share universe differs from the frozen 7-symbol order")
    h_targets = [
        EquityTarget(symbol, "HK", "HKEX", "HKD", "Asia/Hong_Kong")
        for symbol in h_symbols
    ]
    adjustments = tuple(str(value) for value in daily["adjustments"])
    if adjustments != EXPECTED_ADJUSTMENTS:
        raise ConfigError("Stage 17 adjustments must be exactly raw, qfq, hfq")
    if daily["strict_listing_coverage"] is not True:
        raise ConfigError("Stage 17 strict_listing_coverage must remain true")

    minute = _mapping(root["equity_minute_feasibility"], "equity_minute_feasibility")
    _keys(minute, required={
        "direct_intervals", "derived_report_only_interval", "a_share_samples",
        "h_share_samples", "start_date",
    }, field="equity_minute_feasibility")
    direct = tuple(str(value) for value in minute["direct_intervals"])
    if direct != ("1m", "5m") or str(minute["derived_report_only_interval"]) != "3m":
        raise ConfigError("Equity minute feasibility must use direct 1m/5m and report-only 3m")
    samples = tuple(str(value).upper() for value in (
        list(minute["a_share_samples"]) + list(minute["h_share_samples"])
    ))
    if samples != ("002067", "300274", "600763", "02180.HK", "08365.HK"):
        raise ConfigError("Stage 17 minute samples differ from the approved representative set")

    crypto = _mapping(root["crypto"], "crypto")
    _keys(crypto, required={
        "symbol", "requested_instrument", "provider", "exchange", "market",
        "timezone", "minute_intervals", "long_history_intervals",
        "minute_lookback_days", "long_history_start_date", "confirmed_only",
    }, field="crypto")
    minute_intervals = tuple(str(value) for value in crypto["minute_intervals"])
    long_intervals = tuple(str(value) for value in crypto["long_history_intervals"])
    intervals = minute_intervals + long_intervals
    if intervals != EXPECTED_CRYPTO_INTERVALS:
        raise ConfigError("Stage 17 crypto intervals must be exactly 1m,3m,5m,15m,1h,1d")
    identity = (
        str(crypto["symbol"]), str(crypto["requested_instrument"]),
        str(crypto["provider"]), str(crypto["exchange"]), str(crypto["market"]),
        str(crypto["timezone"]), crypto["confirmed_only"],
    )
    if identity != ("ETHUSDT", "ETH-USDT", "okx_public_api", "OKX", "spot", "UTC", True):
        raise ConfigError("Stage 17 crypto identity must remain exact OKX ETH-USDT spot")

    runtime = _mapping(root["runtime"], "runtime")
    _keys(runtime, required={
        "max_attempts", "akshare_retry_delay_seconds", "max_retry_delay_seconds", "inter_request_delay_seconds",
        "request_timeout_seconds", "okx_page_limit",
    }, field="runtime")
    max_attempts = int(runtime["max_attempts"])
    page_limit = int(runtime["okx_page_limit"])
    if not 1 <= max_attempts <= 3 or not 1 <= page_limit <= 300:
        raise ConfigError("Stage 17 runtime max_attempts/page_limit out of range")

    max_retry_delay = float(runtime["max_retry_delay_seconds"])
    if max_retry_delay < float(runtime["akshare_retry_delay_seconds"]):
        raise ConfigError("Stage 17 max retry delay must not be less than the base delay")
    storage = _mapping(root["storage"], "storage")
    _keys(storage, required={"raw_root", "reports_root"}, field="storage")
    return Stage17Config(
        path=config_path,
        schema_version=str(root["schema_version"]),
        model_version=str(root["model_version"]),
        as_of_date=_date(root["as_of_date"], "as_of_date"),
        equity_start_date=_date(daily["start_date"], "equity_daily.start_date"),
        adjustments=adjustments,
        strict_listing_coverage=True,
        provider_policy=provider_policy,
        hk_provider_routes=hk_provider_routes,
        equities=tuple(a_targets + h_targets),
        minute_direct_intervals=direct,
        minute_derived_interval="3m",
        minute_samples=samples,
        minute_start_date=_date(minute["start_date"], "equity_minute_feasibility.start_date"),
        crypto_symbol="ETHUSDT",
        crypto_instrument="ETH-USDT",
        crypto_provider="okx_public_api",
        crypto_intervals=intervals,
        crypto_minute_intervals=minute_intervals,
        crypto_long_intervals=long_intervals,
        crypto_minute_lookback_days=int(crypto["minute_lookback_days"]),
        crypto_long_start_date=_date(crypto["long_history_start_date"], "crypto.long_history_start_date"),
        max_attempts=max_attempts,
        akshare_retry_delay_seconds=float(runtime["akshare_retry_delay_seconds"]),
        max_retry_delay_seconds=max_retry_delay,
        inter_request_delay_seconds=float(runtime["inter_request_delay_seconds"]),
        request_timeout_seconds=float(runtime["request_timeout_seconds"]),
        okx_page_limit=page_limit,
        raw_root=Path(str(storage["raw_root"])),
        reports_root=Path(str(storage["reports_root"])),
    )
