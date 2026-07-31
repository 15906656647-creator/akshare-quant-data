import csv
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test import cli, financial_fetch
from akshare_data_test.adapters.stock_finance import (
    FinancialCall,
    OutputCapture,
    call_with_retry,
)
from akshare_data_test.collectors.financial_collector import FinancialCollector
from akshare_data_test.config import load_universe
from akshare_data_test.storage.raw_store import RawStore
from akshare_data_test.logging_config import SafeConsoleHandler


class ClosedConsole:
    def write(self, _value):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")


def capture(tmp_path):
    return OutputCapture(
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
        stdout_log_path="logs/upstream/stage4/r/s_i.stdout.log",
        stderr_log_path="logs/upstream/stage4/r/s_i.stderr.log",
    )


def test_closed_stdout_and_stderr_are_isolated_to_utf8_task_logs(
    tmp_path, monkeypatch
):
    def upstream(**_):
        print("标准输出：成功")
        print("进度输出：成功", file=sys.stderr)
        return pd.DataFrame({"值": [1]})

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", ClosedConsole())
        patch.setattr(sys, "stderr", ClosedConsole())
        result = call_with_retry(
            upstream, {}, output_capture=capture(tmp_path),
            retry_delay_seconds=0,
        )
    assert result.status == "success"
    assert result.output_capture_status == "success"
    assert "标准输出：成功" in (tmp_path / "out.log").read_text(encoding="utf-8")
    assert "进度输出：成功" in (tmp_path / "err.log").read_text(encoding="utf-8")
    assert result.stdout_log_path == "logs/upstream/stage4/r/s_i.stdout.log"
    assert not Path(result.stdout_log_path).is_absolute()


def test_real_upstream_errno22_is_not_suppressed(tmp_path):
    def upstream(**_):
        raise OSError(22, "upstream failure")

    result = call_with_retry(
        upstream, {}, output_capture=capture(tmp_path),
        retry_delay_seconds=0,
    )
    assert result.status == "failed"
    assert result.attempt_count == 1
    assert "Invalid argument" in result.error_message or "upstream failure" in result.error_message


def test_task_log_write_failure_warns_but_keeps_dataframe(tmp_path, monkeypatch):
    class BrokenLog:
        def write(self, _value):
            raise OSError(22, "log unavailable")

        def flush(self):
            raise OSError(22, "log unavailable")

        def close(self):
            pass

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: BrokenLog())

    def upstream(**_):
        print("tqdm-like output")
        return pd.DataFrame({"值": [1]})

    result = call_with_retry(
        upstream, {}, output_capture=capture(tmp_path),
        retry_delay_seconds=0,
    )
    assert result.status == "success"
    assert result.output_capture_status == "console_output_warning"


def test_safe_console_print_marks_warning_instead_of_raising(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", ClosedConsole())
        assert cli._safe_console_print("ignored") is False


def test_logging_console_handler_tolerates_closed_pipe():
    handler = SafeConsoleHandler(ClosedConsole())
    logger = logging.getLogger("stage4-output-isolation-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("must not raise")


class GoodAdapter:
    akshare_version = "test"

    def _ok(self, *args, **kwargs):
        return FinancialCall(
            pd.DataFrame({
                "报告期": ["2025-12-31"], "公告日期": ["2026-03-01"],
                "营业收入": [1], "净利润": [1],
            }),
            1,
            "success",
            output_capture_status="success",
            stdout_log_path=kwargs["output_capture"].stdout_log_path,
            stderr_log_path=kwargs["output_capture"].stderr_log_path,
        )

    fetch_financial_abstract = _ok
    fetch_financial_indicator = _ok
    fetch_balance_sheet = _ok
    fetch_profit_sheet = _ok
    fetch_cashflow_sheet = _ok


class GoodFund(GoodAdapter):
    fetch_individual_fund_flow = GoodAdapter._ok


def test_raw_write_failure_is_distinct_from_upstream_failure(tmp_path, monkeypatch):
    collector = FinancialCollector(
        finance_adapter=GoodAdapter(),
        fund_flow_adapter=GoodFund(),
        store=RawStore(tmp_path / "data/raw"),
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root=tmp_path,
    )
    monkeypatch.setattr(
        collector.store, "write_parquet",
        lambda *_: (_ for _ in ()).throw(OSError("disk full")),
    )
    record, frame = collector.collect(
        run_id="11111111-1111-4111-8111-111111111111",
        interface_id="financial_abstract",
        interface_name="stock_financial_abstract",
        stock=load_universe().stocks[0],
        as_of_date=date(2026, 7, 27),
        start_year="2021",
    )
    assert frame is not None
    assert record.upstream_call_status == "success"
    assert record.raw_write_status == "failed"
    assert record.error_type == "raw_write_error"


FAILED_TASKS = {
    ("000100", "financial_indicator"),
    ("000100", "balance_sheet_report"),
    ("000100", "profit_sheet_report"),
    ("000100", "cashflow_sheet_report"),
    ("002129", "financial_indicator"),
    ("002129", "balance_sheet_report"),
    ("002129", "profit_sheet_report"),
    ("002129", "cashflow_sheet_report"),
    ("300433", "financial_indicator"),
    ("300433", "balance_sheet_report"),
    ("300433", "profit_sheet_report"),
    ("300433", "cashflow_sheet_report"),
    ("601636", "cashflow_sheet_report"),
}


class SelectiveAdapter(GoodAdapter):
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def _result(self, interface_id, symbol, **kwargs):
        plain = symbol[-6:]
        self.calls.append((plain, interface_id))
        if self.fail and (plain, interface_id) in FAILED_TASKS:
            return FinancialCall(
                None, 1, "failed", "unknown_error", "[Errno 22] Invalid argument",
                output_capture_status="success",
                stdout_log_path=kwargs["output_capture"].stdout_log_path,
                stderr_log_path=kwargs["output_capture"].stderr_log_path,
            )
        return super()._ok(output_capture=kwargs["output_capture"])

    def fetch_financial_abstract(self, symbol, **kwargs):
        return self._result("financial_abstract", symbol, **kwargs)

    def fetch_financial_indicator(self, symbol, _year, **kwargs):
        return self._result("financial_indicator", symbol, **kwargs)

    def fetch_balance_sheet(self, symbol, **kwargs):
        return self._result("balance_sheet_report", symbol, **kwargs)

    def fetch_profit_sheet(self, symbol, **kwargs):
        return self._result("profit_sheet_report", symbol, **kwargs)

    def fetch_cashflow_sheet(self, symbol, **kwargs):
        return self._result("cashflow_sheet_report", symbol, **kwargs)


class SelectiveFund(SelectiveAdapter):
    def fetch_individual_fund_flow(self, symbol, _market, **kwargs):
        return self._result("individual_fund_flow", symbol, **kwargs)


def test_resume_selects_exact_13_preserves_83_and_finishes_96(tmp_path):
    run_id = "11111111-1111-4111-8111-111111111111"
    first_adapter = SelectiveAdapter(fail=True)
    first_fund = SelectiveFund(fail=True)
    report, code = financial_fetch.run_financial_fetch(
        as_of_date=date(2026, 7, 27), start_year="2021", run_id=run_id,
        output_dir="data/raw", evidence_dir="reports/evidence/stage4",
        finance_adapter=first_adapter, fund_flow_adapter=first_fund,
        inter_task_delay_seconds=0,
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root_override=tmp_path,
    )
    assert code == 1
    assert (report["success_count"], report["failed_count"]) == (83, 13)
    existing = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / "data/raw").rglob("data.parquet")
    }

    repaired_adapter = SelectiveAdapter()
    repaired_fund = SelectiveFund()
    report, code = financial_fetch.run_financial_fetch(
        as_of_date=date(2026, 7, 27), start_year="2021", run_id=run_id,
        output_dir="data/raw", evidence_dir="reports/evidence/stage4",
        resume=True, finance_adapter=repaired_adapter,
        fund_flow_adapter=repaired_fund, inter_task_delay_seconds=0,
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root_override=tmp_path,
    )
    calls = set(repaired_adapter.calls + repaired_fund.calls)
    assert calls == FAILED_TASKS
    assert code == 0
    assert (report["success_count"], report["failed_count"]) == (96, 0)
    for relative, content in existing.items():
        assert (tmp_path / relative).read_bytes() == content
    coverage = list(csv.DictReader(
        (tmp_path / "reports/stage4_financial_coverage.csv").open(
            encoding="utf-8-sig"
        )
    ))
    assert len(coverage) == 96
    assert len({(row["symbol"], row["interface_id"]) for row in coverage}) == 96
    manifest = json.loads(
        (tmp_path / report["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["raw_file_count"] == 96
    evidence = tmp_path / "reports/evidence/stage4" / run_id
    for name in (
        "initial_failure_coverage.csv",
        "initial_failure_run.json",
        "initial_failure_manifest.json",
        "manifest.before_repair.json",
    ):
        assert (evidence / name).exists()


def test_closed_console_does_not_block_reports_or_manifest(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", ClosedConsole())
        patch.setattr(sys, "stderr", ClosedConsole())
        report, code = financial_fetch.run_financial_fetch(
            as_of_date=date(2026, 7, 27), start_year="2021",
            run_id="11111111-1111-4111-8111-111111111111",
            only_symbol="002067", only_interface="financial_abstract",
            output_dir="data/raw", evidence_dir="reports/evidence/stage4",
            finance_adapter=GoodAdapter(), fund_flow_adapter=GoodFund(),
            inter_task_delay_seconds=0,
            now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
            project_root_override=tmp_path,
        )
    assert code == 0
    assert (tmp_path / "reports/stage4_financial_coverage.csv").exists()
    assert (tmp_path / report["manifest_path"]).exists()


def test_evidence_write_failure_does_not_masquerade_as_upstream_failure(
    tmp_path, monkeypatch
):
    real_write_csv = financial_fetch._write_csv

    def fail_coverage(path, rows, columns):
        if str(path).endswith("stage4_financial_coverage.csv"):
            raise OSError("evidence disk failure")
        return real_write_csv(path, rows, columns)

    monkeypatch.setattr(financial_fetch, "_write_csv", fail_coverage)
    with pytest.raises(OSError, match="evidence disk failure"):
        financial_fetch.run_financial_fetch(
            as_of_date=date(2026, 7, 27), start_year="2021",
            run_id="11111111-1111-4111-8111-111111111111",
            only_symbol="002067", only_interface="financial_abstract",
            output_dir="data/raw", evidence_dir="reports/evidence/stage4",
            finance_adapter=GoodAdapter(), fund_flow_adapter=GoodFund(),
            inter_task_delay_seconds=0,
            now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
            project_root_override=tmp_path,
        )
    raw_files = list((tmp_path / "data/raw").rglob("data.parquet"))
    assert len(raw_files) == 1
    assert pd.read_parquet(raw_files[0]).shape[0] == 1
