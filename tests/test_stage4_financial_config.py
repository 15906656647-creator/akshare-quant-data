from datetime import date

import pytest

from akshare_data_test.config import load_universe
from akshare_data_test.financial_fetch import INTERFACES, resolve_start_year


def test_stage4_universe_and_task_count():
    universe = load_universe()
    assert len(universe.stocks) == 16
    assert len(INTERFACES) == 6
    assert len(universe.stocks) * len(INTERFACES) == 96
    assert all(len(stock.symbol) == 6 and stock.symbol.isdigit() for stock in universe.stocks)


def test_exchange_parameter_mappings_are_configuration_driven():
    stocks = {stock.symbol: stock for stock in load_universe().stocks}
    assert (stocks["600763"].symbol_em, stocks["600763"].market_lower) == (
        "SH600763", "sh"
    )
    assert (stocks["002067"].symbol_em, stocks["002067"].market_lower) == (
        "SZ002067", "sz"
    )


def test_start_year_is_derived_and_conflict_is_rejected():
    baseline = date(2026, 7, 27)
    assert resolve_start_year(baseline) == "2021"
    assert resolve_start_year(baseline, "2021") == "2021"
    with pytest.raises(ValueError):
        resolve_start_year(baseline, "2020")
