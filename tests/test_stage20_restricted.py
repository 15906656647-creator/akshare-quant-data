from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.stage20 import (
    CapabilityGate,
    Stage20Error,
    add_moving_averages,
    aggregate_weekly,
    scan_public_assets,
    validate_stage20_entry,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "reports/stage19/conditional_closure/stage20_restricted_downstream_contract.json"
CLOSURE = ROOT / "reports/stage19/conditional_closure/stage19_conditional_closure.json"
RUN_ID = "d2f02a9d-901f-4e99-9f4f-20b6d17c77ef"
REPORT = ROOT / "reports/stage20" / RUN_ID
PUBLIC = ROOT / "web/stage20/public/data"


def _write_entry_pair(tmp_path: Path, mutate_contract=None, mutate_closure=None):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    if mutate_contract:
        mutate_contract(contract)
    if mutate_closure:
        mutate_closure(closure)
    closure_path = tmp_path / "closure.json"
    contract_path = tmp_path / "contract.json"
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    contract["conditional_closure_reference"] = "closure.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return contract_path, closure_path


def test_real_restricted_contract_authorizes_only_restricted_scope():
    contract, gate = validate_stage20_entry(ROOT, CONTRACT, CLOSURE)
    assert contract["restricted_entry_authorized"] is True
    assert contract["full_entry_authorized"] is False
    assert contract["formal_event_release_status"] == "BLOCKED"
    assert gate.is_capability_allowed("daily_kline")


def test_missing_contract_fails_closed(tmp_path):
    with pytest.raises(Stage20Error):
        validate_stage20_entry(tmp_path, tmp_path / "missing.json", tmp_path / "closure.json")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.pop("authorization_mode"),
        lambda c: c.update(restricted_entry_authorized=False),
        lambda c: c.update(authorization_mode="FULL"),
        lambda c: c.update(authorization_scope="EVENT_AND_NON_EVENT"),
        lambda c: c.update(formal_event_release_status="PASS"),
        lambda c: c.update(full_entry_authorized=True),
    ],
)
def test_invalid_or_escalated_contract_fails_closed(tmp_path, mutation):
    contract, closure = _write_entry_pair(tmp_path, mutate_contract=mutation)
    with pytest.raises(Stage20Error):
        validate_stage20_entry(tmp_path, contract, closure)


def test_contract_and_closure_conflict_fails_closed(tmp_path):
    contract, closure = _write_entry_pair(tmp_path, mutate_closure=lambda c: c.update(remediation_status="CLOSED"))
    with pytest.raises(Stage20Error):
        validate_stage20_entry(tmp_path, contract, closure)


def test_evidence_reference_mismatch_fails_closed(tmp_path):
    contract, closure = _write_entry_pair(tmp_path)
    payload = json.loads(contract.read_text())
    payload["conditional_closure_reference"] = "wrong.json"
    contract.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Stage20Error):
        validate_stage20_entry(tmp_path, contract, closure)


def test_capability_gate_allows_authorized_and_blocks_event_and_unknown():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    gate = CapabilityGate.from_contract(contract)
    gate.require("ma21")
    with pytest.raises(Stage20Error):
        gate.require("official_limit_up_count")
    with pytest.raises(Stage20Error):
        gate.require("made_up_capability")


def test_ma_windows_have_null_warmup_and_do_not_cross_series():
    first = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=25), "close": range(1, 26)})
    second = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=25), "close": range(101, 126)})
    windows = [3, 5, 7, 10, 13, 20, 21]
    a = add_moving_averages(first, windows)
    b = add_moving_averages(second, windows)
    for window in windows:
        assert a[f"ma{window}"].iloc[: window - 1].isna().all()
        assert a[f"ma{window}"].iloc[window - 1] == pytest.approx((1 + window) / 2)
        assert b[f"ma{window}"].iloc[window - 1] == pytest.approx(100 + (1 + window) / 2)


def test_weekly_aggregation_uses_trading_rows_and_friday_labels():
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-08-03", "2026-08-04", "2026-08-07", "2026-08-10"]),
            "open": [10, 11, 12, 20], "high": [12, 13, 15, 22], "low": [9, 10, 11, 19],
            "close": [11, 12, 14, 21], "volume": [1, 2, 3, 4], "amount": [10, 20, 30, 40],
            "turnover": [0.1, 0.2, 0.3, 0.4],
        }
    )
    weekly = aggregate_weekly(frame)
    assert len(weekly) == 2
    assert weekly.iloc[0]["open"] == 10
    assert weekly.iloc[0]["high"] == 15
    assert weekly.iloc[0]["low"] == 9
    assert weekly.iloc[0]["close"] == 14
    assert weekly.iloc[0]["volume"] == 6
    assert weekly.iloc[0]["time"].strftime("%Y-%m-%d") == "2026-08-07"


def test_generated_manifest_preserves_layered_statuses():
    manifest = json.loads((REPORT / "stage20_manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry_contract_status"] == "PASS"
    assert manifest["restricted_scope_status"] == "PASS"
    assert manifest["full_scope_status"] == "NOT_AUTHORIZED"
    assert manifest["event_scope_status"] == "BLOCKED"
    assert manifest["stage19_event_status"] == "BLOCKED"
    assert manifest["stage21_status"] == "NOT_STARTED"
    assert manifest["supported_ma"] == [3, 5, 7, 10, 13, 20, 21]


def test_public_metadata_routes_only_formal_pass_runs_and_statuses():
    meta = json.loads((PUBLIC / "metadata.json").read_text(encoding="utf-8"))
    assert meta["lineage"]["stage17_run_id"] == "4a5599fb-9e60-4013-9c0c-69fcc25a98b2"
    assert meta["lineage"]["stage18_feature_run_id"] == "1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8"
    assert meta["event"]["formal_event_release"] == "BLOCKED"
    assert meta["event"]["value"] is None
    assert meta["stage21_status"] == "NOT_STARTED"
    assert len(meta["securities"]) == 24
    assert set(meta["series"]) == {x["symbol"] for x in meta["securities"]}


def test_adjustment_is_consistent_for_kline_and_ma():
    payload = json.loads((PUBLIC / "series/A/000100/1d/qfq.json").read_text(encoding="utf-8"))
    assert payload["adjustment"] == "qfq"
    assert payload["source_dataset"] == "daily:000100:qfq"
    assert all(f"ma{w}" in payload["rows"][-1] for w in (3, 5, 7, 10, 13, 20, 21))
    assert all(payload["rows"][i]["ma21"] is None for i in range(20))


def test_market_minute_availability_is_not_invented():
    meta = json.loads((PUBLIC / "metadata.json").read_text(encoding="utf-8"))
    a_share = next(x for x in meta["securities"] if x["market"] == "A")
    eth = next(x for x in meta["securities"] if x["symbol"] == "ETHUSDT")
    assert set(a_share["minute_intervals"].values()) == {"UNAVAILABLE"}
    assert eth["minute_intervals"] == {"1m": "AVAILABLE", "3m": "AVAILABLE", "5m": "AVAILABLE", "15m": "AVAILABLE"}


def test_fundamentals_preserve_pit_and_unavailable_valuation():
    payload = json.loads((PUBLIC / "fundamentals/A/000100.json").read_text(encoding="utf-8"))
    assert payload["availability_status"] == "AVAILABLE"
    assert all(x["announcement_date"] <= "2026-07-27" for x in payload["features"] if x["announcement_date"])
    assert payload["valuation"]["pe"]["value"] is None
    assert payload["valuation"]["pe"]["availability_status"] == "UNAVAILABLE"


def test_eth_does_not_receive_stock_fundamentals():
    payload = json.loads((PUBLIC / "fundamentals/CRYPTO/ETHUSDT.json").read_text(encoding="utf-8"))
    assert payload["availability_status"] == "NOT_APPLICABLE"
    assert payload["features"] == []


def test_comparison_units_remain_market_specific():
    meta = json.loads((PUBLIC / "metadata.json").read_text(encoding="utf-8"))
    currencies = {x["market"]: x["currency"] for x in meta["securities"]}
    assert currencies == {"A": "CNY", "HK": "HKD", "CRYPTO": "USDT"}


def test_public_scan_detects_candidate_and_absolute_path(tmp_path):
    (tmp_path / "safe.json").write_text('{"ok":true}', encoding="utf-8")
    assert scan_public_assets(tmp_path)["status"] == "PASS"
    (tmp_path / "bad.json").write_text('limit_event_candidate E:/secret', encoding="utf-8")
    result = scan_public_assets(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["candidate_data_leak_count"] == 1


def test_real_public_export_has_zero_candidate_leaks_and_no_internal_db():
    result = scan_public_assets(PUBLIC)
    assert result["status"] == "PASS"
    assert result["candidate_data_leak_count"] == 0
    assert not any(path.suffix == ".duckdb" for path in PUBLIC.rglob("*"))


def test_frontend_has_no_limit_inference_or_event_filter_logic():
    source = (ROOT / "web/stage20/src/main.jsx").read_text(encoding="utf-8").lower()
    forbidden = ("pct_change >=", "previous_close", ">= 1.10", "official_limit_up_count", "event_based_screening")
    assert all(token not in source for token in forbidden)
    assert "value = null" in source


def test_frontend_smoke_pages_and_lazy_loading_contract():
    source = (ROOT / "web/stage20/src/main.jsx").read_text(encoding="utf-8")
    for component in ("Dashboard", "Detail", "Compare", "Screen", "Quality"):
        assert f"function {component}" in source
    assert "React.lazy(() => import('react-plotly.js'))" in source
    assert "fetch(path)" in source
    assert "meta.series[symbol]" in source
    assert "时间范围" in source
    assert "全部指标" in source
    assert "证券代码" in source
    assert "最低成交量" in source
    assert "最低换手率" in source


def test_production_bundle_does_not_embed_full_history_or_machine_path():
    dist = ROOT / "web/stage20/dist"
    assert (dist / "index.html").is_file()
    js_files = list((dist / "assets").glob("*.js"))
    assert js_files
    text = "\n".join(path.read_text(encoding="utf-8") for path in js_files)
    assert "4a5599fb-9e60-4013-9c0c-69fcc25a98b2" not in text
    assert "E:/大学" not in text and "E:\\大学" not in text
    assert "limit_event_candidate" not in text


def test_upstream_governance_files_remain_blocked_and_open():
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    assert closure["management_status"] == "CONDITIONALLY_CLOSED"
    assert closure["formal_event_release_status"] == "BLOCKED"
    assert closure["remediation_status"] == "OPEN"
