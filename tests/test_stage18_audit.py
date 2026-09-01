from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from akshare_data_test.adapters.stock_finance import FinancialCall
from akshare_data_test.stage18_audit import (
    Security, Stage18Blocked, run_stage18_interface_audit, select_samples,
)
from akshare_data_test.stage18_config import load_stage18_config
from akshare_data_test.storage.raw_store import file_sha256


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_RUN = "4a5599fb-9e60-4013-9c0c-69fcc25a98b2"


class FakeAdapter:
    akshare_version = "test"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[tuple[str, object], ...]]] = []

    def inspect_function(self, _name: str):
        return True, "(**kwargs)"

    def call(self, name, parameters, **_kwargs):
        self.calls.append((name, tuple(sorted(parameters.items()))))
        if name == "stock_zh_a_spot_em":
            frame = pd.DataFrame({
                "代码": ["600763", "000100", "603259"],
                "市盈率-动态": [10.0, 11.0, 12.0], "市净率": [1.0, 1.1, 1.2],
                "总市值": [100, 110, 120],
            })
        elif name == "stock_hk_spot_em":
            frame = pd.DataFrame({
                "代码": ["08365", "09669"], "最新价": [1.0, 2.0],
            })
        elif name == "stock_hk_financial_indicator_em":
            frame = pd.DataFrame({
                "报告日期": ["2025-12-31"], "市盈率": [8.0], "市净率": [1.0],
                "总市值(港元)": [100.0],
            })
        else:
            frame = pd.DataFrame({
                "REPORT_DATE": ["2024-12-31", "2025-06-30"],
                "ANNOUNCEMENT_DATE": ["2025-03-01", "2025-08-01"],
                "VALUE": [1.0, 2.0],
            })
        return FinancialCall(frame, 1, "success")


def _security(symbol: str, market: str, exchange: str, listed: str) -> Security:
    return Security(symbol, market, exchange, date.fromisoformat(listed), "metadata.json")


def test_sample_selection_is_deterministic():
    securities = [
        _security("600002", "A", "SH", "2001-01-01"),
        _security("600001", "A", "SH", "2001-01-01"),
        _security("000001", "A", "SZ", "2000-01-01"),
        _security("300001", "A", "SZ", "2020-01-01"),
        _security("00002.HK", "HK", "HKEX", "2019-01-01"),
        _security("00001.HK", "HK", "HKEX", "2018-01-01"),
    ]
    selected, reasons = select_samples(list(reversed(securities)))
    assert [item.symbol for item in selected] == [
        "600001", "000001", "300001", "00001.HK", "00002.HK",
    ]
    assert reasons[0]["reason"] == "earliest_listed_SH"


def _build_upstream(tmp_path: Path, *, authorized: bool = True) -> Path:
    for relative in (
        "config/universe.yml", "config/metric_definition.yml", "docs/stage0_scope.md",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    config_path = tmp_path / "config/stage18.yml"
    shutil.copy2(ROOT / "config/stage18.yml", config_path)
    report_dir = tmp_path / "reports/stage17" / UPSTREAM_RUN
    report_dir.mkdir(parents=True)
    (report_dir / "stage17_run.json").write_text(json.dumps({
        "run_id": UPSTREAM_RUN, "status": "PASS", "stage18_authorized": authorized,
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
    rows = []
    for market, symbols in (("A", a_symbols), ("HK", h_symbols)):
        for index, symbol in enumerate(symbols):
            default_year = 2010 if market == "A" else 2020
            listed = listing.get(symbol, f"{default_year}-01-{(index % 27) + 1:02d}")
            for adjust in ("raw", "qfq", "hfq"):
                rows.append({
                    "symbol": symbol, "market": market, "listing_date": listed,
                    "quality_status": "PASS", "adjust": adjust,
                })
            directory = (
                tmp_path / "data/raw/stage17/equity_profile" / f"run_id={UPSTREAM_RUN}"
                / f"market={market}" / f"symbol={symbol}"
            )
            directory.mkdir(parents=True)
            data_path = directory / "data.parquet"
            pd.DataFrame({"symbol": [symbol]}).to_parquet(data_path, index=False)
            (directory / "metadata.json").write_text(json.dumps({
                "run_id": UPSTREAM_RUN, "quality_status": "PASS", "market": market,
                "symbol": symbol,
                "exchange": "HKEX" if market == "HK" else ("SH" if symbol.startswith("6") else "SZ"),
                "data_sha256": file_sha256(data_path),
            }), encoding="utf-8")
    pd.DataFrame(rows).to_csv(report_dir / "daily_coverage.csv", index=False)
    return config_path


def test_upstream_authorization_blocks_before_adapter_call(tmp_path):
    config = _build_upstream(tmp_path, authorized=False)
    adapter = FakeAdapter()
    with pytest.raises(Stage18Blocked, match="authorization mismatch"):
        run_stage18_interface_audit(
            root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
            adapter=adapter,
        )
    assert adapter.calls == []


def test_offline_audit_writes_append_only_interface_audit_evidence(tmp_path):
    config = _build_upstream(tmp_path)
    adapter = FakeAdapter()
    clock = lambda: datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)
    run_id = "11111111-1111-4111-8111-111111111118"
    result, code = run_stage18_interface_audit(
        root=tmp_path, config_path=config, as_of_date=date(2026, 7, 27),
        run_id=run_id, adapter=adapter, clock=clock,
    )
    assert code == 0 and result["status"] == "PASS"
    assert result["sample_symbols"] == [
        "600763", "000100", "603259", "08365.HK", "09669.HK",
    ]
    assert result["inventory_row_count"] == 38
    assert len(adapter.calls) == 35
    inventory = pd.read_csv(tmp_path / "reports/stage18/interface_inventory.csv")
    assert set(inventory["asset_role"]) == {"interface_audit"}
    assert inventory["audit_only"].all()
    assert not inventory["eligible_for_stage18_2_ingestion"].any()
    assert inventory.loc[
        inventory.status.eq("PASS"), "eligible_for_capability_assessment"
    ].all()
    assert not inventory.loc[
        inventory.status.ne("PASS"), "eligible_for_capability_assessment"
    ].any()
    assert set(inventory.status).issubset({"PASS", "UNAVAILABLE"})
    assert set(inventory.loc[
        inventory.interface.eq("stock_hk_spot_em"), "status"
    ]) == {"UNAVAILABLE"}
    assert (tmp_path / "reports/stage18" / run_id / "stage18_1_manifest.json").is_file()
    metadata_paths = list(
        (tmp_path / "data/raw/stage18/interface_audit").rglob("metadata.json")
    )
    assert metadata_paths
    for metadata_path in metadata_paths:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["asset_role"] == "interface_audit"
        assert metadata["audit_only"] is True
        assert metadata["eligible_for_stage18_2_ingestion"] is False
        assert metadata["eligible_for_capability_assessment"] == (
            metadata["status"] == "PASS"
        )


def test_config_rejects_snapshot_backfill_policy(tmp_path):
    payload = yaml.safe_load((ROOT / "config/stage18.yml").read_text(encoding="utf-8"))
    payload["analysis"]["current_snapshot_policy"] = "backfill"
    path = tmp_path / "stage18.yml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    with pytest.raises(Exception, match="audit_only"):
        load_stage18_config(path)
