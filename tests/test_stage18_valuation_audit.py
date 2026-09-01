from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from akshare_data_test.adapters.stage18_valuation import AttemptEvidence, ValuationCall
from akshare_data_test.stage18_audit import Stage18Blocked
from akshare_data_test.stage18_valuation_audit import run_stage18_valuation_audit
from akshare_data_test.stage18_valuation_config import load_stage18_valuation_config
from akshare_data_test.storage.raw_store import file_sha256


ROOT = Path(__file__).resolve().parents[1]
STAGE17_RUN = "4a5599fb-9e60-4013-9c0c-69fcc25a98b2"
STAGE1811_RUN = "19660ce0-e73d-4d0c-8451-cfaee0b726da"


class FakeValuationAdapter:
    akshare_version = "1.18.80-test"

    def __init__(self) -> None:
        self.calls = []

    def inspect_function(self, name):
        return True, "(**kwargs)", "fake.module", "fake.py"

    def discover(self, _keywords):
        return [{
            "interface": "stock_zh_a_spot_tx", "signature": "()",
            "module": "fake.module", "source_file": "fake.py",
        }]

    def call(self, name, parameters, **_kwargs):
        self.calls.append((name, tuple(sorted(parameters.items()))))
        if name == "stock_zh_a_spot":
            frame = pd.DataFrame({
                "代码": ["600763", "000100", "603259"],
                "最新价": [1.0, 2.0, 3.0],
            })
        elif name == "stock_zh_a_spot_tx":
            frame = pd.DataFrame({
                "code": ["sh600763", "sz000100", "sh603259"],
                "price": [1.0, 2.0, 3.0], "pe": [10.0, 11.0, 12.0],
            })
        elif name == "stock_zh_valuation_comparison_em":
            frame = pd.DataFrame({
                "代码": [parameters["symbol"][2:]], "市盈率-TTM": [10.0],
                "市净率-MRQ": [1.0],
            })
        elif name == "stock_zh_scale_comparison_em":
            frame = pd.DataFrame({
                "代码": [parameters["symbol"][2:]], "总市值": [100.0],
                "流通市值": [80.0],
            })
        elif name == "stock_hk_financial_indicator_em":
            frame = pd.DataFrame({
                "市盈率": [8.0], "市净率": [1.0], "总市值(港元)": [100.0],
                "港股市值(港元)": [90.0],
            })
        elif name == "stock_hk_indicator_eniu":
            frame = pd.DataFrame({"date": [date(2026, 8, 26)], "pe": [10.0]})
        else:
            frame = pd.DataFrame({"date": [date(2026, 8, 26)], "value": [10.0]})
        attempt = AttemptEvidence(
            1, "2026-08-27T01:00:00+00:00", "2026-08-27T01:00:01+00:00",
            1000.0, "success", "", "",
        )
        return ValuationCall(frame, "success", "", "", (attempt,))


def _build_workspace(tmp_path: Path, *, next_task: str | None = None) -> Path:
    for relative in (
        "config/universe.yml", "config/metric_definition.yml", "docs/stage0_scope.md",
        "config/stage18.yml", "config/stage18_valuation_audit.yml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    stage17_report = tmp_path / "reports/stage17" / STAGE17_RUN
    stage17_report.mkdir(parents=True)
    (stage17_report / "stage17_run.json").write_text(json.dumps({
        "run_id": STAGE17_RUN, "status": "PASS", "stage18_authorized": True,
        "blocked_risks": [], "unavailable_items": [],
        "counts": {"daily_quality_pass_count": 69},
    }), encoding="utf-8")
    a_symbols = [
        "002067", "002600", "002230", "600763", "603259", "603799",
        "601012", "600438", "002361", "601500", "600231", "300274",
        "601636", "002129", "000100", "300433",
    ]
    h_symbols = ["02180.HK", "08365.HK", "08462.HK", "02076.HK", "06100.HK", "06919.HK", "09669.HK"]
    listing = {
        "600763": "1996-10-30", "000100": "2004-01-30", "603259": "2018-05-08",
        "08365.HK": "2017-05-26", "09669.HK": "2023-04-13",
    }
    coverage = []
    for market, symbols in (("A", a_symbols), ("HK", h_symbols)):
        for index, symbol in enumerate(symbols):
            listed = listing.get(symbol, f"{2010 if market == 'A' else 2020}-01-{index+1:02d}")
            for adjust in ("raw", "qfq", "hfq"):
                coverage.append({
                    "symbol": symbol, "market": market, "listing_date": listed,
                    "quality_status": "PASS", "adjust": adjust,
                })
            directory = (
                tmp_path / "data/raw/stage17/equity_profile" / f"run_id={STAGE17_RUN}"
                / f"market={market}" / f"symbol={symbol}"
            )
            directory.mkdir(parents=True)
            data_path = directory / "data.parquet"
            pd.DataFrame({"symbol": [symbol]}).to_parquet(data_path, index=False)
            (directory / "metadata.json").write_text(json.dumps({
                "run_id": STAGE17_RUN, "quality_status": "PASS", "market": market,
                "symbol": symbol, "exchange": "HKEX" if market == "HK" else ("SH" if symbol.startswith("6") else "SZ"),
                "data_sha256": file_sha256(data_path),
            }), encoding="utf-8")
    pd.DataFrame(coverage).to_csv(stage17_report / "daily_coverage.csv", index=False)
    evidence_dir = tmp_path / "reports/stage18" / STAGE1811_RUN
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "stage18_1_1_spot_retest.json").write_text(json.dumps({
        "run_id": STAGE1811_RUN, "akshare_version": "1.18.80",
        "finished_at": "2026-08-27T04:06:11+00:00",
        "results": [
            {"interface": "stock_zh_a_spot_em", "market": "A", "terminal_status": "FAIL", "error_type": "connection_error", "attempts": [{"attempt": 1}, {"attempt": 2}, {"attempt": 3}]},
            {"interface": "stock_hk_spot_em", "market": "HK", "terminal_status": "FAIL", "error_type": "connection_error", "attempts": [{"attempt": 1}, {"attempt": 2}, {"attempt": 3}]},
        ],
        "governance": {
            "status": "BLOCKED", "stage18_2_authorized": False,
            "next_permitted_task": next_task or "Stage 18.1.2 alternative real-time valuation provider capability audit",
        },
    }), encoding="utf-8")
    return tmp_path / "config/stage18_valuation_audit.yml"


def test_config_rejects_ingestion_eligible_audit(tmp_path):
    payload = yaml.safe_load((ROOT / "config/stage18_valuation_audit.yml").read_text(encoding="utf-8"))
    payload["analysis"]["eligible_for_stage18_2_ingestion"] = True
    path = tmp_path / "bad.yml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    with pytest.raises(Exception, match="audit-only"):
        load_stage18_valuation_config(path)


def test_wrong_1811_gate_blocks_before_network(tmp_path):
    config = _build_workspace(tmp_path, next_task="Stage 18.2")
    adapter = FakeValuationAdapter()
    with pytest.raises(Stage18Blocked, match="does not authorize"):
        run_stage18_valuation_audit(
            root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
            adapter=adapter,
        )
    assert adapter.calls == []


def test_capability_registry_separates_provider_failure_and_selects_complete_provider(tmp_path):
    config = _build_workspace(tmp_path)
    adapter = FakeValuationAdapter()
    run_id = "22222222-2222-4222-8222-222222222222"
    report, code = run_stage18_valuation_audit(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        run_id=run_id, adapter=adapter,
        clock=lambda: datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc),
    )
    assert code == 0 and report["status"] == "PASS"
    assert report["stage18_2_authorized"] is False
    matrix = pd.read_csv(tmp_path / "reports/stage18" / run_id / "valuation_capability_matrix.csv")
    assert dict(zip(matrix.market, matrix.status)) == {"A": "PASS", "HK": "PASS"}
    selected = dict(zip(matrix.market, matrix.selected_provider))
    assert selected["A"] == "EastmoneyDataCenter[valuation_comparison+scale_comparison]"
    assert selected["HK"] == "stock_hk_financial_indicator_em"
    inventory = pd.read_csv(tmp_path / "reports/stage18" / run_id / "valuation_provider_inventory.csv")
    frozen = inventory.loc[inventory["interface"].isin(["stock_zh_a_spot_em", "stock_hk_spot_em"])]
    assert set(frozen.status) == {"FAIL"}
    assert set(frozen.rejection_reason) == {"connection_error"}
    sina = inventory.loc[inventory.interface.eq("stock_zh_a_spot")]
    assert set(sina.status) == {"UNAVAILABLE"}
    assert sina.quote_capability.all()
    assert inventory.audit_only.all()
    assert not inventory.eligible_for_stage18_2_ingestion.any()
    assert sum(name == "stock_zh_a_spot" for name, _params in adapter.calls) == 1
    assert sum(name == "stock_zh_a_spot_tx" for name, _params in adapter.calls) == 1
    metadata = list((tmp_path / "data/raw/stage18/valuation_provider_audit").rglob("metadata.json"))
    assert metadata
    for path in metadata:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["asset_role"] == "valuation_provider_audit"
        assert payload["audit_only"] is True
        assert payload["eligible_for_stage18_2_ingestion"] is False
