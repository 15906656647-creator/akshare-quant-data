import pandas as pd

from akshare_data_test.stage17_collect import extract_listing_date


def test_hk_descriptive_text_never_becomes_listing_date():
    frame = pd.DataFrame({
        "证券代码": ["02180"],
        "上市板块": ["主板"],
        "公司介绍": ["公司于2014-09-26成立，后来在香港上市。"],
    })
    assert extract_listing_date(frame) is None


def test_row_oriented_explicit_listing_label_still_supported():
    frame = pd.DataFrame({"项目": ["上市日期"], "值": ["2019-07-10"]})
    assert extract_listing_date(frame).isoformat() == "2019-07-10"
