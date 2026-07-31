import csv
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import pytest

from akshare_data_test import cli, financial_fetch
from akshare_data_test.adapters.stock_finance import FinancialCall


class FullAdapter:
    akshare_version = "test"

    def _financial(self, *args, **kwargs):
        return FinancialCall(pd.DataFrame({
            "报告期": ["2025-12-31"], "公告日期": ["2026-03-01"],
            "营业收入": [1], "净利润": [2], "资产总计": [3],
            "负债合计": [1], "经营活动产生的现金流量净额": [1],
        }), 1, "success")

    fetch_financial_abstract = _financial
    fetch_financial_indicator = _financial
    fetch_balance_sheet = _financial
    fetch_profit_sheet = _financial
    fetch_cashflow_sheet = _financial


class FullFund(FullAdapter):
    def fetch_individual_fund_flow(self, *args, **kwargs):
        return FinancialCall(pd.DataFrame({
            "日期": ["2026-07-25", "2026-07-27"], "主力净流入": [1, 2]
        }), 1, "success")


def test_full_offline_orchestration_creates_96_coverage_and_manifest(
    tmp_path, monkeypatch
):
    import socket

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("real network is forbidden in default tests")
        ),
    )
    report, code = financial_fetch.run_financial_fetch(
        as_of_date=financial_fetch.date(2026, 7, 27),
        start_year="2021", output_dir="data/raw",
        evidence_dir="reports/evidence/stage4",
        run_id="11111111-1111-4111-8111-111111111111",
        finance_adapter=FullAdapter(), fund_flow_adapter=FullFund(),
        inter_task_delay_seconds=0,
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root_override=tmp_path,
    )
    assert code == 0
    assert report["success_count"] == 96
    coverage = list(csv.DictReader(
        (tmp_path / "reports/stage4_financial_coverage.csv").open(
            encoding="utf-8-sig"
        )
    ))
    assert len(coverage) == 96
    assert len({(row["symbol"], row["interface_id"]) for row in coverage}) == 96
    manifest = json.loads((tmp_path / report["manifest_path"]).read_text())
    assert manifest["raw_file_count"] == 96
    assert len(manifest["raw_files"]) == 96
    assert not (tmp_path / "data/clean").exists()
    assert not (tmp_path / "data/feature").exists()
    assert not (tmp_path / "database").exists()


def test_fetch_fundamentals_cli_options(monkeypatch, capsys):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return ({
            "status": "PASS", "run_id": "x", "success_count": 1,
            "expected_task_count": 1, "manifest_path": "manifest.json",
        }, 0)

    monkeypatch.setattr(financial_fetch, "run_financial_fetch", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "run_pipeline.py", "fetch-fundamentals",
        "--as-of-date", "2026-07-27", "--start-year", "2021",
        "--run-id", "11111111-1111-4111-8111-111111111111",
        "--only-symbol", "002067", "--only-interface", "financial_abstract",
        "--resume",
    ])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert captured["start_year"] == "2021"
    assert captured["resume"] is True
    assert "Financial fetch: PASS" in capsys.readouterr().out


def test_resume_reuses_success_raw_and_retries_only_missing(tmp_path):
    run_id = "11111111-1111-4111-8111-111111111111"
    adapter = FullAdapter()
    fund = FullFund()
    first, code = financial_fetch.run_financial_fetch(
        as_of_date=financial_fetch.date(2026, 7, 27),
        start_year="2021", run_id=run_id, only_symbol="002067",
        only_interface="financial_abstract", output_dir="data/raw",
        evidence_dir="reports/evidence/stage4", finance_adapter=adapter,
        fund_flow_adapter=fund, inter_task_delay_seconds=0,
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root_override=tmp_path,
    )
    assert code == 0 and first["success_count"] == 1

    class MustNotCall(FullAdapter):
        def fetch_financial_abstract(self, *args, **kwargs):
            raise AssertionError("successful Raw must be reused")

    resumed, code = financial_fetch.run_financial_fetch(
        as_of_date=financial_fetch.date(2026, 7, 27),
        start_year="2021", run_id=run_id, only_symbol="002067",
        only_interface="financial_abstract", resume=True, output_dir="data/raw",
        evidence_dir="reports/evidence/stage4", finance_adapter=MustNotCall(),
        fund_flow_adapter=fund, inter_task_delay_seconds=0,
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root_override=tmp_path,
    )
    assert code == 0 and resumed["success_count"] == 1
    evidence = tmp_path / "reports/evidence/stage4" / run_id
    assert (evidence / "initial_failure_coverage.csv").exists()
