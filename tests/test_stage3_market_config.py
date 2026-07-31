from datetime import date

from akshare_data_test.config import load_metrics, load_universe
from akshare_data_test.market_fetch import historical_start_date


def test_stage3_universe_is_frozen_and_string_typed():
    universe = load_universe()
    assert len(universe.stocks) == 16
    assert len({item.symbol for item in universe.stocks}) == 16
    assert all(isinstance(item.symbol, str) and len(item.symbol) == 6 for item in universe.stocks)
    assert universe.crypto[0].requested_pair == "ETHUSDT"


def test_stage3_builds_32_history_tasks():
    assert len(load_universe().stocks) * 2 == 32


def test_history_window_uses_three_calendar_years():
    metrics = load_metrics()
    years = metrics.raw["data_ranges"]["stock_daily"]["default_years"]
    assert years == 3
    assert historical_start_date(date(2026, 7, 27), years) == date(2023, 7, 27)


def test_history_window_handles_leap_day():
    assert historical_start_date(date(2024, 2, 29), 1) == date(2023, 2, 28)
