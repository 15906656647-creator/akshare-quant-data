"""Stage 1: Configuration loader tests.

Validates that config.py correctly loads and validates Stage 0 YAML configs.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from akshare_data_test.config import (
    ConfigError,
    load_metrics,
    load_universe,
    resolve_as_of_date,
)


class TestLoadUniverse:
    def test_parses_without_error(self):
        u = load_universe()
        assert u is not None
        assert u.schema_version == "1.0.0"

    def test_stock_count_is_16(self):
        u = load_universe()
        assert len(u.stocks) == 16

    def test_all_symbols_are_strings(self):
        u = load_universe()
        for s in u.stocks:
            assert isinstance(s.symbol, str)
            assert len(s.symbol) == 6
            assert s.symbol.isdigit()

    def test_no_duplicate_symbols(self):
        u = load_universe()
        symbols = [s.symbol for s in u.stocks]
        assert len(symbols) == len(set(symbols))

    def test_expected_symbols_present(self):
        expected = [
            "002067", "002600", "002230", "600763",
            "603259", "603799", "601012", "600438",
            "002361", "601500", "600231", "300274",
            "601636", "002129", "000100", "300433",
        ]
        u = load_universe()
        actual = sorted(s.symbol for s in u.stocks)
        assert actual == sorted(expected)

    def test_exchange_mapping_correct(self):
        u = load_universe()
        for s in u.stocks:
            if s.symbol.startswith(("600", "601", "603")):
                assert s.exchange == "SH"
                assert s.market_lower == "sh"
            elif s.symbol.startswith(("000", "002", "300")):
                assert s.exchange == "SZ"
                assert s.market_lower == "sz"
            assert s.symbol_em == s.exchange + s.symbol

    def test_as_of_date_is_2026_07_27(self):
        u = load_universe()
        assert u.as_of_date == date(2026, 7, 27)

    def test_crypto_ethusdt_exact_match(self):
        u = load_universe()
        assert len(u.crypto) >= 1
        c = u.crypto[0]
        assert c.requested_pair == "ETHUSDT"
        assert c.exact_match_required is True
        assert c.allow_pair_substitution is False
        assert c.base_asset == "ETH"
        assert c.quote_asset == "USDT"


class TestLoadMetrics:
    def test_parses_without_error(self):
        m = load_metrics()
        assert m is not None
        assert m.schema_version == "1.0.0"

    def test_as_of_date_is_2026_07_27(self):
        m = load_metrics()
        assert m.as_of_date == date(2026, 7, 27)

    def test_ma_windows_correct(self):
        m = load_metrics()
        ma_price = m.raw.get("ma_windows", {}).get("price", [])
        assert ma_price == [3, 5, 7, 10, 13, 20, 21]

    def test_adjustment_rules(self):
        m = load_metrics()
        adj = m.raw.get("adjustment_rules", {})
        assert adj.get("trend_and_ma", {}).get("adjust") == "qfq"
        assert adj.get("limit_detection", {}).get("adjust") == ""
        assert adj.get("mixed_forbidden") is True

    def test_activity_weights_sum_to_one(self):
        m = load_metrics()
        weights = m.raw.get("activity_scoring", {}).get("weights", {})
        weight_sum = sum(float(v) for v in weights.values())
        assert abs(weight_sum - 1.0) < 0.001

    def test_style_labels_correct(self):
        m = load_metrics()
        labels = set(m.raw.get("consolidation_analysis", {}).get("style_labels", []))
        expected = {"温和箱体型", "高波动震荡型", "放量冲击型",
                    "低活跃盘整型", "趋势型", "证据不足"}
        assert labels == expected


class TestResolveAsOfDate:
    def test_from_config_baseline(self):
        d = resolve_as_of_date(cli_date=None)
        assert d == date(2026, 7, 27)

    def test_cli_overrides_config(self):
        d = resolve_as_of_date(cli_date="2025-12-01")
        assert d == date(2025, 12, 1)

    def test_invalid_date_raises(self):
        with pytest.raises(ConfigError):
            resolve_as_of_date(cli_date="not-a-date")

    def test_invalid_format_raises(self):
        with pytest.raises(ConfigError):
            resolve_as_of_date(cli_date="2026/07/27")

    def test_no_system_date_fallback(self):
        import datetime as dt_mod
        today = dt_mod.date.today()
        d = resolve_as_of_date(cli_date=None)
        assert d != today, "as_of_date must not fall back to system date"
        assert d == date(2026, 7, 27)
