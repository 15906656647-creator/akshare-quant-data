from datetime import date, datetime, timezone

import pandas as pd

from akshare_data_test.adapters.stock_finance import (
    FinancialCall,
    call_with_retry,
)
from akshare_data_test.collectors.financial_collector import FinancialCollector
from akshare_data_test.config import load_universe
from akshare_data_test.storage.raw_store import RawStore


class FakeFinance:
    akshare_version = "test"

    def __init__(self):
        self.calls = []

    def _ok(self, name, *args):
        self.calls.append((name, args))
        return FinancialCall(
            pd.DataFrame({
                "报告期": ["2025-12-31"],
                "公告日期": ["2026-03-01"],
                "营业收入": [1],
                "净利润": [2],
                "全空列": [None],
            }),
            1,
            "success",
        )

    def fetch_financial_abstract(self, *args, **kwargs):
        return self._ok("financial_abstract", *args)

    def fetch_financial_indicator(self, *args, **kwargs):
        return self._ok("financial_indicator", *args)

    def fetch_balance_sheet(self, *args, **kwargs):
        return self._ok("balance_sheet", *args)

    def fetch_profit_sheet(self, *args, **kwargs):
        return self._ok("profit_sheet", *args)

    def fetch_cashflow_sheet(self, *args, **kwargs):
        return self._ok("cashflow_sheet", *args)


class FakeFund(FakeFinance):
    def fetch_individual_fund_flow(self, *args, **kwargs):
        return self._ok("fund_flow", *args)


def _collector(tmp_path, finance=None, fund=None):
    return FinancialCollector(
        finance_adapter=finance or FakeFinance(),
        fund_flow_adapter=fund or FakeFund(),
        store=RawStore(tmp_path / "data/raw"),
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root=tmp_path,
    )


def test_all_interface_parameter_formats_and_wide_raw_preserved(tmp_path):
    finance, fund = FakeFinance(), FakeFund()
    collector = _collector(tmp_path, finance, fund)
    stock = next(x for x in load_universe().stocks if x.symbol == "600763")
    mapping = {
        "financial_abstract": "stock_financial_abstract",
        "financial_indicator": "stock_financial_analysis_indicator",
        "balance_sheet_report": "stock_balance_sheet_by_report_em",
        "profit_sheet_report": "stock_profit_sheet_by_report_em",
        "cashflow_sheet_report": "stock_cash_flow_sheet_by_report_em",
        "individual_fund_flow": "stock_individual_fund_flow",
    }
    records = []
    for interface_id, interface_name in mapping.items():
        record, _ = collector.collect(
            run_id="11111111-1111-4111-8111-111111111111",
            interface_id=interface_id,
            interface_name=interface_name,
            stock=stock,
            as_of_date=date(2026, 7, 27),
            start_year="2021",
        )
        records.append(record)
    assert finance.calls == [
        ("financial_abstract", ("600763",)),
        ("financial_indicator", ("600763", "2021")),
        ("balance_sheet", ("SH600763",)),
        ("profit_sheet", ("SH600763",)),
        ("cashflow_sheet", ("SH600763",)),
    ]
    assert fund.calls == [("fund_flow", ("600763", "sh"))]
    raw = pd.read_parquet(tmp_path / records[0].raw_path)
    assert list(raw.columns) == ["报告期", "公告日期", "营业收入", "净利润", "全空列"]
    assert raw["全空列"].isna().all()


def test_empty_is_not_success_and_independent_tasks_can_continue(tmp_path):
    finance = FakeFinance()
    finance.fetch_financial_abstract = lambda *_, **__: FinancialCall(
        pd.DataFrame(), 1, "empty", "empty_result", "Returned empty DataFrame"
    )
    collector = _collector(tmp_path, finance, FakeFund())
    stock = load_universe().stocks[0]
    failed, _ = collector.collect(
        run_id="11111111-1111-4111-8111-111111111111",
        interface_id="financial_abstract",
        interface_name="stock_financial_abstract",
        stock=stock, as_of_date=date(2026, 7, 27), start_year="2021",
    )
    succeeded, _ = collector.collect(
        run_id="11111111-1111-4111-8111-111111111111",
        interface_id="profit_sheet_report",
        interface_name="stock_profit_sheet_by_report_em",
        stock=stock, as_of_date=date(2026, 7, 27), start_year="2021",
    )
    assert failed.status == "empty"
    assert not failed.raw_path
    assert succeeded.status == "success"


def test_retry_policy_is_bounded_and_deterministic_errors_do_not_retry():
    count = 0

    def transient(**_):
        nonlocal count
        count += 1
        raise ConnectionError("temporary")

    result = call_with_retry(transient, {}, max_attempts=10, retry_delay_seconds=0)
    assert result.attempt_count == 3
    assert count == 3

    count = 0

    def invalid(**_):
        nonlocal count
        count += 1
        raise TypeError("invalid argument")

    result = call_with_retry(invalid, {}, retry_delay_seconds=0)
    assert result.error_type == "invalid_parameter"
    assert count == 1
