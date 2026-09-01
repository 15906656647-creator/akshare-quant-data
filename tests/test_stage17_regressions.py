from datetime import date

import pandas as pd

from akshare_data_test.stage17_collect import extract_listing_date, validate_equity_daily


def test_cninfo_listing_date_is_read_from_labelled_column():
    frame = pd.DataFrame({"公司名称": ["示例"], "上市日期": ["2006-09-15"]})
    assert extract_listing_date(frame) == date(2006, 9, 15)


def test_negative_adjusted_prices_do_not_fail_when_ohlc_is_consistent():
    frame = pd.DataFrame({
        "日期": ["2006-09-15"], "开盘": [-2.0], "最高": [-1.0],
        "最低": [-3.0], "收盘": [-1.5], "成交量": [100], "成交额": [1000],
    })
    assert validate_equity_daily(frame)["status"] == "PASS"


def test_real_ohlc_inconsistency_remains_blocking():
    frame = pd.DataFrame({
        "日期": ["2023-01-06"], "开盘": [92.0], "最高": [91.95],
        "最低": [89.3], "收盘": [89.45], "成交量": [11100], "成交额": [1],
    })
    result = validate_equity_daily(frame)
    assert result["status"] == "FAIL"
    assert "ohlc_logic_error" in result["errors"]
