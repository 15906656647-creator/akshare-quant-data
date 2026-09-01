from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

import akshare_data_test.stage18_2_collect as collector
from akshare_data_test.adapters.stage18_valuation import AttemptEvidence, ValuationCall
from akshare_data_test.stage18_2_collect import build_collection_plan, run_stage18_2_collection
from akshare_data_test.stage18_2_config import load_stage18_2_config
from akshare_data_test.stage18_audit import Security, Stage18Blocked


ROOT = Path(__file__).resolve().parents[1]
STAGE17_RUN = "4a5599fb-9e60-4013-9c0c-69fcc25a98b2"
STAGE181_RUN = "4915ea1b-2e00-4a34-a743-d35dfcb66fe2"


def _securities() -> list[Security]:
    a_symbols = [
        "002067", "002600", "002230", "600763", "603259", "603799",
        "601012", "600438", "002361", "601500", "600231", "300274",
        "601636", "002129", "000100", "300433",
    ]
    h_symbols = [
        "02180.HK", "08365.HK", "08462.HK", "02076.HK", "06100.HK",
        "06919.HK", "09669.HK",
    ]
    return [
        Security(
            symbol, market, "HKEX" if market == "HK" else ("SH" if symbol.startswith("6") else "SZ"),
            date(2010, 1, 1), "profile.json",
        )
        for market, symbols in (("A", a_symbols), ("HK", h_symbols))
        for symbol in symbols
    ]


class FakeAdapter:
    akshare_version = "test"

    def __init__(self, *, empty_interface: str = "") -> None:
        self.calls = []
        self.empty_interface = empty_interface

    def inspect_function(self, _name):
        return True, "(**kwargs)", "fake", "fake.py"

    def call(self, name, parameters, **_kwargs):
        self.calls.append((name, parameters))
        if name == self.empty_interface:
            frame = pd.DataFrame()
            status, error_type, message = "empty", "empty_result", "Returned empty DataFrame"
        elif name == "stock_financial_abstract":
            frame = pd.DataFrame({"指标": ["营业收入"], "2025-06-30": [1.0]})
            status, error_type, message = "success", "", ""
        elif name == "stock_zh_valuation_comparison_em":
            frame = pd.DataFrame({"市盈率TTM": [10.0], "市净率": [1.2]})
            status, error_type, message = "success", "", ""
        elif name == "stock_zh_scale_comparison_em":
            frame = pd.DataFrame({"总市值": [100.0], "流通市值": [80.0]})
            status, error_type, message = "success", "", ""
        elif name == "stock_hk_financial_indicator_em":
            frame = pd.DataFrame({
                "报告日期": ["2025-06-30"], "市盈率": [9.0],
                "市净率": [1.1], "总市值(港元)": [90.0],
            })
            status, error_type, message = "success", "", ""
        else:
            frame = pd.DataFrame({
                "REPORT_DATE": ["2025-06-30"],
                "NOTICE_DATE": ["2025-08-01"], "UPDATE_DATE": ["2025-08-02"],
                "VALUE": [1.0],
            })
            if name in {
                "stock_balance_sheet_by_report_em",
                "stock_profit_sheet_by_report_em",
                "stock_cash_flow_sheet_by_report_em",
            }:
                em_symbol = parameters["symbol"]
                frame.insert(0, "SECUCODE", em_symbol[2:] + "." + em_symbol[:2])
            status, error_type, message = "success", "", ""
        attempt = AttemptEvidence(
            1, "2026-08-27T00:00:00+00:00", "2026-08-27T00:00:01+00:00",
            1.0, status, error_type, message,
        )
        return ValuationCall(frame, status, error_type, message, (attempt,))


def _fixture(tmp_path: Path, monkeypatch, *, bad_upstream: bool = False) -> Path:
    for relative in (
        "config/universe.yml", "config/metric_definition.yml", "docs/stage0_scope.md",
        "config/stage18.yml", "config/stage18_2.yml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    monkeypatch.setattr(collector, "validate_upstream", lambda *_args: _securities())
    monkeypatch.setattr(collector, "_stage17_fingerprint", lambda *_args: {"tree": "stage17"})
    if bad_upstream:
        monkeypatch.setattr(
            collector, "_stage181_fingerprint",
            lambda *_args: (_ for _ in ()).throw(Stage18Blocked("Stage 18.1 PASS differs")),
        )
    else:
        monkeypatch.setattr(collector, "_stage181_fingerprint", lambda *_args: {"tree": "stage181"})
    return tmp_path / "config/stage18_2.yml"


def test_plan_is_closed_deterministic_and_preserves_variants(tmp_path, monkeypatch):
    config_path = _fixture(tmp_path, monkeypatch)
    config = load_stage18_2_config(config_path)
    first = build_collection_plan(_securities(), config)
    second = build_collection_plan(list(reversed(_securities())), config)
    assert first == second
    assert len(first) == len({item.dataset_id for item in first}) == 175
    assert sum(item.market == "A" for item in first) == 112
    assert sum(item.market == "HK" for item in first) == 63
    assert {item.variant for item in first if item.market == "HK"} >= {"annual", "report_period"}


def test_full_formal_raw_collection_isolated_and_closed(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    adapter = FakeAdapter()
    run_id = "44444444-4444-4444-8444-444444444444"
    clock = lambda: datetime(2026, 8, 27, 3, 0, tzinfo=timezone.utc)
    result, code = run_stage18_2_collection(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        upstream_run_id=STAGE181_RUN, run_id=run_id, adapter=adapter, clock=clock,
    )
    assert code == 0 and result["status"] == "PASS"
    assert result["status_counts"] == {"PASS": 175}
    assert result["stage18_3_authorized"] is True
    assert result["stage18_3_started"] is False
    assert len(adapter.calls) == 175
    report_dir = tmp_path / "reports/stage18" / run_id
    assert len(pd.read_csv(report_dir / "fundamental_collection_plan.csv")) == 175
    coverage = pd.read_csv(report_dir / "fundamental_coverage.csv")
    assert len(coverage) == 23
    manifest = json.loads((report_dir / "stage18_2_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["collection_plan_rows"]) == len(manifest["result_rows"]) == 175
    raw_files = [path for path in (tmp_path / "data/raw/stage18").rglob("*") if path.is_file()]
    assert len(raw_files) == 350
    metadata_paths = [path for path in raw_files if path.name == "metadata.json"]
    assert len(metadata_paths) == 175
    for path in metadata_paths:
        item = json.loads(path.read_text(encoding="utf-8"))
        assert item["asset_role"] == "fundamental_raw"
        assert item["audit_only"] is False
        if item["expected_temporality"] == "snapshot":
            assert item["snapshot_time"]
            assert item["eligible_for_as_of_date_analysis"] is False
    assert not (tmp_path / "database/stage18").exists()
    assert not (tmp_path / "data/clean/stage18").exists()
    assert not (tmp_path / "data/features/stage18").exists()


def test_unexplained_empty_is_fail_and_blocks_exit(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)
    adapter = FakeAdapter(empty_interface="stock_financial_abstract")
    result, code = run_stage18_2_collection(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        run_id="55555555-5555-4555-8555-555555555555", adapter=adapter,
    )
    assert code == 2 and result["status"] == "BLOCKED"
    assert result["status_counts"]["FAIL"] == 16
    raw_root = tmp_path / "data/raw/stage18/financial_abstract"
    assert not list(raw_root.rglob("data.parquet"))
    assert len(list(raw_root.rglob("metadata.json"))) == 16


def test_semantic_identity_failure_writes_metadata_only(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch)

    class MismatchAdapter(FakeAdapter):
        def call(self, name, parameters, **kwargs):
            result = super().call(name, parameters, **kwargs)
            if name == "stock_balance_sheet_by_report_em":
                frame = result.dataframe.copy()
                frame["SECUCODE"] = "999999.SZ"
                return ValuationCall(
                    frame, result.status, result.error_type,
                    result.error_message, result.attempts,
                )
            return result

    run_id = "77777777-7777-4777-8777-777777777777"
    result, code = run_stage18_2_collection(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        run_id=run_id, adapter=MismatchAdapter(),
    )
    assert code == 2 and result["status_counts"]["FAIL"] == 16
    raw_root = tmp_path / "data/raw/stage18/balance_sheet" / f"run_id={run_id}"
    a_market = raw_root / "market=A"
    assert not list(a_market.rglob("data.parquet"))
    assert len(list(a_market.rglob("metadata.json"))) == 16


def test_bad_stage181_authorization_blocks_before_network(tmp_path, monkeypatch):
    config = _fixture(tmp_path, monkeypatch, bad_upstream=True)
    adapter = FakeAdapter()
    with pytest.raises(Stage18Blocked, match="Stage 18.1 PASS"):
        run_stage18_2_collection(
            root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
            adapter=adapter,
        )
    assert adapter.calls == []


def test_config_rejects_snapshot_baseline_eligibility(tmp_path):
    payload = yaml.safe_load((ROOT / "config/stage18_2.yml").read_text(encoding="utf-8"))
    payload["analysis"]["eligible_for_as_of_date_analysis"] = True
    path = tmp_path / "stage18_2.yml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    with pytest.raises(Exception, match="baseline-eligible"):
        load_stage18_2_config(path)
