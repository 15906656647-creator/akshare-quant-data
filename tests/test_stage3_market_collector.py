from datetime import date, datetime, timezone
import pandas as pd

from akshare_data_test.adapters.stock_market import MarketCall, _call_with_retry
from akshare_data_test.collectors.market_collector import MarketCollector, validate_history
from akshare_data_test.config import load_universe
from akshare_data_test.market_fetch import run_market_fetch
from akshare_data_test.storage.raw_store import RawStore


def history_frame():
    return pd.DataFrame(
        {
            "日期": ["2023-07-27", "2026-07-27"],
            "股票代码": ["002067", "002067"],
            "开盘": [10.0, 11.0],
            "收盘": [10.5, 10.8],
            "最高": [10.8, 11.2],
            "最低": [9.9, 10.7],
            "成交量": [100, 110],
            "成交额": [1000, 1200],
        }
    )


class FakeAdapter:
    akshare_version = "test"

    def __init__(self):
        self.history_calls = []
        self.spot_calls = 0

    def fetch_history(self, **kwargs):
        self.history_calls.append(kwargs)
        return MarketCall(history_frame(), 1, "success")

    def fetch_spot(self):
        self.spot_calls += 1
        return MarketCall(
            pd.DataFrame(
                {
                    "代码": ["002067", "600763", "999999"],
                    "名称": ["A", "B", "X"],
                    "最新价": [1.0, 2.0, 3.0],
                }
            ),
            1,
            "success",
        )


def test_history_qfq_and_raw_parameters_and_paths(tmp_path):
    adapter = FakeAdapter()
    collector = MarketCollector(
        adapter=adapter,
        store=RawStore(tmp_path / "data/raw"),
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root=tmp_path,
    )
    for adjust in ("qfq", ""):
        result = collector.collect_history(
            run_id="11111111-1111-4111-8111-111111111111",
            symbol="002067",
            exchange="SZ",
            adjust=adjust,
            start_date=date(2023, 7, 27),
            as_of_date=date(2026, 7, 27),
        )
        assert result.status == "success"
        assert result.quality_status == "PASS"
        assert result.request_parameters["period"] == "daily"
        assert result.request_parameters["adjust"] == adjust
    assert [item["adjust"] for item in adapter.history_calls] == ["qfq", ""]
    paths = list((tmp_path / "data/raw/stock_zh_a_hist").rglob("data.parquet"))
    assert any("adjust=qfq" in path.as_posix() for path in paths)
    assert any("adjust=raw" in path.as_posix() for path in paths)


def test_spot_is_called_once_and_filtered_in_memory(tmp_path):
    adapter = FakeAdapter()
    collector = MarketCollector(
        adapter=adapter,
        store=RawStore(tmp_path / "data/raw"),
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root=tmp_path,
    )
    records, summary, _ = collector.collect_spot(
        run_id="11111111-1111-4111-8111-111111111111",
        target_symbols=["002067", "600763"],
        as_of_date=date(2026, 7, 27),
    )
    assert adapter.spot_calls == 1
    assert summary["target_count"] == 2
    assert summary["missing_symbols"] == []
    assert len(records) == 3
    assert records[0].snapshot_at != records[0].as_of_date


def test_quality_detects_future_duplicate_and_bad_ohlc():
    frame = history_frame()
    frame.loc[1, "日期"] = "2026-07-28"
    frame.loc[0, "最高"] = 1
    status, issues, _, _ = validate_history(
        frame, start_date=date(2023, 7, 27), as_of_date=date(2026, 7, 27)
    )
    assert status == "ERROR"
    assert "date_later_than_as_of_date" in issues
    assert "high_below_open_or_close" in issues

    duplicate = history_frame()
    duplicate.loc[1, "日期"] = duplicate.loc[0, "日期"]
    assert "duplicate_date" in validate_history(
        duplicate, start_date=date(2023, 7, 27), as_of_date=date(2026, 7, 27)
    )[1]


def test_non_trading_start_boundary_is_not_a_coverage_error():
    frame = history_frame()
    frame.loc[0, "日期"] = "2025-07-28"
    status, issues, _, _ = validate_history(
        frame, start_date=date(2025, 7, 27), as_of_date=date(2026, 7, 27)
    )
    assert status != "ERROR"
    assert "historical_window_not_covered" not in issues


def test_empty_dataframe_is_not_success():
    call = _call_with_retry(
        lambda: pd.DataFrame(),
        parameters={},
        max_attempts=3,
        retry_delay_seconds=0,
    )
    assert call.status == "empty"
    assert call.attempt_count == 1


def test_parameter_error_is_not_retried():
    calls = 0

    def bad():
        nonlocal calls
        calls += 1
        raise TypeError("bad argument")

    result = _call_with_retry(
        bad, parameters={}, max_attempts=3, retry_delay_seconds=0
    )
    assert result.status == "failed"
    assert result.error_type == "parameter_error"
    assert calls == 1


def test_transient_error_has_bounded_retry():
    calls = 0

    def bad():
        nonlocal calls
        calls += 1
        raise ConnectionError("temporary")

    result = _call_with_retry(
        bad, parameters={}, max_attempts=10, retry_delay_seconds=0
    )
    assert result.status == "failed"
    assert result.attempt_count == 3
    assert calls == 3


def test_full_orchestration_writes_parseable_reports_and_manifest(tmp_path):
    class FullAdapter(FakeAdapter):
        def fetch_spot(self):
            self.spot_calls += 1
            symbols = [item.symbol for item in load_universe().stocks]
            return MarketCall(
                pd.DataFrame(
                    {
                        "代码": symbols,
                        "名称": [f"S{i}" for i in range(16)],
                        "最新价": [float(i + 1) for i in range(16)],
                    }
                ),
                1,
                "success",
            )

    adapter = FullAdapter()
    report, exit_code = run_market_fetch(
        as_of_date=date(2026, 7, 27),
        output_dir="data/raw",
        evidence_dir="reports/evidence/stage3",
        run_id="11111111-1111-4111-8111-111111111111",
        adapter=adapter,
        inter_symbol_delay_seconds=0,
        now=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        project_root_override=tmp_path,
    )
    assert exit_code == 0
    assert report["daily_success_count"] == 32
    assert len(adapter.history_calls) == 32
    assert adapter.spot_calls == 1
    assert report["spot"]["target_count"] == 16
    import csv
    import json

    coverage = list(
        csv.DictReader(
            (tmp_path / "reports/stage3_market_coverage.csv").open(
                encoding="utf-8-sig"
            )
        )
    )
    assert len(coverage) == 49
    manifest = json.loads(
        (tmp_path / report["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["daily_success_count"] == 32
    assert len(manifest["raw_files"]) == 34
