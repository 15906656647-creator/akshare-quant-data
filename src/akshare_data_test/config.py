"""Stage 0 configuration loader with validation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .paths import metric_definition_path, universe_path


class ConfigError(Exception):
    """Configuration parsing or validation error."""


@dataclass
class StockConfig:
    """Parsed stock entry from universe.yml."""
    symbol: str
    exchange: str
    symbol_em: str
    market_lower: str


@dataclass
class CryptoConfig:
    """Parsed crypto entry from universe.yml."""
    requested_pair: str
    base_asset: str
    quote_asset: str
    exact_match_required: bool
    allow_pair_substitution: bool
    result_enum: list[str]


@dataclass
class UniverseConfig:
    """Parsed universe.yml."""
    schema_version: str
    project_name: str
    timezone: str
    base_currency: str
    as_of_date: date
    stocks: list[StockConfig]
    crypto: list[CryptoConfig]


@dataclass
class MetricConfig:
    """Parsed metric_definition.yml."""
    schema_version: str
    as_of_date: date
    raw: dict[str, Any]


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_iso_date(value: str, path: Path) -> date:
    if not _DATE_RE.match(value):
        raise ConfigError(
            f"Invalid date format '{value}' in {path}; expected YYYY-MM-DD"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise ConfigError(f"Invalid date value '{value}' in {path}: {e}")


def load_universe() -> UniverseConfig:
    """Load and validate config/universe.yml."""
    path = universe_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"Universe config not found: {path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {path}: {e}")

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Universe config root must be a mapping, "
            f"got {type(raw).__name__} in {path}"
        )

    if "as_of_date" not in raw:
        raise ConfigError(f"Missing 'as_of_date' in {path}")
    as_of_date = _parse_iso_date(str(raw["as_of_date"]), path)

    stocks_raw = raw.get("stocks", [])
    if not isinstance(stocks_raw, list):
        raise ConfigError(f"'stocks' must be a list in {path}")
    if len(stocks_raw) != 16:
        raise ConfigError(
            f"Expected 16 stocks in {path}, got {len(stocks_raw)}"
        )

    stocks: list[StockConfig] = []
    for s in stocks_raw:
        symbol = str(s.get("symbol", ""))
        if not symbol or len(symbol) != 6 or not symbol.isdigit():
            raise ConfigError(f"Invalid stock symbol '{symbol}' in {path}")
        stocks.append(StockConfig(
            symbol=symbol,
            exchange=str(s.get("exchange", "")),
            symbol_em=str(s.get("symbol_em", "")),
            market_lower=str(s.get("market_lower", "")),
        ))

    crypto_list: list[CryptoConfig] = []
    crypto_raw = raw.get("crypto", [])
    if isinstance(crypto_raw, list):
        for c in crypto_raw:
            crypto_list.append(CryptoConfig(
                requested_pair=str(c.get("requested_pair", "")),
                base_asset=str(c.get("base_asset", "")),
                quote_asset=str(c.get("quote_asset", "")),
                exact_match_required=bool(c.get("exact_match_required", False)),
                allow_pair_substitution=bool(
                    c.get("allow_pair_substitution", True)
                ),
                result_enum=[str(x) for x in c.get("result_enum", [])],
            ))

    return UniverseConfig(
        schema_version=str(raw.get("schema_version", "")),
        project_name=str(raw.get("project_name", "")),
        timezone=str(raw.get("timezone", "")),
        base_currency=str(raw.get("base_currency", "")),
        as_of_date=as_of_date,
        stocks=stocks,
        crypto=crypto_list,
    )


def load_metrics() -> MetricConfig:
    """Load and validate config/metric_definition.yml."""
    path = metric_definition_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(f"Metric definition config not found: {path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {path}: {e}")

    if not isinstance(raw, dict):
        raise ConfigError(
            f"Metric config root must be a mapping, "
            f"got {type(raw).__name__} in {path}"
        )

    if "as_of_date" not in raw:
        raise ConfigError(f"Missing 'as_of_date' in {path}")
    as_of_date = _parse_iso_date(str(raw["as_of_date"]), path)

    return MetricConfig(
        schema_version=str(raw.get("schema_version", "")),
        as_of_date=as_of_date,
        raw=raw,
    )


def resolve_as_of_date(cli_date: str | None = None) -> date:
    """Resolve business as_of_date.

    CLI argument takes priority, then config baseline.
    Never falls back to system date.
    """
    if cli_date is not None:
        try:
            return datetime.strptime(cli_date, "%Y-%m-%d").date()
        except ValueError as e:
            raise ConfigError(f"Invalid --as-of-date '{cli_date}': {e}")
    universe = load_universe()
    return universe.as_of_date
