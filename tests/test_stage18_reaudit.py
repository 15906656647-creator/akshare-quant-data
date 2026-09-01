from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.adapters.stage18_valuation import AttemptEvidence, ValuationCall
from akshare_data_test.adapters.stock_finance import FinancialCall
from akshare_data_test.stage18_audit import Stage18Blocked
from akshare_data_test.stage18_reaudit import run_stage18_full_reaudit
from akshare_data_test.storage.raw_store import file_sha256


ROOT = Path(__file__).resolve().parents[1]
STAGE17_RUN = "4a5599fb-9e60-4013-9c0c-69fcc25a98b2"
VALUATION_RUN = "9c869e51-ae27-4b7e-895c-79a2c978258c"
FROZEN_RUN = "19660ce0-e73d-4d0c-8451-cfaee0b726da"


class FakeFundamentalAdapter:
    akshare_version = "test"

    def __init__(self) -> None:
        self.calls = []

    def inspect_function(self, _name):
        return True, "(**kwargs)"

    def call(self, name, parameters, **_kwargs):
        self.calls.append((name, parameters))
        return FinancialCall(pd.DataFrame({
            "REPORT_DATE": ["2025-06-30"],
            "ANNOUNCEMENT_DATE": ["2025-08-01"], "VALUE": [1.0],
        }), 1, "success")


class FakeValuationAdapter:
    akshare_version = "test"

    def __init__(self) -> None:
        self.calls = []

    def inspect_function(self, _name):
        return True, "(**kwargs)", "fake", "fake.py"

    def call(self, name, parameters, **_kwargs):
        self.calls.append((name, parameters))
        if name == "stock_zh_valuation_comparison_em":
            frame = pd.DataFrame({"市盈率TTM": [10.0], "市净率": [1.2]})
        elif name == "stock_zh_scale_comparison_em":
            frame = pd.DataFrame({"总市值": [100.0], "流通市值": [80.0]})
        else:
            frame = pd.DataFrame({"市盈率": [9.0], "市净率": [1.1], "总市值(港元)": [90.0]})
        attempt = AttemptEvidence(
            1, "2026-08-27T00:00:00+00:00", "2026-08-27T00:00:01+00:00",
            1.0, "success", "", "",
        )
        return ValuationCall(frame, "success", "", "", (attempt,))


def _record(path: Path, root: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _build_fixture(tmp_path: Path, *, valuation_status: str = "PASS") -> Path:
    for relative in (
        "config/universe.yml", "config/metric_definition.yml", "docs/stage0_scope.md",
        "config/stage18.yml", "config/stage18_reaudit.yml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    stage17_dir = tmp_path / "reports/stage17" / STAGE17_RUN
    stage17_dir.mkdir(parents=True)
    (stage17_dir / "stage17_run.json").write_text(json.dumps({
        "run_id": STAGE17_RUN, "status": "PASS", "stage18_authorized": True,
        "blocked_risks": [], "unavailable_items": [],
        "counts": {"daily_quality_pass_count": 69},
    }), encoding="utf-8")
    a_symbols = [
        "002067", "002600", "002230", "600763", "603259", "603799",
        "601012", "600438", "002361", "601500", "600231", "300274",
        "601636", "002129", "000100", "300433",
    ]
    h_symbols = [
        "02180.HK", "08365.HK", "08462.HK", "02076.HK", "06100.HK",
        "06919.HK", "09669.HK",
    ]
    listing = {
        "600763": "1996-10-30", "000100": "2004-01-30", "603259": "2018-05-08",
        "08365.HK": "2017-05-26", "09669.HK": "2023-04-13",
    }
    coverage = []
    raw_records = []
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
            metadata_path = directory / "metadata.json"
            metadata_path.write_text(json.dumps({
                "run_id": STAGE17_RUN, "quality_status": "PASS", "market": market,
                "symbol": symbol,
                "exchange": "HKEX" if market == "HK" else ("SH" if symbol.startswith("6") else "SZ"),
                "data_sha256": file_sha256(data_path),
            }), encoding="utf-8")
            raw_records.extend((_record(data_path, tmp_path), _record(metadata_path, tmp_path)))
    filler = tmp_path / "data/raw/stage17/test_filler" / f"run_id={STAGE17_RUN}"
    filler.mkdir(parents=True)
    for index in range(196 - len(raw_records)):
        path = filler / f"file_{index:03d}.txt"
        path.write_text(str(index), encoding="utf-8")
        raw_records.append(_record(path, tmp_path))
    pd.DataFrame(coverage).to_csv(stage17_dir / "daily_coverage.csv", index=False)
    (stage17_dir / "stage17_manifest.json").write_text(json.dumps({
        "run_id": STAGE17_RUN, "status": "PASS", "raw_files": raw_records,
    }), encoding="utf-8")

    valuation_dir = tmp_path / "reports/stage18" / VALUATION_RUN
    valuation_dir.mkdir(parents=True)
    evidence_file = valuation_dir / "valuation_provider_audit.md"
    evidence_file.write_text("audit", encoding="utf-8")
    (valuation_dir / "stage18_1_2_run.json").write_text(json.dumps({
        "run_id": VALUATION_RUN, "status": valuation_status,
        "stage18_2_authorized": False,
        "valuation_capabilities": [
            {"market": "A", "selected_provider": "EastmoneyDataCenter[valuation_comparison+scale_comparison]"},
            {"market": "HK", "selected_provider": "stock_hk_financial_indicator_em"},
        ],
    }), encoding="utf-8")
    (valuation_dir / "stage18_1_2_manifest.json").write_text(json.dumps({
        "run_id": VALUATION_RUN, "status": valuation_status,
        "files": [{
            "path": evidence_file.relative_to(tmp_path).as_posix(),
            "size": evidence_file.stat().st_size, "sha256": file_sha256(evidence_file),
        }],
    }), encoding="utf-8")
    frozen_dir = tmp_path / "reports/stage18" / FROZEN_RUN
    frozen_dir.mkdir(parents=True)
    attempts = [{"attempt": i, "duration_ms": 1.0, "status": "failed"} for i in range(1, 4)]
    (frozen_dir / "stage18_1_1_spot_retest.json").write_text(json.dumps({
        "run_id": FROZEN_RUN, "analysis_as_of_date": "2026-07-27",
        "started_at": "2026-08-27T00:00:00+00:00",
        "finished_at": "2026-08-27T00:00:01+00:00",
        "results": [
            {"interface": "stock_zh_a_spot_em", "market": "A", "terminal_status": "FAIL", "error_type": "connection_error", "attempts": attempts},
            {"interface": "stock_hk_spot_em", "market": "HK", "terminal_status": "FAIL", "error_type": "connection_error", "attempts": attempts},
        ],
    }), encoding="utf-8")
    return tmp_path / "config/stage18_reaudit.yml"


def test_full_reaudit_passes_by_capability_and_keeps_audit_assets_isolated(tmp_path):
    config = _build_fixture(tmp_path)
    fundamental = FakeFundamentalAdapter()
    valuation = FakeValuationAdapter()
    run_id = "33333333-3333-4333-8333-333333333333"
    clock = lambda: datetime(2026, 8, 27, 2, 0, tzinfo=timezone.utc)
    result, code = run_stage18_full_reaudit(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        run_id=run_id, fundamental_adapter=fundamental,
        valuation_adapter=valuation, clock=clock,
    )
    assert code == 0 and result["status"] == "PASS"
    assert result["stage18_2_authorized"] is True
    assert result["stage18_2_started"] is False
    assert len(fundamental.calls) == 31
    assert len(valuation.calls) == 8
    report_dir = tmp_path / "reports/stage18" / run_id
    capability = pd.read_csv(report_dir / "capability_matrix.csv")
    assert len(capability) == 11 and set(capability.status) == {"PASS"}
    inventory = pd.read_csv(report_dir / "interface_inventory.csv")
    rejected = inventory[inventory.provider_role.eq("frozen_rejected_provider")]
    assert len(rejected) == 2 and set(rejected.status) == {"FAIL"}
    assert not rejected.affects_capability.any()
    metadata = list((tmp_path / "data/raw/stage18/interface_audit" / f"run_id={run_id}").rglob("metadata.json"))
    assert len(metadata) == 39
    for path in metadata:
        item = json.loads(path.read_text(encoding="utf-8"))
        assert item["asset_role"] == "interface_audit"
        assert item["audit_only"] is True
        assert item["eligible_for_stage18_2_ingestion"] is False


def test_bad_valuation_evidence_blocks_before_network(tmp_path):
    config = _build_fixture(tmp_path, valuation_status="BLOCKED")
    fundamental = FakeFundamentalAdapter()
    valuation = FakeValuationAdapter()
    with pytest.raises(Stage18Blocked, match="PASS evidence"):
        run_stage18_full_reaudit(
            root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
            fundamental_adapter=fundamental, valuation_adapter=valuation,
        )
    assert fundamental.calls == [] and valuation.calls == []


def test_validate_only_is_network_free_and_reports_expected_scope(tmp_path):
    config = _build_fixture(tmp_path)
    fundamental = FakeFundamentalAdapter()
    valuation = FakeValuationAdapter()
    result, code = run_stage18_full_reaudit(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        validate_only=True, fundamental_adapter=fundamental,
        valuation_adapter=valuation,
    )
    assert code == 0 and result["status"] == "READY"
    assert result["planned_capability_count"] == 11
    assert result["network_call_count"] == 39
    assert fundamental.calls == [] and valuation.calls == []
