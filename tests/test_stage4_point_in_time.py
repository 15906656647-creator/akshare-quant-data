import json
from datetime import date

import pandas as pd

from akshare_data_test.collectors.financial_collector import (
    FinancialRecord,
    core_field_rows,
)
from akshare_data_test.financial_fetch import _point_rows


def _record():
    return FinancialRecord(
        run_id="r", dataset_id="d", interface_id="financial_abstract",
        interface_name="stock_financial_abstract", symbol="002067",
        exchange="SZ", symbol_plain="002067", symbol_em="SZ002067",
        market_lower="sz", request_parameters="{}", started_at="", finished_at="",
        fetched_at="", as_of_date="2026-07-27", start_year="2021",
        akshare_version="test", python_version="test", status="success",
        row_count=1, column_count=3, columns="[]", dtypes="[]", schema_hash="x",
        detected_report_date_columns=json.dumps(["报告期"]),
        detected_announcement_date_columns=json.dumps(["公告日期"]),
        min_report_date="", max_report_date="", min_announcement_date="",
        max_announcement_date="", raw_path="data/raw/x.parquet", error_type="",
        error_message="", root_exception_class="", target_host="", attempt_count=1,
        quality_status="PASS", warning_count=0, error_count=0, elapsed_seconds=0,
    )


def test_lookahead_is_reported_without_mutating_raw():
    frame = pd.DataFrame({
        "报告期": ["2025-12-31"],
        "公告日期": ["2026-08-01"],
        "营业收入": [1],
    })
    before = frame.copy(deep=True)
    rows = _point_rows(_record(), frame, date(2026, 7, 27))
    assert rows[0]["potential_lookahead"] is True
    pd.testing.assert_frame_equal(frame, before)


def test_field_presence_and_non_null_count_are_separate():
    rows = core_field_rows(
        "r", "002067",
        {"financial_abstract": pd.DataFrame({
            "报告期": ["2025-12-31"], "营业收入": [None], "净利润": [2],
        })}
    )
    revenue = next(row for row in rows if row["concept"] == "营业收入或营业总收入")
    assert revenue["availability_status"] == "field_present_all_null"
    assert revenue["non_null_count"] == 0


def test_transposed_abstract_recognizes_period_headers_and_metric_rows():
    from akshare_data_test.collectors.financial_collector import detect_date_columns

    frame = pd.DataFrame({
        "指标": ["营业收入", "净利润"],
        "2025-12-31": [1, 2],
        "2024-12-31": [3, 4],
    })
    report_columns, announcement_columns = detect_date_columns(frame)
    assert report_columns == ["2025-12-31", "2024-12-31"]
    assert announcement_columns == []
    rows = core_field_rows("r", "002067", {"financial_abstract": frame})
    revenue = next(row for row in rows if row["concept"] == "营业收入或营业总收入")
    assert revenue["availability_status"] == "available_non_null"
    assert revenue["non_null_count"] == 2
